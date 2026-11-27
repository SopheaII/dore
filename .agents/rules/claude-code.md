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
| Learning (statements, corrections, updates, reactions) | word-rule learner: 0 Claude tokens, locally in the hook; Haiku learner (always on since 2026-11-27): only at a session end with 30 items waiting or the oldest 3 hours old; ~4.7k Haiku tokens per batch (sentences, their nearby notes and long blocks in one call); real replay ~6k a day (below) |
| Hook latency | ~0.07 s per prompt with the warm helper (was ~0.9 s: 0.68 s of it loading the embedder); parsing adds ~1 ms per sentence (the helper preloads the parser); first prompt after idle ~1.5 s (was ~1.1 s; +0.6 s loading spaCy `en_core_web_md`) |
| Raw memory (every typed sentence that is not a note, `memory.episodes`) | 0 tokens; ~1.9 ms per prompt (parse + insert, no embedding); the warm helper consolidates after 20 s idle in batches of 64 (~0.1-0.3 s each, so a prompt waits at most one batch), and SessionEnd too |
| Auto-update (`integrations/update.py`, 2026-11-26) | 0 tokens and nothing on the prompt path; no notice (the user found notices annoying). Once a day, in the warm helper's idle time (thread) or at SessionEnd: one GET of `registry.npmjs.org/dore-memory/latest` (~1.8 s, nothing about the user sent); if newer than `data/install.json` (written by `npx dore-memory install/update`), runs `npx --yes dore-memory@<version> update` detached at low priority, output in `data/update.log`; the helper restarts on the code change. Source checkouts never update; off with `DORE_NO_AUTO_UPDATE`, `NO_UPDATE_NOTIFIER`, `DO_NOT_TRACK`, `DISABLE_UPDATES`, `DISABLE_AUTOUPDATER`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` |
| Reading Claude's previous answer (`hooks.last_turn`, 2026-11-26) | the session log is read once per prompt, its last `LOG_BYTES` = 2 MB (~5 ms on a 48 MB real log; 0.4 MB read twice was ~2.6 ms). An answer runs from one typed message to the next (`typed_text`): meta events, `/model` and other command output, task notifications no longer start a "turn" (they lost or cut 142 of 689 real answers). Real answers that fit: 705 of 727 in 2 MB (553 in 0.4 MB) |
| Newer note shown next to an older one about the same thing | ~+6 tokens per question on `conversation long` (46 -> 52), for "newer wins" |
| An entry of a list (group, 2026-11-27) | the entry with its title (~18 tokens), `+N more in #id` (~4), and once per prompt `(all entries of a list: <path>/dore-hook recall <#>)` (~21); ~66 tokens per answer with the header (`eval.lists`). The title once when two entries match; a title alone (~12) only on a question and with entries left. `dore-hook recall <id>` prints every entry (0 tokens until Claude runs it; ~0.45 s without the helper) |

- `dore-hook` = `dore.integrations.hookclient`: standard-library-only client that asks the warm helper `dore.integrations.hookd` over `data/hook.sock` (owner-only). If none answers, it starts one and handles the event itself, so hooks never fail because of it. The helper quits after 30 idle minutes, or before answering once dore's code has changed. `DORE_NO_HELPER=1` turns it off. Windows (no Unix sockets in Python): the helper listens on 127.0.0.1 and `data/hook.sock` is an owner-only file with its port and a random token every request must carry (`DORE_HOOK_TCP=1` forces this elsewhere for tests); measured on macOS 2026-11-26: same ~0.03 s warm as the Unix socket. The hook command looks for `.venv/bin/dore-hook` and `.venv/Scripts/dore-hook.exe` (runs in Git Bash on Windows). Not yet run on a real Windows machine.
- The prompt hook (`hooks.on_prompt`) per prompt: judges the notes shown last time (`react`), saves the user's new statements right away (a correction counts in the same session, and other sessions see it at once), never echoes them back (Claude already has the message), then adds notes only on a strong match (>= 0.65, or an exact ID). The SessionEnd hook only stores messages the prompt hook didn't already learn (`message_key`).
- What is learned today: only the user's own messages (prompt hook + SessionEnd backfill). Claude's replies, tool
  calls and commits are not read; learning from them is roadmap step 2 (strong signals only, `unverified`, capped per session).
- Token rules: learning stays local; nothing relevant -> nothing added; new plugin features must not raise tokens without a measured gain.
- `integrations/bridge.py` (opencode, other editors) uses the same `on_prompt`; fix behaviour in `integrations/hooks.py` (message rules in `learn/statements.py`), not twice.
- Measuring real Claude Code token use: claude.ai connectors (Notion, Claude Docs) connect in the background and are only counted once connected, so compare runs with the same connector state (`--strict-mcp-config` also blocks plugin MCP servers). Real Claude Code test runs write auto-memory under `~/.claude/projects/<cwd>/`; delete the folders made for scratch directories.

- Haiku learner (`integrations.learner`, always on since 2026-11-27): one `claude -p --model haiku` call per batch (30 sentences, a day old, or its session over: SessionEnd
  or a newer session started, so the next session knows it; ~4.8 calls a day on the real history, estimate) from the warm helper's idle loop in a thread (the helper keeps answering prompts; it waits for the batch
  before closing), or at SessionEnd. Flags: `--effort low`, thinking off, `disableAllHooks` (any installed dore
  would otherwise learn the batch: it did, 132 junk notes, archived), no tools, no MCP, no saved session, an empty
  folder outside every project. Measured: ~1.3-1.7k tokens in, 20-700 out, 3-5 s per call; 76 calls / ~226k tokens
  for the real 22-day replay with batches of ~8 (now full batches: about half). Failures keep the queue: back-off
  30 min doubling to a day, or the limit's reset time; daily cap 50k tokens. Prompt hook in this mode: the word rules still
  run (provisional notes, so a first session works at once) plus queueing: ~14 ms (queueing alone 4.4 ms).
  After a batch, provisional notes Haiku did not make or match are archived (`learner.settle`).
