---
name: your-token
description: Tracks the AI's own token usage (input vs output, thinking, tool calls, file-reading depth, reasoning effort, model, plan) for claude.ai subscriptions (Free/Pro/Max, 5-hour window) AND for the Claude API (pay-as-you-go dollar spend, optional spend cap, rate limits), plus how full the current conversation's context is. Warns before a limit runs out, suggests savings, and writes a HANDOFF.md plus work-in-progress files. Use this skill whenever the user mentions token limits, usage limits, the 5-hour window, API cost or spend, rate limits, running out of quota or context, "your token", handoff, checkpointing a long task, or when a long multi-step task (many tool calls, large files, high effort, expensive model) is likely to hit a limit, even if the user doesn't name the skill.
---

# your-token

You cannot see the real remaining limit. This skill **estimates** usage, compares it with a budget, and helps you hand off cleanly **before** a limit hits. Anthropic publishes no exact free-tier numbers, so every claude.ai budget here is a hypothesis to calibrate; the input-vs-output classification is reliable because you know what you read and wrote. In API mode the numbers can be **exact**, because API responses include a `usage` object.

Files: `plans.json` (plans, multipliers, models/prices, context window, effort profiles), `scripts/ledger.py`, `scripts/count_tokens.py`, `assets/handoff_template.md`.

The scripts are standard-library Python only: no network access, no other programs launched. They read `plans.json` and files you pass explicitly, and write only the ledger file (`ledger.json`) and an optional `--out` file such as `HANDOFF.md`.

## 0. Setup: no interview needed

The ledger **creates itself** the first time any command runs (Free plan, Sonnet 5.5 by default). Do not quiz the user. Pick the mode from context:

- **claude.ai chat or app** (the default): just start logging turns. If the user has said which plan they have, run `plan --set claude_pro|claude_max5|claude_max20`. If they volunteer when their window started, run `window --started-ago-min N`. Otherwise the window simply starts at the first logged turn.
- **Claude API, SDK, Agent SDK, Claude Code with an API key, or the user is building on the API**: run `python scripts/ledger.py init --api [--budget-usd N] [--period session|day|month] [--model M]`. A spend cap is optional.
- If you assumed the plan, mention it **once, in one line**, with how to change it ("I'm assuming the Free plan; tell me if you're on Pro/Max/API"). Ask a question only if the user's goal actually depends on the answer (for example they ask "how much can I still do today?" and the plan is unknown).

Budget on claude.ai = `free_budget_tokens` x plan multiplier (Pro >=5x, Max 5x = 25x, Max 20x = 100x Free; the multiples are Anthropic's, the Free baseline is an unverified hypothesis). The skill does not track Max plans' weekly limits.

## 1. Two separate clocks: track both

| Clock | Measures | Resets when |
|---|---|---|
| **USAGE** | claude.ai: weighted tokens in the rolling **5-hour window** vs budget. API: **USD spend** in the chosen period vs an optional cap | window/period ends (API `session` never auto-resets) |
| **CONTEXT** | how full this conversation is (default limit 200k; change with `calibrate --context-limit`) | only in a **new chat/session** |

Hitting USAGE = wait for the reset (or upgrade / raise the cap). Hitting CONTEXT = this conversation is full; continue in a new chat/session from HANDOFF.md. A new window doesn't empty the context; a new chat doesn't refresh the window.

## 2. Classify everything by source

| Type | What | Counts as |
|---|---|---|
| system | system prompt, this skill, memory | input |
| user | user messages, uploads | input |
| tool_result | search / bash / file-view output | input |
| assistant_text | what you write to the user | output |
| tool_call | code, commands, arguments you send | output |
| thinking | your reasoning (hidden but billed) | output |
| created_file | files you create | output |

Rule: **read = input, generated = output.**

## 3. Cost model

- **Every model call re-reads the whole context** (k tool calls = k+1 reads). The bigger the conversation, the more each message costs, even a one-line follow-up. The ledger shows this as **MARGINAL COST** (cost of the next message) and **FORECAST** (turns left here vs in a fresh chat from HANDOFF.md).
- **claude.ai cost:** `(input + output x out_ratio) x usage_weight`. `out_ratio` = the model's output/input price ratio (5 for all current models). `usage_weight` is relative to Sonnet 5.5 and is a **guess** (API list prices Oct 2026, $/MTok in/out: Haiku 5.5 0.10/0.50, Sonnet 5.5 2/10, Opus 5.5 4/20, Fable 5.1 10/50; Mythos 5.1 unpublished, assumed = Fable). Real claude.ai consumption is not documented; calibrate with `calibrate --model-weight opus-5.5=1.8`.
- **API cost (USD):** `(input x price_in + output x price_out) / 1,000,000`. With exact usage: cache reads cost 0.1x input, 5-minute cache writes 1.25x, 1-hour writes 2x, Batch API 0.5x (multipliers live in `plans.json` > `api_pricing`; verify against the current pricing page if exact dollars matter). Thinking tokens are billed as output and are already inside `usage.output_tokens`.
- **Cache:** re-reads are discounted by `cache_discount` (Free default 0 = every re-read counted in full; set `calibrate --cache-discount 0.9` if an API app uses prompt caching). The discount is **dropped for a turn when the gap since the previous turn exceeds 5 minutes** (cache expired); the script measures the gap itself, or pass `--gap-min`.
- Reading depth: `skim` (grep/head/`--lines a-b`) counts only what entered context; `deep` counts the whole file x re-reads. Output weighs more than input; thinking grows with effort (`thinking_ratio`).
- The Free default of 30000 per window is an **unverified third-party estimate**; treat it as a conservative start and let calibration replace it.

## 4. Read your own settings

At session start and whenever they change: **effort** (a number in your context; inverted scale: `4=low, 3=medium, 2=high, 1=extra, 0=max`; assume `3` if absent) and **model** (from your system prompt or the API request, e.g. "Claude Opus 5.5" or `claude-opus-5-5` -> `opus-5.5`; pass `--model` on the turn it changes). The script warns if the model isn't normally in the plan.

## 5. Workflow

**Language.** Script output is English. Always relay messages to the user **in the language they are writing in**, in plain wording (say "new chat" or "new window" in their language, not in English, unless they write English). Never paste raw ledger output unless asked.

### claude.ai (code execution available)
1. Before a big task: `predict --effort N [--tool-calls K --out-chars C --result-tokens R --model M]`. If USAGE or CONTEXT would pass the handoff threshold, lower effort/model, split the task, or hand off first.
2. When reading files: `add --type tool_result --file F [--lines a-b | --read-mode skim|deep --times N]`.
3. **End of every turn, one call** (pass character counts, never conversation text):
   `turn --effort N --tool-calls K --user-chars U --out-chars O [--created-chars C] [--result-tokens R] --lang vi|en|code|mixed [--model M]`
   (`--lang` is only the chars-per-token class of the text: `vi` = Vietnamese, `en` = English-like, `code`, or `mixed`.)

### Claude API / agents
1. After **each API response**, log its exact `usage` object (one call per response):
   `api-usage --input <input_tokens> --output <output_tokens> [--cache-read <cache_read_input_tokens>] [--cache-write <cache_creation_input_tokens>] [--cache-write-1h N] [--batch] [--model M]`
   This sets CONTEXT exactly (prompt size + output) and adds exact dollars. If the usage object isn't available, fall back to `turn`.
2. Optional limits you can set once the user knows them: `calibrate --budget-usd N`, `calibrate --rpm N --itpm N --otpm N` (rate limits from the Console). Status then shows `RATE (last 60s)` and warns at 80%.
3. On an HTTP 429 (rate limit): `calibrate --hit-rate-limit` right away (records the observed per-minute rates as limits), then back off and retry. On hitting a spend cap: `calibrate --hit-limit`.
4. Period: `--period day|month` makes the spend cap reset every 24 h / 30 days from the first call; `session` (default) never resets until `reset`.

### Acting on the printed output (both modes)
- `** NEW 5H WINDOW` / `** NEW 24H PERIOD`: usage reset. Tell the user in one line.
- `OK`: continue silently.
- `WARN` (>=70%): one-line heads-up; prioritize; share 1-2 of the SAVING TIPS.
- `HANDOFF` (>=85%): finish the smallest clean unit (never mid-file or mid-function), then hand off (section 6). Say which clock triggered it: USAGE -> the user can also wait for the reset (time shown) or, on API, raise the cap; CONTEXT -> a new chat/session is required.
- `=> OPEN A NEW CHAT`: the next message already costs >=10% of budget and a fresh chat would last longer. Write HANDOFF.md now even if USAGE is low.
- `NO_BUDGET` (claude.ai only): totals only; set a budget with `calibrate --budget N`, or just keep tracking. On the API, having no cap is normal: spend is still reported.

**No code execution:** estimate by hand (chars/2.8 Vietnamese, /4 English, /3.3 code; output x5; each tool call re-reads the context; expensive models x2-5; API dollars = tokens x list price) and hand off at about 85% of the budget the user gave.

## 6. Handoff

1. Copy `assets/handoff_template.md` to `HANDOFF.md` and fill every section concretely (exact stopping point, ordered next steps, decisions + reasons, file list).
2. `python scripts/ledger.py export --out HANDOFF.md` appends the ledger block (plan, model, calibration included).
3. Put `HANDOFF.md` and every in-progress file in `/mnt/user-data/outputs/` and present them with `present_files`. Tell the user in 2-3 lines: how far you got, which clock triggered it, what to do next (new chat + attach the files; or wait for the reset). In API/agent contexts without file presentation, write the files to the working directory and report their paths.
4. In the new chat: `restore --file HANDOFF.md` (plan, model and calibration are kept; no need to re-ask anything).
5. After a manual reset: `reset` (usage only) or `reset --new-chat` (usage + context). Budget, weights, calibration are kept.

## 7. Calibration

- Known budget: `calibrate --budget N` (claude.ai, per 5-hour window, Sonnet-equivalent weighted tokens) or `calibrate --budget-usd N` (API).
- The moment the user says "I just hit the limit": `calibrate --hit-limit` BEFORE any reset. On claude.ai, observations are normalized by plan multiplier so they carry over if the plan changes.
- Also available: `--model-weight NAME=VALUE`, `--context-limit N` (e.g. 1000000 for a long-context model), `--cache-discount X`, `--rpm/--itpm/--otpm`.
- Be honest that claude.ai estimates may be off by tens of percent; thresholds sit below 100% for that reason.

## 8. Don'ts

- Don't claim to know the true remaining limit (API dollar totals are exact only for the calls you logged).
- Don't interrogate the user to set this up; use defaults and correct them when the user gives information.
- Don't let tracking cost more than it saves: one `turn` (or `api-usage`) call per turn/response; `status` only when needed.
- Don't announce routine OK status; speak up at WARN, HANDOFF, window/period reset, new-chat advice, or when asked.
