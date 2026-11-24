# dore

A small local AI that **keeps learning from everyday use**: the questions you ask, the tasks it solves, the documents you load and the corrections you make. It runs on a normal CPU laptop.

Inspired by how the brain splits learning between a fast store (hippocampus) and a slow one (cortex):

| Part | Role | Learns |
|---|---|---|
| Stable core | Small pretrained LLM (Llama 3.2 1B, GGUF) | Nothing: the model is never trained (LoRA dropped) |
| Fast memory | SQLite + FAISS vector search (RAG) | Facts, instantly |
| Thinking loop | Draft → check → fix | Only when a real checker exists |
| Checkers | Python sandbox, maths evaluator | Decide what counts as `verified` |
| Memory server | One process shared by Claude Code and other agents (MCP) | Facts from every connected tool |

See [`PLAN.md`](PLAN.md) for the roadmap and design rules.

dore is not a new invention: it combines ideas from Voyager, Letta, SEAL, Google's Nested Learning, the Tiny Recursive Model, SLIDE, RAG, LoRA and the neuroscience of memory. See [`REFERENCES.md`](REFERENCES.md) for what comes from where.

## Quick start

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e ".[dev]"

# download a model (about 0.8 GB)
mkdir -p data/models
curl -L -o data/models/Llama-3.2-1B-Instruct-Q4_K_M.gguf \
  https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf

.venv/bin/dore            # chat
.venv/bin/dore-web        # same chat in a browser: http://127.0.0.1:8000
.venv/bin/pytest          # tests (no model needed)
```

## Check that it remembers

Just talk to it; no special command is needed:

```text
you> My cat is called Mochi and I live in Phnom Penh.
you> /load notes.md
you> /quit
$ .venv/bin/dore                      # new session
you> What is my cat called?           → Your cat is called Mochi.
you> Where do I live?                 → Phnom Penh.
you> What is my dog called?           → I don't have any information about your dog.
you> /mem cat                         → shows the stored memory and its trust level
```

## Browser chat

`.venv/bin/dore-web` serves the same chat at http://127.0.0.1:8000:

- **model** dropdown lists every GGUF in `data/models/`.
- **project** field is the same as `/project` in the CLI (empty = general).
- The same commands work (`/teach`, `/correct`, `/good`, `/bad`, `/mem`, `/stats`, `/projects`, `/load`, `/code`, `/new`).

It listens on localhost only (there is no login). Options: `--host`, `--port`, `--model`
(default model name such as `3b`, or a `.gguf` path), `--threads`. Only one model is kept in
RAM, so switching frees the old one first; the first message with a new model is slower.

To experiment without touching your real memory, use a throw-away data folder:

```bash
export DORE_DATA=$PWD/data/tmp-test && mkdir -p $DORE_DATA
ln -s ../models $DORE_DATA/models && ln -s ../cache $DORE_DATA/cache
.venv/bin/dore
rm -rf $DORE_DATA      # when done
```

## What it learns, and what it doesn't

| You do | It learns |
|---|---|
| Say something ("I work as a nurse.") | Each sentence is saved as a fact told by you (questions are not saved) |
| `/load` a file | The file is split into pieces and is searchable at once |
| `/code` with tests | Code that passes the tests is saved as a verified lesson |
| Get an answer | The answer is kept but **not reused** until you approve it with `/good`, so made-up answers can't reinforce themselves |
| `/correct` | The correction is saved; the old answer is marked wrong and never used again |

Limits:
- It believes what you tell it; fix false statements with `/correct`.
- Questions worded very differently from what you said may not find the fact.
- The embedding model is English-only.
- The default 1B model finds and repeats facts well but reasons weakly. Try the 3B model (about 2× slower): download `Llama-3.2-3B-Instruct-Q4_K_M.gguf` from the same `bartowski` page and run `.venv/bin/dore --model data/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf`.

## Chat commands

| Command | Effect |
|---|---|
| *(plain text)* | Chat. Statements you make ("My cat is called Mochi.") are learned automatically; questions are not. The model's answer is kept but **not reused** until you approve it |
| `/teach <fact>` | Save a `verified` fact |
| `/correct <text>` | Correct the last answer (old answer marked `wrong`) |
| `/good`, `/bad` | `/good` approves the last answer (it becomes verified and reusable); both rate the memories it used |
| `/code <task>` | Solve with the code checker; passing tests → `verified` lesson |
| `/load <file>` | Load a text/markdown file into memory |
| `/mem <query>`, `/stats` | Inspect memory |
| `/protect <id>` | Never auto-archive this memory |
| `/project <name>`, `/projects` | Switch project / list projects. Facts about you ("my…", "I…") stay general and are seen everywhere; other facts belong to the current project. `dore --project shop` starts in a project |

Search is **hybrid**: meaning (FAISS) plus exact keywords (SQLite FTS5), so codes, IPs and IDs such as `SRV-4471` or `10.0.0.5` are found even when the meaning search misses them. Near-identical results are skipped so they don't fill every slot.

## Use dore's memory from Claude Code (plugin)

Install once; after that every Claude Code session starts its own small dore process (0.8 s, ~290 MB) and
stops it at the end. Nothing to keep running. All sessions share the same `data/memory.db`, so a fact saved
in one session is found in the next, and two sessions open at the same time see each other's notes.

```bash
claude plugin marketplace add ~/Documents/dore
claude plugin install dore@dore
```

(If dore lives elsewhere, set `DORE_HOME=/path/to/dore`.)

What the plugin adds to Claude Code, designed to spend as few tokens as possible:

| Part | When | Cost |
|---|---|---|
| Instructions + 3 tool names (`recall`, `remember`, `correct`) | every request | ~200 tokens (measured) |
| **Prompt hook**: adds this project's rules once per session, and other notes only when they strongly match the prompt (never the same note twice) | before each prompt, runs locally (~0.2–1 s) | 0 tokens when nothing matches; ~55 per note added |
| **Session-end hook**: saves the facts *you* stated (decisions, settings, preferences) from the session log; requests, questions and small talk are skipped | when a session ends, locally | 0 Claude tokens |
| `remember` / `recall` tools | only when Claude needs them (its own findings, older context) | one round trip each |

Facts about you ("my…") and the organisation ("our production server…") are general and reach every
project; other facts stay in their project. Measured on a real 6-session test: same or better answers than
Claude Code alone, 23 instead of 30 requests, 3% cheaper (`reports/token-design.md`).

`ask_local` (run the local 1B/3B model) is off by default; start the server with `--local-models` to offer it.
Other agents that need a network connection can use the shared HTTP server: `.venv/bin/dore-server`
(http://127.0.0.1:8765/mcp).

After changing files in `plugin/`, raise its version and run `claude plugin marketplace update dore` and
`claude plugin update dore@dore`. Python changes in `src/dore/` apply to new sessions automatically.

## Run Claude Code on a local model (experimental)

```bash
.venv/bin/dore-claude --list                 # models in Ollama
.venv/bin/dore-claude qwen2.5-coder --ctx 32768
```

Needs Ollama 0.14+. Much slower and weaker than Claude; see `reports/claude-local.md` for measurements.

## Project layout

```
dore/
├── src/dore/          # the package
│   ├── config.py      # paths and settings
│   ├── core.py        # llama.cpp model wrapper
│   ├── embed.py       # text embeddings (fastembed / test embedder)
│   ├── memory.py      # fast memory: SQLite records + FAISS index
│   ├── ingest.py      # document chunking and loading
│   ├── checkers.py    # Python sandbox + maths checker
│   ├── agent.py       # answering, thinking loop, learning from use
│   ├── bench.py       # benchmarks (results → reports/)
│   └── cli.py         # interactive chat
│   └── web.py         # browser chat (model picker + same memory)
├── tests/             # pytest suite (runs without a model)
├── reports/           # git-ignored: benchmark/test reports (machine-specific)
├── exams/             # exam sets (Phase 5)
├── data/              # models, memory DB, adapters (git-ignored)
├── pyproject.toml
├── PLAN.md
└── CLAUDE.md
```

## Where learned data is stored

Everything lives under `data/` (git-ignored; set `DORE_DATA=/some/path` to move it):

| Path | Contents |
|---|---|
| `data/memory.db` | **All learned knowledge**: facts, lessons, corrections, loaded documents, answers. One SQLite file with text, trust level, dates, scores and each item's vector. Back up this file to back up what dore has learned. |
| `data/memory.faiss` | Search index. Rebuilt automatically from `memory.db` if missing, so it needs no backup. |
| `data/models/` | Core model files (GGUF). Downloadable again. |
| `data/cache/` | Embedding model cache. Downloadable again. |

## Data and trust levels

Every memory has a trust level:

| Level | What gets it | Used in answers? |
|---|---|---|
| `verified` | Passed a real test; taught, stated or approved (`/good`) by you | ✅ |
| `unverified` | Loaded documents, search results | ✅ (labelled as unverified) |
| `unverified` answer | The model's own answers | ❌ until approved with `/good` |
| `wrong` | Answers you corrected | ❌ never (kept for reference) |

Nothing is ever hard-deleted; low-value items are archived (Phase 4).

## Tests

```bash
.venv/bin/pytest                             # 19 unit tests, no model needed, ~2 s
.venv/bin/python -m dore.bench llm           # model speed (tokens/s, RAM)
.venv/bin/python -m dore.bench search        # vector search at 10k / 100k / 1M items
.venv/bin/python -m dore.bench embed         # embedding speed
.venv/bin/python -m dore.bench memory 100000 # memory store at scale (add, search, save, restart)
.venv/bin/python -m dore.bench remember      # auto-remember speed with the real embedder
```

Save benchmark results in `reports/` (git-ignored, since they describe one machine).
