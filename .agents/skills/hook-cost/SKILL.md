---
name: hook-cost
description: Token and latency budget for anything Claude Code or another agent sees (plugin/, src/integrations/, text the prompt hook adds). Use before changing it, and as the checklist when reviewing such a diff.
---

# Hook cost

The plugin's value is memory at almost no Claude tokens. Measured costs:
[claude-code](../../rules/claude-code.md).

- **0 tokens when nothing matches.** No new MCP tools, instructions or session banners
  unless a measured gain beats their cost on every request. Learning stays in the hook.
- **Per prompt**: notes only on a strong match; `MAX_TOTAL_CHARS` still enforced.
- **Latency**: no new heavy imports on the hook path (`integrations/hooks.py`, `learn/`,
  `memory/`); `integrations/` never imports `assistant/` at module level. Warm helper ~0.07 s.
  The spaCy parser (`learn/grammar.py`) loads lazily and is preloaded by `hookd`; cold prompt ~1.5 s.
- **CPU**: no Python loops over all notes, no extra embedding calls per prompt.
- **Measure**: `python -m dore.eval.conversation` prints tokens per question (baseline
  ~46 long, ~73 short); time `.venv/bin/dore-hook prompt` with a throw-away `DORE_DATA`.
- Fix behaviour once in `integrations/hooks.py` or `learn/statements.py` (bridge and server reuse them).
  After changing `plugin/` files, raise the plugin version.
