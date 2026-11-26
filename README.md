<h1 align="center">dore</h1>

<p align="center">
  <strong>Local long-term memory for Claude Code and other coding agents, that keeps learning from everyday use.</strong><br/>
  Say a fact, a decision or a rule once, in your own words. Every later session remembers it.<br/>
  0 Claude tokens to learn · nothing leaves your machine · no model training.
</p>

<p align="center">
  <a href="#see-it-work">See it work</a> ·
  <a href="#install-for-claude-code">Install</a> ·
  <a href="#test-results">Test results</a> ·
  <a href="#limits">Limits</a> ·
  <a href="AGENTS.md#roadmap-one-step-at-a-time">Roadmap</a> ·
  <a href="REFERENCES.md">Where the ideas come from</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Claude_Code-plugin_0.5.0-d97757?style=flat-square" alt="Claude Code plugin 0.5.0" />
  <img src="https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/runs_on-CPU_laptop-555?style=flat-square" alt="Runs on a CPU laptop" />
  <img src="https://img.shields.io/badge/data-stays_local-2ea44f?style=flat-square" alt="Data stays local" />
</p>

## Test highlights

Measured on 2026-11-26 on an Apple M1 Mac (8 cores, 8 GB RAM, CPU only). Every number comes from a command you can run
yourself ([Test results](#test-results)).

- 🧠 **Remembers across sessions:** 80 of 80 questions right after a 20-session coding chat (486 messages,
  53 facts that changed 1–3 times). An outdated value was shown 0 of 53 times.
- 🔁 **Follows your changes:** 35 of 35 update cases right. "I switched my editor to Helix" replaces
  "My editor is Neovim"; the old note is kept in history, never deleted.
- 🪶 **Almost free:** learning costs 0 Claude tokens (it runs in a local hook). On 1,036 real prompts from
  the author's own Claude Code sessions, dore added 7.3 tokens per prompt on average, and nothing at all when
  nothing matched.
- ⚡ **Fast:** 12 ms per prompt (median) with 24 weeks of memory from 12 projects (8,640 prompts).
- 🧹 **Keeps chatter out:** 0 of 39 held-out requests, questions and small talk were stored, while 38 of 41
  held-out facts were stored in the right place. "Held-out" means these sentences were never used to tune the rules.
- 🗂️ **Right project:** facts about you reach every project, a project's facts stay in it: 0 leaks over
  4 simulated weeks × 5 runs.

## What is dore?

A new Claude Code session only knows what is written in files like `CLAUDE.md`. What you said in chat (your
stack, your server, "don't touch the payment module", "we moved to Fly.io") is gone when the session ends, so
you say it again, and again.

dore fixes that with two Claude Code hooks and a small memory on your laptop:

1. **It listens.** Every message you type is read locally. Lasting statements (facts, decisions, settings,
   preferences, "always / never / don't" rules) become notes. Requests, questions, pasted logs and small talk don't.
2. **It keeps notes up to date.** A newer statement about the same thing replaces the older one ("now",
   "switched to", "moved off"…). Nothing is ever deleted: replaced notes stay in history.
3. **It reminds Claude only when it helps.** Before each prompt, dore searches its notes. On a strong match it
   adds the note, with its date, to the prompt. No match: nothing is added, 0 tokens.

No cloud service, no MCP tools taking space in Claude's prompt, no model training. The language model never
changes; only the memory grows.

## See it work

This is the real output of `python -m dore.eval.demo`: four sessions in two projects, sent through the same
prompt hook Claude Code calls (real embedder and grammar parser, no LLM, a throw-away store, made-up facts).

```text
── Session 1 · Monday · project "shop" ──────────────────────────────
you>  My name is Dara. My editor is Neovim.
      saved #1 (every project)
      saved #2 (every project)
      dore adds nothing (0 tokens)
you>  We deploy the shop API to Render. The database is Postgres 16.
      saved #3 (project shop only)
      saved #4 (project shop only)
      dore adds nothing (0 tokens)
you>  Please don't reformat existing code.
      saved #5 (project shop only)
      dore adds nothing (0 tokens)
you>  fix the login bug please
      dore adds nothing (0 tokens)
you>  can you check why the test fails?
      dore adds nothing (0 tokens)
you>  hmm that's not right, the test still fails
      saved #6 (project shop only)                    ← a known miss: see Limits
      dore adds nothing (0 tokens)

── Session 2 · Thursday · project "shop" ──────────────────────────────
you>  I switched my editor to Helix.
      saved #7 (every project), replaces #2 'My editor is Neovim.'
      dore adds:                                      ← this project's rules, once per session
        - #5 (2026-11-26) Don't reformat existing code.
you>  We moved off Render, the shop API deploys to Fly.io now.
      saved #8 (project shop only), replaces #3 'We deploy the shop API to Render.'
      dore adds nothing (0 tokens)

── Session 3 · next week · project "blog" ──────────────────────────────
you>  Which editor do I use?
      dore adds:
        - #7 (2026-11-26) I switched my editor to Helix.
you>  Where does the shop API deploy?
      dore adds:
        - #8 (2026-11-26) (from project shop) We moved off Render, the shop API deploys to Fly.io now.
you>  What is my name?
      dore adds:
        - #1 (2026-11-26) My name is Dara.
you>  add a dark mode toggle to the header
      dore adds nothing (0 tokens)

── Session 4 · next week · project "shop" ──────────────────────────────
you>  Where do we deploy the API?
      dore adds:
        - #5 (2026-11-26) Don't reformat existing code.
        - #8 (2026-11-26) We moved off Render, the shop API deploys to Fly.io now.
you>  Which database version do we run?
      dore adds:
        - #4 (2026-11-26) The database is Postgres 16.

Notes: 8 saved, 2 replaced (kept in SQLite, out of search). Added ~14 tokens per prompt (characters / 4).
```

In Claude Code, the added lines start with `dore memory (use if relevant; trust user code/instructions over it):`.

| What the demo shows | Result |
|---|---|
| Facts kept (name, editor, deploy target, database, a "don't" rule, 2 updates) | 7 of 7 |
| Updates that replaced the old note (Neovim → Helix, Render → Fly.io) | 2 of 2, no old value shown afterwards |
| Questions answered from memory with the current value | 5 of 5 |
| Requests and questions stored as notes | 0 of 8 |
| Junk stored | 1 ("hmm that's not right, the test still fails") |
| Prompts where dore added nothing | 8 of 14 |

The facts about Dara (name, editor) reached the blog project; the shop's database and rule did not. A question
in another project that strongly matches a project fact is shown, marked "(from project shop)".

## What it helps with

- **Stop repeating yourself:** your stack, ports, servers and deploy targets are told once and found in every new session.
- **Standing rules:** "don't reformat existing code", "always use pnpm" are shown at the start of each session in that project.
- **Things that change:** the newest value wins and Claude sees the date, so it doesn't use last month's port.
- **You, everywhere:** your name, editor and style preferences are general; project facts stay in their project.
- **Many sessions at once:** all sessions share one memory. A fact said in one is found in the next prompt of another.
- **Your past sessions too:** `backfill` learns facts from old Claude Code logs ([below](#learn-from-past-sessions)).
- **Other agents:** opencode, and any MCP client, use the same memory ([below](#other-coding-agents)).

## How it works

```text
 you type a prompt in Claude Code
            │
            ▼
 ┌──────────── UserPromptSubmit hook · runs locally · ~12–24 ms ─────────────────────┐
 │ 1. react   did the notes shown last time help? (asked again −1, moved on +1)      │
 │ 2. learn   sentences → grammar gate (spaCy) → facts, rules, updates               │
 │            → save as notes; an update replaces the older note it changes          │
 │            → every other sentence kept as raw memory, judged again when the       │
 │              rules improve, so a rule fixed later also learns from the past       │
 │ 3. recall  hybrid search on this project + general notes                          │
 │            (FAISS meaning search + SQLite FTS5 keywords, so IDs like SRV-4471     │
 │            and 10.0.0.5 are found) → strong match: add the note and its date      │
 └───────────────────────────────────────────────────────────────────────────────────┘
            │  nothing matched → nothing added (0 tokens) · hard cap ~150 tokens
            ▼
      Claude answers
            │
 SessionEnd hook: learns anything the prompt hook missed (0 Claude tokens)
```

A small warm helper answers the hooks so the embedder and parser stay loaded; it quits after 30 idle minutes.
Nothing needs to be kept running. If the helper is not there, the hook starts it and still answers.

### Core ideas

| Idea | What it means |
|---|---|
| **Fast memory, fixed model** | Like the brain's split between hippocampus (learns at once) and cortex (changes slowly): the LLM is never trained, facts go into fast memory at once. |
| **Grammar, not word lists** | What becomes a note is decided by sentence shape and grammar, so it works for anyone's wording. Rules are designed on one set of sentences and judged on another. |
| **Trust levels** | `verified` (you said it), `unverified` (an agent wrote it), `wrong` (corrected; kept, never shown as true). An agent's note never overrules yours. |
| **Newer wins** | Every note has a date; a newer statement about the same thing replaces the older one. |
| **Never deleted** | Replaced, wrong and archived notes stay in SQLite. Back up one file to back up everything. |
| **0 tokens by default** | Learning is local; nothing is added to a prompt unless a note strongly matches it. |

## Install for Claude Code

Needs Python 3.11+ ([uv](https://docs.astral.sh/uv/) recommended), Claude Code, macOS or Linux. No GPU.

```bash
# put the repo at ~/Documents/dore (or anywhere, then set DORE_HOME=/path/to/dore)
cd ~/Documents/dore
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e ".[dev]"

claude plugin marketplace add ~/Documents/dore
claude plugin install dore@dore
```

That's all. Use Claude Code as usual. The small embedding model (`bge-small-en-v1.5`) downloads once on first use.

**Try it:** tell Claude a fact in one session ("Our staging server runs on port 8443."), then open a new session,
even in another folder for facts about you, and ask about it.

**See what dore has stored:**

```bash
sqlite3 data/memory.db "SELECT id, project, trust, content FROM memories
                        WHERE archived = 0 AND replaced_by IS NULL ORDER BY id DESC LIMIT 20"
```

(`project` empty = general, seen in every project.)

### What it costs in Claude Code

| What | Cost |
|---|---|
| Learning (facts, rules, updates, corrections) | 0 Claude tokens: runs in the local hook |
| A prompt with nothing relevant | 0 tokens: the hook prints nothing |
| A note added | ~15–55 tokens each (estimate: characters / 4); hard cap ~150 tokens per prompt |
| On real use (1,036 real prompts replayed) | 7.3 tokens added per prompt on average |
| Tools in Claude's prompt | none: the plugin has no MCP server (one costs ~200 tokens on every request) |
| Hook time | ~0.07 s per prompt with the warm helper; ~1.5 s on the first prompt after 30 idle minutes |

### Learn from past sessions

dore can read your old Claude Code logs (`~/.claude/projects/*/*.jsonl`; Claude Code keeps them 30 days by
default) and learn the facts you typed there:

```bash
.venv/bin/python -m dore.integrations.backfill            # dry run: lists the facts it would learn, writes nothing
.venv/bin/python -m dore.integrations.backfill --apply    # keep them
```

Read the list first: on the author's 98 real session logs, about half of the 43 proposed facts were real
(tech stack, devices, "don't use java") and half were junk (reports, a pasted error, requests).

Notes saved under older rules can be judged again with today's rules (archived, never deleted):
`.venv/bin/python -m dore.learn.recheck` (dry run), then `--apply`.

## What it learns, and what it doesn't

| You say | dore |
|---|---|
| "We deploy to Render." · "My editor is Neovim." | Saves a fact (`verified`, dated) |
| "Please don't reformat existing code." · "Always use spaces." | Saves a standing rule, shown once per session in that project |
| "I switched my editor to Helix." · "We moved off Render." | Saves the update; the old note leaves search (kept in history) |
| "No, the max discount is 40%." | Marks the note it corrects `wrong` (kept), saves the new value |
| "fix the login bug please" · "can you check why…?" | Nothing: a request or a question |
| A pasted log, stack trace or code | Nothing: a paste, not a statement |
| A long instruction with constraints | Kept hidden; shown only once you say it again in another session |

Scope: facts about you ("I…", "my…") and the organisation ("our production server…") are general and reach every
project. Everything else stays in the project (the session's folder name).

## Test results

Run on 2026-11-26 on an Apple M1 Mac, CPU only. None of these needs an LLM or Claude tokens.

| Check | Command | What it tests | Result |
|---|---|---|---|
| Unit tests | `.venv/bin/pytest -q` | 128 tests | 127 pass; 1 (warm helper socket) needs Linux |
| Conversation | `.venv/bin/python -m dore.eval.conversation` | 20 sessions, 486 messages, 80 questions; facts change 1–3 times | 80/80 correct, old value shown 0/53, ~49 tokens per question |
| | | short: 2 sessions, 7 questions, corrections in plain words | 5/7 correct, old value shown 0/3, ~73 tokens per question |
| Learning | `.venv/bin/python -m dore.eval.learning` | which sentences become notes, and where | see the next table |
| Stream | `.venv/bin/python -m dore.eval.stream seeds 5` | 4 weeks of use in 3 projects (~500 messages, 29 facts), 5 wordings | see below |
| Scale | `.venv/bin/python -m dore.eval.scale` | 12 projects × 24 weeks, 8,640 prompts, 112 facts | see below |
| Demo | `.venv/bin/python -m dore.eval.demo` | the example above | as shown |

**Learning** (DEV = sentences the rules were designed on; HELDOUT = sentences kept aside to judge them fairly):

| Set | Facts stored in the right place | Junk stored |
|---|---|---|
| DEV | 52 of 56 | 2 of 73 |
| HELDOUT | 38 of 41 | 0 of 39 |
| Updates (replace the old note, or rightly keep both) | 35 of 35 | |
| Rephrased question finds its note | 9 of 10 | |

**Stream** (mean of 5 runs with different wording; 30 questions a week):

| Week | Correct | Old value also shown | Leaks to other projects |
|---|---|---|---|
| 1 | 28.6 / 30 | 0 | 0 |
| 2 | 28.4 / 30 | 0.4 | 0 |
| 3 | 26.2 / 30 | 2.0 | 0 |
| 4 | 26.0 / 30 | 2.4 | 0 |

Facts missed 0 of 29; junk stored 10.8 of ~467 non-fact messages; 3.7 tokens added per work prompt.

**Scale** (memory keeps growing for 24 weeks; every known fact asked every 4 weeks):

| Week | 8 | 12 | 16 | 20 | 24 |
|---|---|---|---|---|---|
| Correct | 81% | 80% | 80% | 80% | 81% |
| Old value shown | 0/3 | 1/5 | 1/7 | 1/8 | 2/12 |

Facts missed 3 of 112; junk notes 195 from ~8,500 noise prompts; 6.4 tokens added per work prompt;
hook 12 ms median, 26 ms p95. Accuracy holds as memory grows.

**Real prompts** (private replay of the author's own Claude Code logs; counts only):

| Check | Result |
|---|---|
| 1,036 real prompts replayed | 7.3 tokens added per prompt, hook 24 ms median |
| A fresh sample of 118 real prompts, labelled by hand | junk 5 of 118 with the grammar gate (27 of 118 with the old word lists) |
| Replay after the 2026-11-26 rules | 70 → 46 notes, every real fact kept |

Speed benchmarks: `.venv/bin/python -m dore.eval.bench search|embed|memory|scale` (save results under
`reports/`, git-ignored: they describe one machine).

## Limits

Measured, not guessed:

- **Synonyms:** "What is my job?" doesn't find "I work as a nurse" (the 1 miss in 10 rephrased questions). An
  update that uses another word for the topic ("db" vs "database") keeps both notes; the newer is shown first.
- **One fact per sentence works best:** "My name is Dara and my editor is Neovim" is one note, so a later
  editor change can't replace only half of it (both are shown, newer first).
- **Some complaints look like facts:** "hmm that's not right, the test still fails" is stored (2 of 73 DEV junk;
  195 junk notes in 8,640 scale prompts).
- **Stale values creep in over time:** after 4 weeks of changes, ~2.4 of 30 answers also show an old value
  (Claude sees the dates, newer first).
- **Only your messages are learned,** not Claude's replies or tool calls: on 701 real turns those were mostly task logs.
- **English only:** other languages (Khmer, for example) are neither learned nor found.
- **It believes what you say.** Correct it in plain words ("No, it's 40%").
- **No UI yet** to browse notes: use the `sqlite3` command above.

## Other coding agents

- **opencode:** the plugin in `plugin/opencode` uses `dore-bridge`, the same learning path as the Claude Code hook.
- **Any MCP client:** `.venv/bin/dore-server` (shared HTTP server at http://127.0.0.1:8765/mcp, no login: keep it
  on localhost) or `dore-server --stdio` in the client's MCP config. Tools: `recall`, `remember`, `correct`.
  Notes an agent writes are `unverified` and never overrule yours. Each tool costs tokens on every request, which
  is why the Claude Code plugin uses hooks only.

After changing files in `plugin/`, raise its version and run `claude plugin marketplace update dore` and
`claude plugin update dore@dore`. Python changes in `src/` apply to new sessions automatically.

## Where your data lives

Everything is under `data/` (git-ignored; set `DORE_DATA=/some/path` to move it):

| Path | Contents |
|---|---|
| `data/memory.db` | **Everything dore learned**: notes, rules, corrections, raw sentences, with trust level, dates, scores and vectors. One SQLite file: back it up to back up dore. |
| `data/memory.faiss`, `data/memory.keys.faiss` | Search indexes, rebuilt from `memory.db` when missing. |
| `data/cache/` | Embedding model cache (downloads again if deleted). |

## Project layout

`src/` is the `dore` package itself. Each layer imports only the ones above it.

```text
src/
├── config.py          paths and settings
├── memory/            1. fast memory, no model
│   ├── store.py       MemoryStore: add, merge, replace, hybrid search, feedback, archive
│   ├── rules.py       duplicates, one detail changed, which note replaces which
│   ├── episodes.py    raw memory: every typed sentence that is not a note
│   └── schema.py, types.py, embed.py, ingest.py
├── learn/             2. what to learn from a message, no model
│   ├── statements.py  shape and word rules, project vs general
│   ├── grammar.py     spaCy grammar gate, topic keys
│   └── recheck.py     judge old notes again with today's rules
├── integrations/      3. coding agents
│   ├── hooks.py       the prompt and SessionEnd hooks
│   ├── hookd.py, hookclient.py   warm helper + standard-library client (`dore-hook`)
│   ├── bridge.py      opencode and other editors (`dore-bridge`)
│   ├── server.py      MCP server (`dore-server`)
│   └── backfill.py    learn from past Claude Code sessions
└── eval/              4. checks and benchmarks (no LLM): conversation, learning, stream, scale, bench, demo
```

Also: `tests/` (pytest), `plugin/` (Claude Code plugin, hooks only; `plugin/opencode`), `reports/` and `data/`
(git-ignored).

## Learn more

- [`AGENTS.md`](AGENTS.md): design rules and the roadmap (what is done, what is next).
- [`.agents/rules/`](.agents/rules): how learning, the hooks and the checks work, with every measurement.
- [`REFERENCES.md`](REFERENCES.md): dore isn't a new invention. It combines ideas from Voyager, Letta, SEAL,
  Nested Learning, RAG, HippoRAG and the neuroscience of memory; this file says what comes from where.
