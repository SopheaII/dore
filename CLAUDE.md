# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project: dore

A small local AI that **keeps learning from everyday use** (tasks, questions, searches, corrections) while it keeps working, like the brain's hippocampus + cortex + sleep. No bulk training: knowledge arrives a little at a time from real use.

The design combines existing work (Voyager, Letta, SEAL, Nested Learning/Titans, TRM, SLIDE, RAG, LoRA, complementary learning systems); `REFERENCES.md` maps each part to its source. Add new sources there when a design idea is borrowed, and mark unverified ones ⚠️.

## Architecture (5 parts)

1. **Stable core**: small pretrained LLM (Llama 3.2 1B Instruct by default, 3B optional; 4-bit GGUF; see PLAN.md "Review v2") plus one small LoRA adapter. It learns **skills and habits only, never facts**.
2. **Fast memory (RAG)**: every fact, lesson, correction and search result is stored as a record (text, vector, source, trust level, date, times used, score) and found with vector search. This is how the system learns instantly.
3. **Thinking loop**: draft, check, fix. **Only used when a real checker exists** (run the code, check the maths). Otherwise answer once.
4. **Self-checking**: checkers for code and maths. Everything else is marked unverified.
5. **Consolidation**: in idle time or short sessions, train the LoRA adapter on verified lessons with replay, run an exam, and swap the new adapter in only if it passes. Otherwise roll back.

## Hard rules (from the design review; do not break)

- **Never train facts into the core.** Facts live in fast memory only. Fine-tuning on new facts increases hallucination (Gekhman et al. 2024).
- **Never train on unverified model-generated text.** Use only test-passed results and real human data, always mixed with replay (default 30% new / 70% old). This prevents model collapse (Shumailov et al. 2024).
- **Never hard-delete memories.** Low-score items move to the archive. Items the user marks as protected are never archived automatically.
- **The adapter swap needs a passed exam**; keep the previous adapter for rollback.
- **Three exam sets**: a rotating short exam (every swap), a hidden exam (monthly), and a final exam (measurement only, never used for decisions or training).
- **Trust levels**: `verified` (passed a test, or taught, stated or confirmed by the user), `unverified` (search results, unchecked answers), `wrong` (kept for reference, never retrieved as truth). Only `verified` items can enter training.
- Newer information wins over older when they conflict (store dates on everything).

## Target hardware

- Baseline: an ordinary **CPU-only laptop** (4+ cores with AVX2, 8 GB+ RAM, no GPU, Linux). Everything must work there; a GPU is an optional speed-up, never a requirement.
- Don't rely on Apple-only (MLX) or NVIDIA-only (CUDA, bitsandbytes QLoRA) tools in the core path. Use plain LoRA on CPU, or train heavy jobs on a cloud GPU and bring the adapter back.
- Rough expectations on such a laptop (measure with `python -m dore.bench`): 1B Q4 inference ~20 tokens/s, 3B ~9 tokens/s; 1B LoRA training ~10–25 tokens/s.
- Training must run at low priority and pause while the user is chatting. Default to 4 threads; thin laptops throttle under long load.

## Stack

- Python 3 for orchestration. Run heavy work in optimised native code (llama.cpp, FAISS); never loop over large data in pure Python.
- Inference: `llama.cpp` (`llama-server` or `llama-cpp-python`), with LoRA adapters loaded in GGUF format.
- Embeddings: small model (e.g. `bge-small-en-v1.5` or `nomic-embed-text`).
- Memory: SQLite for records and metadata, FAISS (HNSW, optionally int8/PQ compression) for the vector index.
- Training: PyTorch (CPU) + PEFT LoRA; convert the adapter to GGUF with llama.cpp's `convert_lora_to_gguf.py`.
- Rust is reserved for later hot paths, only if profiling shows Python is the bottleneck.

## Layout and commands

- Standard `src/` layout: the package is `src/dore/`, tests are in `tests/`. Git-ignored: runtime data in `data/`, machine-specific benchmark and test reports in `reports/`.
- Setup: `uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -e ".[dev]"`
- Tests: `.venv/bin/pytest` (no model needed; uses `HashEmbedder` and a fake core).
- Goal test with the real model (throw-away store, never touches `data/`): `.venv/bin/python -m dore.selftest [seeds] [scenario]`.
- Chat: `.venv/bin/dore`. Benchmarks: `.venv/bin/python -m dore.bench llm|search|embed|memory|remember`.

## Current status (2026-11-24)

- Phases 0–3 of `PLAN.md` are done: chat, fast memory, learning from plain chat, `/teach` `/correct` `/good` `/bad` `/protect` `/load` `/code` `/mem` `/stats`, code checker with fix loop. 34 tests pass; `dore.selftest` (5 seeds) passes 23/26 checks fully, the rest are 1B-model limits (see Known weaknesses).
- Speed/robustness pass done (2026-11-24): batched writes (`MemoryStore.add_many`), unapproved answers kept out of the FAISS index, index file written at most every 120 s (checked against SQLite and rebuilt at startup if stale), thread-safe store, prompts trimmed to fit `n_ctx`, bounded code-fix prompts, CLI survives command errors. Measurements in `reports/benchmarks.md`.
- **Next: Phase 4** (memory maintenance: score decay, merging near-duplicates, archiving).
- Initial version not yet committed to git.

## How memory learning works (verified with the real 1B model; don't regress)

Unit tests use a fake core and can't catch these; after any change to prompts or retrieval, rerun the real-model check below.

- **Statements in plain chat are learned automatically**: `Agent.remember_statements` splits the user's message into sentences, skips questions (ending in `?` or starting with a `QUESTION_START` word) and sentences under 3 words, and stores each one as `kind="statement"`, `source="user"`, `trust="verified"`. One fact per memory matches questions far better than a whole message.
- **The model's own answers (`kind="answer"`) are stored but kept out of the vector index until the user approves them with `/good`** (which makes them `verified`; `memory.searchable()` is the single rule). Otherwise made-up answers come back as "memory" and reinforce themselves (observed: an invented "Elm Street" address), and they used to crowd real facts out of the top-20 search candidates. They are also never merged with other memories, so `/correct` can't mark a user's fact wrong.
- **Statement filter** (`split_statements`): "Please remember / FYI / can you note that X" stores X (even in question form); small talk ("Thanks a lot!", "Hello, how are you") and requests ("Summarize the following text") are not stored. Requests need verb + object, so "Help desk number is 555" is still a statement.
- **`/correct` also marks wrong the used notes that conflict with the correction** (similarity >= 0.7 to it: "My car is a Toyota" vs "My car is a Honda" = 0.84, unrelated facts <= 0.62). Without this the model answered "a Honda or a Toyota" 3/3. They are kept, never deleted (`Agent.last_demoted_ids`).
- **Duplicates merge only when words and numbers match exactly** (plus similarity >= 0.95): bge-small scores "server IP 10.0.0.5" vs "10.0.0.6" at 0.985, and merging lost one of them.
- **Long messages** (more than 20 statements or 3000 characters) are stored as `unverified` document chunks (`source="chat-paste"`), not as verified facts.
- **Questions about the user get `NO_GUESS`** ("If no note above answers this, say you don't know.") after the question. Measured with 7 questions × 8 seeds: 54/56 strict vs 42/56 without (the model invented "Your dog is called Kavi"). Longer wordings were worse (one turned "Calmette Hospital" into "Pasteur Institute"). One run of the real-model check is not enough to compare prompts: sample several seeds with `llm.set_seed`.
- **Memory notes go in the user turn, right before the question**, not in the system prompt: the 1B model ignored system-prompt notes.
- **Notes are labelled with their origin** (`[verified, told by the user]`, `[unverified, from a document]`, `tested`). Without "told by the user", the 1B model read "My favourite language is…" as being about itself.
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

Expected (passes as of 2026-11-24): Mochi / Phnom Penh / nurse at Calmette Hospital / "no information about your dog" / Paris.

## Known weaknesses

- Search misses questions phrased very differently from the stored fact (e.g. "job" vs "work as a nurse" scores 0.55). Options: a stronger embedding model (`bge-base`) or adding keyword matching (hybrid search).
- `bge-small-en-v1.5` is English-only; other languages need a multilingual embedding model and a full re-embed.
- Every add checks for duplicates with an exact (flat) search, which is O(n) per item: fine for chat, but bulk-loading 100k items into a 100k store takes minutes (measured 440 items/s). Switch to HNSW above ~200k items.
- 1B-model limits seen in `dore.selftest` (5 seeds): still invents a dog name 2/5 when only the cat is known; refuses to tell a stored wifi password 2/5 ("I do not have access"); with two same-day conflicting statements ("I live in Phnom Penh" then "I live in Siem Reap") it mentions the old one 1/5. Notes carry no dates yet.
- The 1B model ignores `unverified` notes, so answers about long pasted text are weak (stored correctly, poorly used).
- The 1B model retrieves and repeats facts well but reasons weakly across several facts; 3B (`--model data/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf`) is ~2× slower.
- Statements are trusted as the user said them; false statements need `/correct`.
- The code sandbox can't block network access (user namespaces are often disabled); it uses timeouts, rlimits, a temporary directory and `python -I`.

## Working conventions

- Measure before claiming performance numbers; write results to `reports/` (never committed, since they describe one machine).
- Keep the core model, adapters, memory DB and model caches under `data/` (git-ignored); never commit model weights or personal memory.
- Every learning change must be measurable: log the exam scores of each adapter version.
- Keep it simple: one feature per phase in `PLAN.md`, and finish and test it before starting the next.
- `fastembed` caches models in `/tmp` by default (wiped on reboot); always pass `cache_dir=cfg.cache_dir / "fastembed"`.
- When waiting on a background process in shell, don't `pgrep -f` a string that also appears in the waiting command itself: it matches itself and waits forever.
- Explain results to the user in plain, simple English with tables; mark estimates as estimates and say which claims were actually measured.
