# dore agent instructions

`AGENTS.md` (also `CLAUDE.md`, a link to it) is the always-loaded guide and router: keep it short,
because every request and every subagent pays for it. Details live in `rules/`, read only when the
routing table points there. Procedures and review checklists live in `skills/` (`.claude/skills`
links here so Claude Code finds them).

## Rules

Roadmap: `AGENTS.md`. Known weaknesses: the rule file they belong to.

- `memory-learning.md`: how learning, replacing, demoting and retrieval work, with measured limits
- `claude-code.md`: plugin and hook design, token and latency costs
- `testing.md`: checks from cheapest to dearest, baselines, conventions

## Skills
- `learning-change`: procedure before changing learning or retrieval rules
- `review-learning`: read-only checklist for such a diff
- `hook-cost`: token and latency budget for anything a coding agent sees

Keep skills short, anchored on file and function names (not line numbers), and only for things
an agent would not do anyway. Update the rule file when a measured behaviour changes.
