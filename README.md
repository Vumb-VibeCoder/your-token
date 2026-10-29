# your-token

A skill that lets Claude track its own token consumption across **two separate clocks**, for both **claude.ai subscriptions** and the **Claude API**:

1. **USAGE**
   - *claude.ai (Free / Pro / Max 5x / Max 20x):* weighted tokens in the rolling 5-hour window vs a budget. Resets automatically and tells you when a new window starts.
   - *API (pay-as-you-go):* dollar spend vs an optional cap (per session, day or month), exact when you feed it each response's `usage` object, plus optional rate-limit tracking (requests / input tokens / output tokens per minute).
2. **CONTEXT:** how full the current conversation is (resets only in a new chat/session).

It separates input/output, extended thinking, tool calls, skimming vs deep reading, reasoning effort, **model variants** (Haiku 5.5, Sonnet 5.5, Opus 5.5, Fable 5.1, Mythos 5.1, ...) and **plans**. When a limit is close, Claude writes a `HANDOFF.md` and exports in-progress files so you can continue in a fresh chat.

## Setup: zero questions
Nothing to configure. The ledger creates itself on first use (Free plan, Sonnet 5.5). Tell Claude your plan whenever you like, or use `init --api` for API work. Claude only mentions its assumption once.

## Key facts
- The Free baseline of **30,000 weighted tokens per window is an unverified hypothesis**; Anthropic does not publish exact limits. If you hit a limit, say "I just hit the limit" and Claude runs `calibrate --hit-limit`. Observations are normalized by plan multiplier, so they carry over if you change plan.
- `usage_weight` per model is a heuristic, referenced to API list prices (Oct 2026, USD per million tokens in/out): Haiku 5.5 0.10/0.50; Sonnet 5.5 2/10; Opus 5.5 4/20; Fable 5.1 10/50; Mythos 5.1 unpublished (assumed = Fable).
- API dollars use those list prices plus Anthropic's cache/batch multipliers (`plans.json` > `api_pricing`: cache read 0.1x, 5-min write 1.25x, 1-hour write 2x, Batch 0.5x). Verify against the current pricing page if exact dollars matter.
- Cache: a pause longer than 5 minutes expires the prompt cache, so the next turn's re-reads are charged in full.
- Bigger context = costlier messages. The skill computes the marginal cost of the next message, forecasts the turns left, and recommends a fresh chat when that is cheaper.
- Max plans have weekly limits that this skill does not track.

## Transparency
Standard-library Python only. No network access, no subprocesses. The scripts read `plans.json` and files you pass explicitly, and write only `ledger.json` and an optional `--out` file such as `HANDOFF.md`. Everything is plain text you can read in a minute.

## Installation
Zip the `your-token/` folder into a `.zip` or `.skill` bundle and upload it to your Skills settings. Code Execution is needed to run `scripts/`; without it Claude falls back to the manual estimates in `SKILL.md`.

## Quick commands
```bash
# claude.ai
python scripts/ledger.py init --plan claude_pro --model "Claude Opus 5.5"     # optional, auto-created otherwise
python scripts/ledger.py window --started-ago-min 40
python scripts/ledger.py turn --effort 3 --tool-calls 2 --user-chars 800 --out-chars 2400 --lang en
python scripts/ledger.py predict --effort 2 --model fable-5.1 --out-chars 6000
python scripts/ledger.py plan --set claude_max5 --model opus-5.5
python scripts/ledger.py calibrate --hit-limit

# API
python scripts/ledger.py init --api --budget-usd 5 --period day --model claude-sonnet-5-5
python scripts/ledger.py api-usage --input 1200 --output 800 --cache-read 40000 --cache-write 3000
python scripts/ledger.py calibrate --rpm 50 --itpm 30000 --otpm 8000          # from your Console limits
python scripts/ledger.py calibrate --hit-rate-limit                           # right after a 429

# both
python scripts/ledger.py status
python scripts/ledger.py export --out HANDOFF.md
python scripts/ledger.py restore --file HANDOFF.md
python scripts/ledger.py reset [--new-chat]
```
