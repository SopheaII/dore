# dore agent guide

dore is a local memory for Claude Code and other coding agents that keeps learning from everyday use without training: every fact and correction is a note in fast memory (SQLite + FAISS), learned and shared through hooks at ~0 Claude tokens. Project facts stay in their project; facts about the user and organisation are general. (dore's own chat with a local 1B model still exists but is not used day to day.) Roadmap: below; known weaknesses: the rule files. Sources of borrowed ideas: `REFERENCES.md` (add new ones; mark unverified ones ⚠️).

## Rules (do not break)

- **No model training** (dropped by the user). Facts live in fast memory only; the core LLM never changes.
- **Never hard-delete a memory.** Low-score notes are archived; protected notes are never archived automatically. Replaced or wrong notes stay in SQLite.
- **Trust levels**: `verified` (passed a test, or stated or confirmed by the user), `unverified` (search results, unchecked answers, agent-written facts), `wrong` (kept, never returned as truth). An agent or unverified note never overrules a user's verified fact.
- **Newer wins** when two notes conflict; store dates on everything.
- **Draft-check-fix loops only with a real checker** (run the code, check the maths); otherwise answer once.
- **CPU-only laptop baseline** (4+ cores with AVX2, 8 GB RAM, no GPU, Linux): no Apple-only (MLX) or NVIDIA-only (CUDA) tools in the core path; background work at low priority, paused while the user chats, 4 threads. Heavy work in native code (llama.cpp, FAISS), never Python loops over large data.
- **One roadmap step at a time**; finish and measure it (`bench stream`) before the next.

## Working here

- Use the cheapest check that covers the change: `.venv/bin/pytest -q`, then `.venv/bin/python -m dore.eval.conversation`, `-m dore.eval.learning` and `-m dore.eval.stream` (~10 s each, no LLM).
- Learning rules must work for anyone's wording: decide by shape, grammar or meaning, never by lists of topic or action words; design on DEV cases, judge on HELDOUT and fresh real prompts (`learning-change` skill). Run the local model (`dore`, `dore.eval.selftest`) only when the user asks.
- Explain results in plain, simple English with tables; mark estimates as estimates. Commit or push only when the user asks.
- Update the rule file whose measured behaviour changed, and the roadmap below when a step finishes.

| Changing | Read | Skill |
|---|---|---|
| What is learned, merged, replaced, demoted or retrieved (`src/memory/`, `src/learn/`), prompts | [memory-learning](.agents/rules/memory-learning.md) | `learning-change`, then `review-learning` on the diff |
| Anything a coding agent sees or runs (`plugin/`, `src/integrations/`) | [claude-code](.agents/rules/claude-code.md) | `hook-cost` |
| Checks, benchmarks, reports | [testing](.agents/rules/testing.md) | — |

## Layout

`src/` **is** the `dore` package (`package-dir = {"dore" = "src"}`); import with full paths (`from dore.memory import MemoryStore`). Each layer imports only earlier ones: `config.py` → `memory/` (types, schema, rules, store, embed, ingest; no model) → `learn/` (what to learn from a message: `statements` shape and word rules, `grammar` spaCy gate) → `assistant/` (core, agent, checkers) → `integrations/` (hooks, hookd, hookclient, bridge, server; never imports `assistant/` at module level) → `apps/` (cli, web) → `eval/` (cases, learning, conversation, stream, scale, bench, selftest).

- Git-ignored, never commit: `data/` (models, memory DB, caches), `reports/` (one machine's results).
- fastembed caches in `/tmp` by default (wiped on reboot): always pass `cache_dir=cfg.cache_dir / "fastembed"`.
- Setup: `uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -e ".[dev]"`

## Roadmap (one step at a time)

Done: memory store, learning from plain chat, replace/merge/correct, implicit feedback, projects, hybrid search,
Claude Code hooks (0 tokens when nothing matches, ~0.07 s), `bench stream` (2026-11-25), grammar gate for what is
learned + structural updates + newer-first notes (2026-11-25; junk on fresh real prompts 27/118 -> 7/118). Dropped: model training.
Success = `bench stream`: correct up, stale/leak/junk/repeat mistakes down, tokens per prompt not up.

1. Mostly done (2026-11-25; real replay 70 -> 46 notes, every real fact kept; echo check; hub correction). Left: reworded updates keep both notes (stale 7/11 in weeks 3–4); rephrased questions miss (retrieval 5/8, moves to step 5). Details: [memory-learning](.agents/rules/memory-learning.md).
2. Learn from Claude's side at SessionEnd: measured 2026-11-25 on 117 real sessions, "a failed shell command then a similar one that worked" gave 2 lessons, both junk (exploratory reads in long chained commands; 145 of 186 real failures are long multi-step commands): not adopted. Commit messages only repeat `git log`. Next signal to measure: the user accepting a proposal ("yes, keep that").
3. Forgetting (first part done 2026-11-25: `dore.learn.recheck` archives notes today's rules would not store). Left: score (use + recency + trust), decay, archive (never delete; protected exempt), merge similar notes; idle time.
4. Project -> general promotion: a fact seen or helpful in 2+ projects becomes general (project copies kept, linked); one project's names/paths/IDs never go general; identify a project by git root, not folder name.
5. Retrieval: likely-question keys per note (`bge-base-en-v1.5` measured: +1 to +3 points end to end for 2x hook time, not adopted) (biggest remaining miss: "How long should your answers be?" vs "I prefer short answers"), then fact slots + profile card (once per session), small reranker.
6. Other languages: multilingual parser + embedder (Khmer is neither learned nor found today).

