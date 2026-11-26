# Claude Code plugin and hooks

Plugin and hook design, with measured token and latency costs. Budget for changes: the `hook-cost` skill.

## Design

**Memory for Claude Code** (`plugin/`, hooks only; the plugin's MCP server was removed by the user on 2026-11-25 to save ~200 tokens per request): all processes share `data/memory.db`, and each catches up with the others' writes before searching (`PRAGMA data_version`). `dore-server` without `--stdio` is a shared HTTP server for other agents. Agent-written facts are `unverified`; `user_said` facts are `verified`; the project defaults to the client's folder, facts about the user are general. The hooks (`dore-hook prompt|end`) do the learning at 0 Claude tokens: see "Performance and token use" below. The plugin never writes to a project's CLAUDE.md.

## Performance and token use (Claude Code and other coding agents)

Measured 2026-11-24/25; keep these when changing the plugin.

| What | Cost |
|---|---|
| dore tools + instructions in Claude's prompt | 0 (plugin has no MCP server since 2026-11-25; was ~+200) |
| Prompt hook, nothing relevant | 0 tokens (prints nothing) |
| Prompt hook, notes added | ~55 tokens per note; hard cap `MAX_TOTAL_CHARS = 600` (~150 tokens) per prompt |
| Rules/decisions of the project | once per session, at the first prompt |
| Learning (statements, corrections, updates, reactions) | 0 Claude tokens: runs locally in the hook |
| Hook latency | ~0.07 s per prompt with the warm helper (was ~0.9 s: 0.68 s of it loading the embedder); parsing adds ~1 ms per sentence (the helper preloads the parser); first prompt after idle ~1.5 s (was ~1.1 s; +0.6 s loading spaCy `en_core_web_md`) |
| Raw memory (every typed sentence that is not a note, `memory.episodes`) | 0 tokens; ~1.9 ms per prompt (parse + insert, no embedding); the warm helper consolidates after 20 s idle in batches of 64 (~0.1-0.3 s each, so a prompt waits at most one batch), and SessionEnd too |
| Newer note shown next to an older one about the same thing | ~+6 tokens per question on `conversation long` (46 -> 52), for "newer wins" |

- `dore-hook` = `dore.integrations.hookclient`: standard-library-only client that asks the warm helper `dore.integrations.hookd` over `data/hook.sock` (owner-only). If none answers, it starts one and handles the event itself, so hooks never fail because of it. The helper quits after 30 idle minutes, or before answering once dore's code has changed. `DORE_NO_HELPER=1` turns it off.
- The prompt hook (`hooks.on_prompt`) per prompt: judges the notes shown last time (`react`), saves the user's new statements right away (a correction counts in the same session, and other sessions see it at once), never echoes them back (Claude already has the message), then adds notes only on a strong match (>= 0.65, or an exact ID). The SessionEnd hook only stores messages the prompt hook didn't already learn (`message_key`).
- What is learned today: only the user's own messages (prompt hook + SessionEnd backfill). Claude's replies, tool
  calls and commits are not read; learning from them is roadmap step 2 (strong signals only, `unverified`, capped per session).
- Token rules: learning stays local; nothing relevant -> nothing added; new plugin features must not raise tokens without a measured gain.
- `integrations/bridge.py` (opencode, other editors) uses the same `on_prompt`; fix behaviour in `integrations/hooks.py` (message rules in `learn/statements.py`), not twice.
- Measuring real Claude Code token use: claude.ai connectors (Notion, Claude Docs) connect in the background and are only counted once connected, so compare runs with the same connector state (`--strict-mcp-config` also blocks plugin MCP servers). Real Claude Code test runs write auto-memory under `~/.claude/projects/<cwd>/`; delete the folders made for scratch directories.
