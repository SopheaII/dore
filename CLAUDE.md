# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project: dore

A small local AI that **keeps learning from everyday use** (tasks, questions, searches, corrections) while it keeps working, like the brain's hippocampus + cortex + sleep. No bulk training: knowledge arrives a little at a time from real use.

The design combines existing work (Voyager, Letta, SEAL, Nested Learning/Titans, TRM, SLIDE, RAG, LoRA, complementary learning systems); `REFERENCES.md` maps each part to its source. Add new sources there when a design idea is borrowed, and mark unverified ones ⚠️.

## Architecture (6 parts)

1. **Stable core**: small pretrained LLM (Llama 3.2 1B Instruct by default, 3B optional; 4-bit GGUF; see PLAN.md "Review v2"). No model training: LoRA was dropped on 2026-11-24 (CPU training too slow on the target laptop for a small, uncertain gain; Claude, the main model the user works with, can't be trained anyway). The core never changes; all learning happens in fast memory.
2. **Fast memory (RAG)**: every fact, lesson, correction and search result is stored as a record (text, vector, source, trust level, date, times used, score) and found with vector search. This is how the system learns instantly.
3. **Thinking loop**: draft, check, fix. **Only used when a real checker exists** (run the code, check the maths). Otherwise answer once.
4. **Self-checking**: checkers for code and maths. Everything else is marked unverified.
5. **Consolidation = memory maintenance** (PLAN.md Phase 4): in idle time, merge same-meaning notes into summaries that link to the originals, decay scores, archive unused notes. No model training.
6. **Memory for Claude Code** (`plugin/`, MCP + hooks): by default Claude Code starts `dore-server --stdio` per session (no server to keep running); all processes share `data/memory.db`, and each catches up with the others' writes before searching (`PRAGMA data_version`). `dore-server` without `--stdio` is a shared HTTP server for other agents. Agent-written facts are `unverified`; `user_said` facts are `verified`; the project defaults to the client's folder, facts about the user are general. The hooks (`dore-hook prompt|end`) do the learning at 0 Claude tokens: see "Performance and token use" below. The plugin never writes to a project's CLAUDE.md.

## Hard rules (from the design review; do not break)

- **Never train facts into the core.** Facts live in fast memory only. Fine-tuning on new facts increases hallucination (Gekhman et al. 2024).
- **Never train on unverified model-generated text.** Use only test-passed results and real human data, always mixed with replay (default 30% new / 70% old). This prevents model collapse (Shumailov et al. 2024).
- **Never hard-delete memories.** Low-score items move to the archive. Items the user marks as protected are never archived automatically.
- **No model training** (LoRA dropped by the user). If it is ever reconsidered, the old rules apply: only verified data with replay, a passed exam before any adapter swap, rollback kept, three exam sets.
- **Trust levels**: `verified` (passed a test, or taught, stated or confirmed by the user), `unverified` (search results, unchecked answers), `wrong` (kept for reference, never retrieved as truth). Only `verified` items can enter training.
- Newer information wins over older when they conflict (store dates on everything).

## Target hardware

- Baseline: an ordinary **CPU-only laptop** (4+ cores with AVX2, 8 GB+ RAM, no GPU, Linux). Everything must work there; a GPU is an optional speed-up, never a requirement.
- Don't rely on Apple-only (MLX) or NVIDIA-only (CUDA, bitsandbytes QLoRA) tools in the core path.
- Rough expectations on such a laptop (measure with `python -m dore.bench`): 1B Q4 inference ~20 tokens/s, 3B ~9 tokens/s.
- Background work (index rebuilds, Phase 4 maintenance) must run at low priority and pause while the user is chatting. Default to 4 threads; thin laptops throttle under long load.

## Stack

- Python 3 for orchestration. Run heavy work in optimised native code (llama.cpp, FAISS); never loop over large data in pure Python.
- Inference: `llama.cpp` (`llama-server` or `llama-cpp-python`) (GGUF models). Local models for Claude Code go through Ollama.
- Embeddings: small model (e.g. `bge-small-en-v1.5` or `nomic-embed-text`).
- Memory: SQLite for records and metadata, FAISS (HNSW, optionally int8/PQ compression) for the vector index.
- Server: `mcp` 2.x (`MCPServer`, streamable HTTP on 127.0.0.1). Local models for Claude Code: Ollama (`dore-claude`).
- Rust is reserved for later hot paths, only if profiling shows Python is the bottleneck.

## Layout and commands

- Standard `src/` layout: the package is `src/dore/`, tests are in `tests/`. Git-ignored: runtime data in `data/`, machine-specific benchmark and test reports in `reports/`.
- Setup: `uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -e ".[dev]"`
- Tests: `.venv/bin/pytest` (no model needed; uses `HashEmbedder` and a fake core).
- Goal test with the real model (throw-away store, never touches `data/`): `.venv/bin/python -m dore.selftest [seeds] [scenario]`.
- Chat: `.venv/bin/dore`; browser chat with a model picker: `.venv/bin/dore-web` (http://127.0.0.1:8000). Benchmarks: `.venv/bin/python -m dore.bench llm|search|embed|memory|remember`.

## Current status (2026-11-25)

- Phases 0–3 of `PLAN.md` are done: chat, fast memory, learning from plain chat, `/teach` `/correct` `/good` `/bad` `/protect` `/load` `/code` `/mem` `/stats` `/project` `/projects`, code checker with fix loop.
- Done since: speed/robustness pass (batched writes, index written at most every 120 s and rebuilt from SQLite if stale, thread-safe store, prompts fit `n_ctx`); **projects** (a `project` column; search sees the current project + general ""; chat statements about the user go to general); **hybrid search** (FAISS + SQLite FTS5 keywords, identifier matches, near-duplicate results skipped); **memory for Claude Code**: plugin in `plugin/` (stdio per session, cross-process sync, session-start note via `dore-server --brief`) and `dore-server` (MCP: `recall`, `remember`, `correct`, `ask_local`); **`dore-claude`** (Claude Code on an Ollama model).
- Earlier (2026-11-24): scale: 97/100 hidden facts in the top 3 among 9,750 notes (`reports/scale.md`). Claude Code with the dore plugin: ~300 tokens per request, saves decisions unprompted, a new session answers from it (`reports/claude-mcp.md`).
- LoRA / skill training (Phase 5) was **dropped** by the user.
- **PLAN.md Phase 3.5 (reliable, self-updating memory), steps 1–3 done 2026-11-25**: write/read bug fixes (order-aware duplicates, merges keep the first date, `/correct` demotes only same-frame notes, agents can't overrule user facts, non-facts and pastes not stored, wrong rows filtered in SQL, no write lock while embedding); automatic updates from plain chat (`replaced_by`/`valid_to`, "No, it's X" works like `/correct`, notes shown with dates); implicit feedback (re-ask -1, moving on +1, `/good` `/bad` ±3, feedback changes ranking). The same learning runs in the Claude Code hooks, per prompt.
- Tests: 90 unit tests pass; `dore.selftest 5`: 36/37 checks (only miss: the 1B model invents a dog name, 0/5). Results in `reports/selftest.md`.
- **Next: Phase 3.5 step 4** (`bench stream`: simulated days; repeated mistakes, stale facts, accuracy over time), then fact slots + profile card + "I don't know" (step 5).
- First commit `init` exists; the work since (projects, hybrid search, server, plugin, dore-claude) is not committed yet. `src/dore.egg-info/` was committed by mistake (build output; now in .gitignore): remove it from git with `git rm -r --cached src/dore.egg-info`.

## How memory learning works (verified with the real 1B model; don't regress)

Unit tests use a fake core and can't catch these; after any change to prompts or retrieval, rerun the real-model check below.

- **Statements in plain chat are learned automatically**: `Agent.remember_statements` splits the user's message into sentences, skips questions (ending in `?` or starting with a `QUESTION_START` word) and sentences under 3 words, and stores each one as `kind="statement"`, `source="user"`, `trust="verified"`. One fact per memory matches questions far better than a whole message.
- **The model's own answers (`kind="answer"`) are stored but kept out of the vector index until the user approves them with `/good`** (which makes them `verified`; `memory.searchable()` is the single rule). Otherwise made-up answers come back as "memory" and reinforce themselves (observed: an invented "Elm Street" address), and they used to crowd real facts out of the top-20 search candidates. They are also never merged with other memories, so `/correct` can't mark a user's fact wrong.
- **Statement filter** (`split_statements`): "Please remember / FYI / can you note that X" stores X (even in question form); small talk ("Thanks a lot!", "Hello, how are you") and requests ("Summarize the following text") are not stored. Requests need verb + object, so "Help desk number is 555" is still a statement.
- **`/correct` (or "No, …" / "Actually, …" after an answer) marks wrong the used notes that conflict with the correction**: similarity >= 0.7 AND `memory.same_frame` (same words around one changed detail). Without this the model answered "a Honda or a Toyota" 3/3; with similarity alone, all four car notes ("red", "bought 2020", "broken mirror", "Toyota") were marked wrong. Known limit: "My car is red" still matches "My car is a Honda"; embedding the changed words can't tell detail kinds apart (same-kind 0.52–0.94 vs different 0.50–0.66). Protected notes are never demoted. Kept, never deleted (`Agent.last_demoted_ids`).
- **A new statement replaces the older one it updates** (`add_many(supersede=True)`, `memory.replaces`): same frame, one detail changed, and a single-value verb (is/live/work/use/prefer/called…), not have/like/friend… ("I have a dog Buddy" + "I have a dog Max" keeps both). The old note gets `replaced_by`/`valid_to`, stays in SQLite, leaves search. Only within one project; an unverified note never replaces a verified one. Shortlist bar 0.6 (real updates 0.76–0.90).
- **Reactions are feedback** (`Agent._react`, `hooks.react`), only after a question: asked again (similarity >= 0.80 and not one-detail-changed: dog/cat 0.82 is a new question) = -1 to the notes used; moving on = +1; `/good` `/bad` = ±3. Ranking adds `0.06*tanh(feedback/4)`: reorders close notes, can't lift unrelated ones.
- **Duplicates merge only when words and numbers match exactly, in order** (plus similarity >= 0.95): bge-small scores "server IP 10.0.0.5" vs "10.0.0.6" at 0.985, and a word set merged "Alice reports to Bob" with "Bob reports to Alice". A merge keeps `created` (first date) and sets `last_seen`.
- **Not facts**: `[Request interrupted by user]`, `/commands`, hypotheticals ("If I were…", "Pretend…") (`NOT_A_FACT`).
- **Long messages** (more than 20 statements or 3000 characters) are stored as `unverified` document chunks (`source="chat-paste"`), not as verified facts.
- **Questions about the user get `NO_GUESS`** ("If no note above answers this, say you don't know.") after the question. Measured with 7 questions × 8 seeds: 54/56 strict vs 42/56 without (the model invented "Your dog is called Kavi"). Longer wordings were worse (one turned "Calmette Hospital" into "Pasteur Institute"). One run of the real-model check is not enough to compare prompts: sample several seeds with `llm.set_seed`.
- **Memory notes go in the user turn, right before the question**, not in the system prompt: the 1B model ignored system-prompt notes.
- **Notes are labelled with their origin and date** (`[verified, told by the user, 2026-11-25]`, `[unverified, from a document, …]`, `tested`); dates did not change selftest results. Without "told by the user", the 1B model read "My favourite language is…" as being about itself.
- **The 1B model ignores notes marked `[unverified]`**, which is why user statements are stored as `verified`.
- **Relevance cut-off `min_similarity = 0.5`** (bge-small, cosine). Measured: a fact asked about directly scores ~0.68–0.83; differently-phrased personal questions only ~0.51–0.55 ("Where do I live?" vs "I live in Phnom Penh"); unrelated items are mostly below 0.5 but can reach ~0.57. The prompt tells the model to use only notes that answer the question.

### Real-model check (run after prompt or retrieval changes)

Use a throw-away data folder so the real memory is untouched, then delete it:

```bash
export DORE_DATA=$PWD/data/tmp-check && mkdir -p $DORE_DATA && ln -s ../models $DORE_DATA/models && ln -s ../cache $DORE_DATA/cache
printf 'My cat is called Mochi and I live in Phnom Penh.\nI work as a nurse at Calmette Hospital.\n/quit\n' | .venv/bin/dore
printf 'What is my cat called?\nWhere do I live?\nWhat is my job?\nWhat is my dog called?\nWhat is the capital of France?\n/quit\n' | .venv/bin/dore
rm -rf $DORE_DATA
```

Expected: Mochi / Phnom Penh / nurse at Calmette Hospital / "no information about your dog" / Paris. As of 2026-11-25 the dog answer is invented in most runs (1B guess, prompt unchanged); everything else passes.

## Performance and token use (Claude Code and other coding agents)

Measured on the target laptop (`reports/token-design.md`, `reports/selftest.md`); keep these when changing the plugin.

| What | Cost |
|---|---|
| dore tools + instructions in Claude's prompt | ~+200 tokens per request (3 tools, short descriptions) |
| Prompt hook, nothing relevant | 0 tokens (prints nothing) |
| Prompt hook, notes added | ~55 tokens per note; hard cap `MAX_TOTAL_CHARS = 600` (~150 tokens) per prompt |
| Rules/decisions of the project | once per session, at the first prompt |
| Learning (statements, corrections, updates, reactions) | 0 Claude tokens: runs locally in the hook |
| Hook latency | ~0.07 s per prompt with the warm helper (was ~0.9 s: 0.68 s of it loading the embedder); first prompt after idle ~1.1 s |

- `dore-hook` = `dore.hookclient`: standard-library-only client that asks the warm helper `dore.hookd` over `data/hook.sock` (owner-only). If none answers, it starts one and handles the event itself, so hooks never fail because of it. The helper quits after 30 idle minutes, or before answering once dore's code has changed. `DORE_NO_HELPER=1` turns it off.
- The prompt hook (`hooks.on_prompt`) per prompt: judges the notes shown last time (`react`), saves the user's new statements right away (a correction counts in the same session, and other sessions see it at once), never echoes them back (Claude already has the message), then adds notes only on a strong match (>= 0.65, or an exact ID). The SessionEnd hook only stores messages the prompt hook didn't already learn (`message_key`).
- Token rules: learning stays local; nothing relevant -> nothing added; new plugin features must not raise tokens without a measured gain (rerun the `reports/token-design.md` comparison).
- `bridge.py` (opencode, other editors) uses the same `on_prompt`; fix behaviour in `hooks.py`, not twice.

## Known weaknesses

- Search misses questions phrased very differently from the stored fact (e.g. "job" vs "work as a nurse" scores 0.55). Keyword search (FTS5) helps only when words overlap; a stronger embedding model (`bge-base`) is the remaining option.
- Questions with no answer still get ~3 loosely related notes (0/100 empty in `bench scale`).
- Claude Code on local Ollama models failed a one-line task (llama3.2: 9 min, qwen2.5-coder: 15 min) with Ollama's default 4096 context; see `reports/claude-local.md`.
- `bge-small-en-v1.5` is English-only; other languages need a multilingual embedding model and a full re-embed.
- Every add checks for duplicates with an exact (flat) search, which is O(n) per item: fine for chat, but bulk-loading 100k items into a 100k store takes minutes (measured 440 items/s). Switch to HNSW above ~200k items.
- 1B-model limits seen in `dore.selftest` (5 seeds): invents a dog name when only the cat is known (0/5 "don't know" on 2026-11-25, 3/5 the day before, same prompt); wifi password 5/5 now (was 3/5).
- Re-ask detection misses big rewordings ("What is my job?" / "What do I do for work?" 0.79). Reactions in Claude Code judge only the notes the hook showed, not Claude's answer.
- The 1B model ignores `unverified` notes, so answers about long pasted text are weak (stored correctly, poorly used).
- The 1B model retrieves and repeats facts well but reasons weakly across several facts; 3B (`--model data/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf`) is ~2× slower.
- Statements are trusted as the user said them; a false one is fixed by saying "No, …" or `/correct`.
- The code sandbox can't block network access (user namespaces are often disabled); it uses timeouts, rlimits, a temporary directory and `python -I`.

## Working conventions

- Measure before claiming performance numbers; write results to `reports/` (never committed, since they describe one machine).
- Keep the core model, adapters, memory DB and model caches under `data/` (git-ignored); never commit model weights or personal memory.
- Every learning change must be measurable: add a `dore.selftest` scenario or a `dore.bench` measurement.
- Keep it simple: one feature per phase in `PLAN.md`, and finish and test it before starting the next.
- `fastembed` caches models in `/tmp` by default (wiped on reboot); always pass `cache_dir=cfg.cache_dir / "fastembed"`.
- Measuring Claude Code token overhead: claude.ai connectors (Notion, Claude Docs) connect in the background and are only counted if they finished connecting, so compare runs with the same connector state (`--strict-mcp-config` blocks plugin MCP servers too).
- Real Claude Code tests write auto-memory under `~/.claude/projects/<cwd>/`; delete the folders made for scratch test directories afterwards.
- When waiting on a background process in shell, don't `pgrep -f` a string that also appears in the waiting command itself: it matches itself and waits forever.
- Explain results to the user in plain, simple English with tables; mark estimates as estimates and say which claims were actually measured.
