# PLAN: dore, a local AI that learns from use

## Goal

Build a local AI that runs on an ordinary CPU-only laptop (4+ cores, 8 GB+ RAM, no GPU) and:
- answers questions and does tasks using a small pretrained model,
- learns **instantly** from every use (tasks, searches, corrections) through fast memory,
- slowly improves its **skills** through small LoRA consolidation sessions,
- never gets worse silently (exams + rollback),
- stays fast as memory grows (index + merging + forgetting).

**Success test (final phase):** over 30 days, the final-exam score on held-out Python problems goes up, old-skill scores stay flat, and memory search stays under ~5 ms.

## What we expect (from the design review)

| Question | Expected |
|---|---|
| Remembers what it is taught | Yes, through fast memory |
| Improves at code and maths over time | Likely, then it slows down |
| Improves at everything | No, only where answers can be tested |
| Improves forever | No, a fixed-size model reaches a ceiling |
| Gets slower as memory grows | No (core fixed; indexed search adds only milliseconds) |
| Main long-term risk | Memory quality (duplicates, stale or wrong items) |

## Review v2 (2026-11-24): fixes after checking the design against CPU-only hardware

1. **Default core = Llama 3.2 1B.** The exam and the training both run on the same model. With 3B on CPU, a 30-item exam takes ~25 min and training runs at ~3–8 tokens/s. With 1B the exam is ~8 min and training ~10–25 tokens/s. 3B stays an option if Phase 0 shows it is fast enough.
2. **Training needs Hugging Face weights, not GGUF.** Inference uses GGUF (ungated `bartowski/*-GGUF`); training uses the safetensors model (ungated mirror `unsloth/Llama-3.2-1B-Instruct`). Convert the trained adapter with `convert_lora_to_gguf.py`.
3. **Adapter "hot swap" = load a second model instance with the new adapter, then switch.** llama.cpp can't load a new adapter file into a running model. 1B Q4 uses ~1.4 GB, so two copies at once fit in 8 GB of RAM.
4. **The vector index starts as exact search** (`IndexIDMap2(IndexFlatIP)`): it supports removal and takes milliseconds up to ~100k items. Switch to HNSW above ~200k items (HNSW can't remove items, so filter archived ones and rebuild the index periodically). Vectors are also stored in SQLite, so the index can always be rebuilt.
5. **Sandbox limits:** many desktop kernels block unprivileged user namespaces, so the code checker does not try to cut off network access. It uses a timeout, memory and CPU limits, a temporary directory, isolated Python (`-I`) and an empty environment. It only runs code the model wrote for your own tasks.
6. **Embeddings use `fastembed` (ONNX, no PyTorch)**, model `bge-small-en-v1.5` (384 numbers per vector, English). If you need Khmer or other languages, switch to a multilingual model in the config and rebuild the index.
7. **Verified means passed a real test.** Code that only runs without error stays `unverified`; it becomes `verified` only when user-provided tests pass or the user confirms it.
8. **The rotating exam has 30 items** (it was 50), to keep CPU exam time near 8 minutes.

## Folder layout (target)

Standard `src/` layout (PyPA recommended). Files marked *(later)* don't exist yet.

```
dore/
├── src/dore/
│   ├── config.py        # paths and settings
│   ├── core.py          # llama.cpp wrapper, adapter swap
│   ├── embed.py         # embeddings
│   ├── memory.py        # SQLite records + FAISS index, search, trust, archive
│   ├── ingest.py        # chunk + store documents
│   ├── checkers.py      # python sandbox runner, maths checker
│   ├── agent.py         # answering, thinking loop, learning from use
│   ├── bench.py         # machine benchmarks
│   ├── cli.py           # chat interface
│   ├── maintain.py      # (later) merge, archive, score decay
│   ├── consolidate.py   # (later) LoRA training, exam, swap / rollback
│   └── search.py        # (later) optional web search
├── tests/
├── reports/             # git-ignored: benchmark and test reports (machine-specific)
├── exams/               # rotating / hidden / final exam sets
├── data/                # git-ignored: models, adapters, memory.db, index
├── pyproject.toml
├── README.md
├── PLAN.md
└── CLAUDE.md
```

## Phases

### Phase 0: Setup and baseline
- [x] Python venv, `pyproject.toml`, `.gitignore` (`data/`), `git init`.
- [x] Build or install llama.cpp; download Llama 3.2 1B and 3B Instruct (Q4_K_M GGUF).
- [ ] **You:** read Meta's Llama 3.2 licence (needed before sharing or selling anything built on it).
- [x] Benchmark script (`python -m dore.bench`): tokens/s, RAM, search speed. Results go to `reports/` (git-ignored, machine-specific).
- [x] Choose the core model → **1B** (21.4 vs 9.4 tok/s).

**Done when:** you can chat with the core model from the CLI, and the benchmark numbers are recorded.

### Phase 1: Fast memory (RAG)
- [x] SQLite schema: `id, content, vector_id, source, trust (verified|unverified|wrong), protected, created, last_used, times_used, score, archived`.
- [x] Embedding model and FAISS index (exact search now; HNSW above ~200k items); add, search and rebuild.
- [x] Ingest: chunk text, embed it, store it (a single item or a document).
- [x] Retrieval: top-k (default 5), skip `wrong` and archived items, prefer newer items, add each item's trust level to the prompt.
- [x] Benchmark search at 10k / 100k / 1M synthetic items.

**Done when:** a fact you teach is used in the next answer, and search of 1M items takes under ~5 ms.

### Phase 2: Learning from use
- [x] After each answer, save the useful result as a memory with a trust level.
- [x] Learn statements from plain chat (one memory per sentence, questions skipped, stored as told by the user).
- [x] Don't reuse the model's own answers until the user approves them (`/good`), so made-up answers can't reinforce themselves.
- [x] Real-model check passed (see CLAUDE.md "Real-model check").
- [x] CLI commands: `/correct <text>` (verified; marks the old item `wrong`), `/good`, `/bad` (score changes), `/protect`.
- [x] Conflict handling: same topic, newer item wins; keep the old one with lower priority.

**Done when:** normal chatting adds memories automatically, and corrections change later answers.

### Phase 3: Checkers and the thinking loop
- [x] Python sandbox checker (subprocess, timeout, no network, temporary directory).
- [x] Maths checker (evaluate the expression or compare with a known result).
- [x] Thinking loop: draft, check, fix up to N times (default 3), **only when a checker applies**.
- [x] Code that passes the checker is saved as a `verified` lesson (task + solution + the mistakes it fixed).

**Done when:** coding tasks are retried until the tests pass, and passing solutions are stored as verified.

### Phase 3.5: Reliable, self-updating memory (added 2026-11-25)

Why: dore gathers notes but doesn't yet learn like a brain.
Probes found bad writes (non-facts stored as verified, word-order-blind merges, `/correct` hiding true notes)
and weak recall (no "I don't know", no dates). The user will not type `/correct` or `/good`: learning must
come from plain conversation.

Target architecture (each part measured before the next; the 1B model never decides what to update or delete):

```
conversation -> ① event log (append-only) -> background worker (low priority, single writer)
                                               ├─ ② fact slots: subject/attribute/value + valid from/to
                                               ├─ ③ text notes (today's store) + likely-question search keys
                                               ├─ ④ lessons ("when X, do Y") + helped/hurt counters
                                               └─ ⑤ profile card (top facts about the user)
question -> ⑥ router -> slot lookup | note search | code checker | plain LLM
```

Steps:
- [x] 1. (done 2026-11-25; 71 unit tests, selftest 30/31, see `reports/selftest.md`) Fix write/read bugs: order-aware duplicate check; merges keep the first date and update the source;
      `/correct` demotes only notes with the same sentence frame (not every note on the topic); agents can't mark
      protected or user-stated notes wrong; non-facts (`[Request interrupted…]`, `/commands`, hypotheticals, long
      pastes in Claude Code) are not stored; the near-duplicate result filter keeps differing (possibly
      opposite) notes; keyword search skips wrong/unapproved rows in SQL; no write lock held while embedding.
- [x] 2. (done 2026-11-25; 79 unit tests, selftest `plain-correct` 3/3) Automatic updates from plain chat: detect corrections ("no, it's X", "actually …"); a new fact with the
      same frame and one changed detail replaces the old one (`valid_to`, `replaced_by`, never deleted);
      unclear cases keep both. Notes shown with their date.
- [x] 3. (done 2026-11-25; 85 unit tests, selftest 36/37) Implicit feedback: re-asking = the last answer failed; moving on = weak OK; code passing = verified.
      Guessed feedback weighs less than explicit feedback. Usage and feedback change ranking.
- [ ] 4. `bench stream`: simulated days; measure repeat-mistake rate, stale-fact use, accuracy over time,
      store size, search time.
- [ ] 5. Fact slots + profile card; router; reliable "I don't know" (no slot, no strong note -> 0 notes).
- [ ] 6. Recall: likely-question keys per fact (written in idle time), small reranker (measure CPU latency).
- [ ] 7. Lessons (first test whether the 1B model follows them); optional learned search adapter / ranking
      (tiny CPU training on the user's own feedback: needs the user's OK, the LLM is never trained).

Token rules (Claude Code plugin):
- All learning runs locally (rules, embedder, 1B in idle time): 0 Claude tokens.
- Nothing relevant -> nothing added (already true). Cap: at most ~150 tokens of notes per prompt.
- Fact slots are shown as short lines ("city: Siem Reap"); the profile card once per session, not per prompt.
- The plugin never writes to a project's CLAUDE.md.
- Every change is re-measured with the `reports/token-design.md` test; tokens may not grow without a measured gain.

**Done when:** `bench stream` shows fewer repeated mistakes and no stale facts over simulated days, token
overhead is not above today's, and the real-model check still passes.

### Phase 4: Memory maintenance
- [ ] Score = usage + recency + verified + surprise; decays over time.
- [ ] Merge near-duplicates (similarity above a threshold) into one summary that links back to the originals.
- [ ] Archive low-score items (never delete); protected items are exempt.
- [ ] Run in the background when idle; log memory size and search time.

**Done when:** after many synthetic days, memory stays clean and search stays fast.

### Phase 5: Consolidation (skill learning) — DROPPED (2026-11-24)

> Dropped by the user. It doesn't need a GPU (1B LoRA runs on CPU), but on the target i5 laptop a small session would take ~40 min–1.7 h for 1B and ~2–5.5 h for 3B (estimates), for a small, uncertain gain: only the local model improves, Claude is not affected, and the website test showed the local models far behind Claude. dore's learning is memory only. The plan below is kept for reference.

- [ ] Build exam sets: rotating (~30 items), hidden (monthly), final (300 Python problems, never trained on or used for decisions).
- [ ] Select training data: verified lessons only, mixed 30% new / 70% replay.
- [ ] LoRA training with PyTorch CPU + PEFT, low priority, paused while the user chats; sessions of 10–20 minutes.
- [ ] Convert the adapter to GGUF; run the rotating exam; **swap only if the score is equal or better**, otherwise roll back. Keep all versions and their scores.
- [ ] Optional: run large training jobs on a free cloud GPU and import the adapter.

**Done when:** an adapter can be trained, examined and hot-swapped without stopping the chat, and a worse adapter is rejected automatically.

### Phase 6: Search tool (optional)
- [ ] Web search through a search API or tool; results are saved as `unverified` with source and date.
- [ ] Search results never enter training until the user confirms them or a test confirms them.

### Phase 7: The 30-day experiment
- [ ] Daily use: practise on Python problems (excluding the final exam) and chat normally.
- [ ] Weekly: final-exam score, old-skills score, memory size, search time, adapter versions kept or rejected.
- [ ] Write up the results in `reports/results.md`: does it keep improving, where does it plateau, what broke.

## Known limits (accepted)

- Self-checking only works for testable tasks (code, maths, puzzles).
- A small fixed-size core reaches a ceiling; facts scale through memory, skills do not scale forever.
- CPU training is slow (~12–30 examples per 10 minutes for 1B); use the cloud for heavy jobs.

## Later (not now)

- Rust for hot paths if profiling shows a need.
- Separate adapters per skill area, loaded on demand (raises the ceiling).
- Brain-inspired spiking-network experiments (separate project).
