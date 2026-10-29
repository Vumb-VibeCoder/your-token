# your-token

A skill that enables AI to track its own token consumption across **two separate clocks**:

1. **USAGE** — budget for the rolling 5-hour window (automatically resets and notifies you when entering a new window).
2. **CONTEXT** — current chat saturation level (only resets when starting a new chat).

Distinguishes between input/output, extended thinking, tool calls, skimming vs. deep reading, reasoning effort, **model variants** (Haiku 5.5, Sonnet 5.5, Opus 5.5, Fable 5.1, Mythos 5.1, etc.), and **subscription plans** (Free, Pro, Max 5x, Max 20x). When limits are approaching, the AI automatically generates `HANDOFF.md` and exports in-progress work files for you.

## First-Time Use
At the start of every new chat (or right after installing), the AI will ask: which plan you are using, and roughly how long ago your 5-hour window began. Budget = Free baseline × plan multiplier (Pro ≥ 5x, Max 5x = 25x, Max 20x = 100x Free). Note: Claude does not offer a "Plus" tier.

## Key Information
- The Free tier baseline of **30,000 tokens/window is an unverified hypothesis**; Anthropic does not disclose exact token limits. If you hit a rate limit, simply say "I just hit the limit" so the AI can execute `calibrate --hit-limit` (before the window resets). Recorded observations are normalized by plan multipliers, ensuring portability if you switch plans.
- Model weights (`usage_weight`) are heuristic estimates referenced against API pricing (as of October 2026, USD per million tokens in/out): Haiku 5.5 0.10/0.50; Sonnet 5.5 2/10; Opus 5.5 4/20; Fable 5.1 10/50; Mythos 5.1 pricing unpublished.
- Cache invalidation: Pauses longer than 5 minutes between turns expire the prompt cache, incurring full re-read token charges without discounts on the subsequent turn.
- Larger context sizes directly increase per-turn costs. The skill calculates marginal costs, predicts remaining turns, and proactively recommends opening a fresh chat when appropriate.
- Max plans have weekly limits that this skill does not track.

## Installation
Compress the `your-token/` directory into a `.zip` or `.skill` bundle and upload it to the Skills repository. Requires Code Execution permissions to run `scripts/`; otherwise, the AI falls back to manual heuristic estimation defined in `SKILL.md`.

## Quick Commands
```bash
python scripts/ledger.py init --plan claude_pro --model "Claude Opus 5.5"
python scripts/ledger.py window --started-ago-min 40
python scripts/ledger.py turn --effort 3 --tool-calls 2 --user-chars 800 --out-chars 2400 --lang vi
python scripts/ledger.py predict --effort 2 --model fable-5.1 --out-chars 6000
python scripts/ledger.py plan --set claude_max5 --model opus-5.5
python scripts/ledger.py status
python scripts/ledger.py calibrate --hit-limit
python scripts/ledger.py export --out HANDOFF.md
python scripts/ledger.py restore --file HANDOFF.md
python scripts/ledger.py reset [--new-chat]