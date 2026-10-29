---
name: your-token
description: Tracks the AI's own token usage (input vs output, thinking, tool calls, file-reading depth, reasoning effort, which Claude model and which plan) against the plan's 5-hour usage window AND how full the current chat's context is; warns before either runs out, suggests savings, and writes a HANDOFF.md plus work-in-progress files for the user. Use this skill whenever the user mentions token limits, usage limits, the 5-hour window, running out of quota or context, "your token", handoff, checkpointing a long task, or when a long multi-step task (many tool calls, large files, high effort, expensive model) is likely to hit a limit — even if the user doesn't name the skill.
---

# your-token

You cannot see the real remaining limit. This skill **estimates** usage, compares it with a user-calibrated budget, and makes you hand off cleanly **before** a limit hits. Anthropic publishes no exact free-tier numbers, so every budget here is a hypothesis to calibrate; the input-vs-output classification is reliable because you know what you read and wrote.

Files: `plans.json` (plans, multipliers, models/prices, context window, effort profiles), `scripts/ledger.py`, `scripts/count_tokens.py`, `assets/handoff_template.md`.

## 0. First thing in every new chat (or right after installing)

If there is no ledger and no HANDOFF.md ledger block to restore, **ask the user** (use `ask_user_input_v0` buttons when available; two questions max):
1. Which plan? **Free / Pro / Max 5x / Max 20x** / Other. (Claude has no "Plus" tier; if the user says Plus or Pro Plus, confirm which of these they mean.)
2. Roughly how long ago did the current 5-hour window start (their first message since the last reset)?

Then: `python scripts/ledger.py init --plan <claude_free|claude_pro|claude_max5|claude_max20|custom> --model <running model>` and `window --started-ago-min N`.

Budget = `free_budget_tokens` × plan multiplier (Pro ≥5×, Max 5x = 25× Free, Max 20x = 100× Free; these are Anthropic's published multiples, the Free baseline itself is an unverified hypothesis). If the user later upgrades/downgrades: `plan --set <plan>`. When restoring from a HANDOFF, ask only to confirm plan/model are unchanged. The skill does not track Max's weekly limits.

## 1. Two separate clocks — track both

| Clock | Measures | Resets when |
|---|---|---|
| **USAGE** | weighted tokens in the current **5-hour window** vs budget | window ends (rolling 5 h from first message) |
| **CONTEXT** | how full this chat is (default limit 200k) | only in a **new chat** |

Hitting USAGE = wait for the window (or upgrade). Hitting CONTEXT = this chat is full; continue in a new chat with HANDOFF.md. A new window doesn't empty the context; a new chat doesn't refresh the window.

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

- **Every model call re-reads the whole context** (k tool calls = k+1 reads). The bigger the chat, the more each message costs, even a one-line follow-up. The ledger shows this as **CHI PHÍ BIÊN** (cost of the next message) and **DỰ BÁO** (turns left here vs in a fresh chat from HANDOFF.md).
- **Per-model cost:** `(input + output × out_ratio) × usage_weight`. `out_ratio` = model's output/input price ratio (5 for all current models). `usage_weight` is relative to Sonnet 5.5 and is a **guess** (API list prices Oct 2026, $/MTok in/out: Haiku 5.5 0.10/0.50, Sonnet 5.5 2/10, Opus 5.5 4/20, Fable 5.1 10/50; Mythos 5.1 unpublished, assumed = Fable). Real claude.ai consumption is not documented; calibrate with `calibrate --model-weight opus-5.5=1.8`.
- **Cache:** re-reads are discounted by `cache_discount` (Free default 0 = every re-read counted in full, hypothesis). The discount is **dropped for a turn when the gap since the previous turn exceeds 5 minutes** (cache expired); the script measures the gap itself, or pass `--gap-min`.
- Reading depth: `skim` (grep/head/`--lines a-b`) counts only what entered context; `deep` counts the whole file × re-reads. Output weighs more than input; thinking grows with effort (`thinking_ratio`).
- Free default budget 30000 per window is an **unverified third-party estimate**; treat as a conservative start and let calibration replace it.

## 4. Read your own settings

At session start and whenever they change: **effort** (number in your context; scale inverted: `4=low, 3=medium, 2=high, 1=extra, 0=max`; ask if absent) and **model** (from your system prompt, e.g. "Claude Opus 5.5" → `opus-5.5`; pass `--model` on the turn it changes). The script warns if the model isn't normally in the plan.

## 5. Workflow (code execution available)
- **but first you need to know what are users language to respon correctly, don't say mở cửa sổ or mở chat mới if users are not vietnamese**
1. Ask (section 0) → `init` → `window`. Or `restore --file HANDOFF.md`.
2. **Before a big task:** `predict --effort N [--tool-calls K --out-chars C --result-tokens R --model M]`. If USAGE or CONTEXT would pass the handoff threshold → lower effort/model, split the task, or hand off first.
3. When reading files: `add --type tool_result --file F [--lines a-b | --read-mode skim|deep --times N]`.
4. **End of every turn, one call** (pass character counts, never conversation text):
   `turn --effort N --tool-calls K --user-chars U --out-chars O [--created-chars C] [--result-tokens R] --lang vi|en|code|mixed [--model M]`
5. Act on the printed output:
   - `** CỬA SỔ ... MỚI` — new window, usage reset: tell the user in one line.
   - `OK` — continue silently.
   - `WARN` (≥70%) — one-line heads-up; prioritize; show 1–2 of the MẸO TIẾT KIỆM (batch questions, cheaper model/no extended thinking, avoid >5-min pauses, skim files, Projects for heavy files).
   - `HANDOFF` (≥85%) — finish the smallest clean unit (never mid-file/function), then hand off (section 6). Say which clock triggered it: USAGE → user can also wait for the window (time shown); CONTEXT → new chat required.
   - `=> NÊN MỞ CHAT MỚI` — the next message already costs ≥10% of budget and a fresh chat would last longer: write HANDOFF.md now even if USAGE is low. A new chat doesn't refresh the window but makes each message far cheaper.
   - `NO_BUDGET` — totals only; ask for a budget or calibrate.

No code execution: estimate by hand (chars/2.8 Vietnamese, /4 English, /3.3 code; output ×5; each tool call re-reads the context; expensive models ×2–5) and hand off at ~85% of the budget the user gave.

## 6. Handoff

1. Copy `assets/handoff_template.md` → `HANDOFF.md`, fill every section concretely (exact stopping point, ordered next steps, decisions + reasons, file list).
2. `python scripts/ledger.py export --out HANDOFF.md` appends the ledger block (plan, model, calibration included).
3. Put `HANDOFF.md` and every in-progress file in `/mnt/user-data/outputs/` and present them with `present_files`. Tell the user in 2–3 lines: how far you got, which clock triggered it, what to do next (new chat + attach files; or wait for the window reset).
4. After a manual reset: `reset` (usage only) or `reset --new-chat` (usage + context). Budget, weights, calibration are kept.

## 7. Calibration

- Known budget: `calibrate --budget N` (for the current plan, per 5-hour window, sonnet-equivalent).
- The moment the user says "I just hit the limit": `calibrate --hit-limit` BEFORE any reset. Observations are normalized by plan multiplier, so they carry over if the plan changes.
- Also available: `--model-weight NAME=VALUE`, `--context-limit N`, `--cache-discount X`.
- Be honest that estimates may be off by tens of percent; thresholds sit below 100% for that reason.

## 8. Don'ts

- Don't claim to know the true remaining limit.
- Don't let tracking cost more than it saves: one `turn` call per turn; `status` only when needed.
- Don't announce routine OK status; speak up at WARN, HANDOFF, window reset, new-chat advice, or when asked.
