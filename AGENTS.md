# dore agent guide

dore is a local memory for Claude Code and other coding agents that keeps learning from everyday use without training: every fact and correction is a note in fast memory (SQLite + FAISS), learned and shared through hooks at ~0 Claude tokens. Project facts stay in their project; facts about the user and organisation are general. It is used only through coding agents (Claude Code, opencode, MCP clients): dore's own local-model chat and web chat were removed on 2026-11-26. Roadmap: below; known weaknesses: the rule files. Sources of borrowed ideas: `REFERENCES.md` (add new ones; mark unverified ones ⚠️).

## Rules (do not break)

- **No model training** (dropped by the user). Facts live in fast memory only; the core LLM never changes.
- **Never hard-delete a memory.** Low-score notes are archived; protected notes are never archived automatically. Replaced or wrong notes stay in SQLite.
- **Trust levels**: `verified` (passed a test, or stated or confirmed by the user), `unverified` (search results, unchecked answers, agent-written facts), `wrong` (kept, never returned as truth). An agent or unverified note never overrules a user's verified fact.
- **Newer wins** when two notes conflict; store dates on everything.
- **Draft-check-fix loops only with a real checker** (run the code, check the maths); otherwise answer once.
- **CPU-only laptop baseline** (4+ cores with AVX2, 8 GB RAM, no GPU, Linux): no Apple-only (MLX) or NVIDIA-only (CUDA) tools in the core path; background work at low priority, paused while the user chats, 4 threads. Heavy work in native code (FAISS, ONNX via fastembed), never Python loops over large data.
- **One roadmap step at a time**; finish and measure it (`bench stream`) before the next.
- **Fix the design, not the example.** When something fails, find the missing concept or the decision made in the
  wrong place (the data model, when it is decided, what evidence it uses) and change that, so the whole class of
  cases works. No new word lists, thresholds tuned to one case, or special cases for one sentence; existing lists
  should shrink. Before building a part, look for a maintained library that already does it (PyPI,
  `REFERENCES.md`), measure it, and prefer it over writing our own. No new ready-made AI models (the user's choice,
  2026-11-26): use evidence (what the user and Claude do next) and the parser and embedder dore already has.
- **Speed is part of the design.** The prompt hook stays fast (median ~10–25 ms; `bench stream`, `bench scale`).
  A model on the prompt path must be small (ONNX) and run on a few items only; heavier models run in idle
  consolidation. Report ms and tokens with every change.

## Working here

- Use the cheapest check that covers the change: `.venv/bin/pytest -q`, then `.venv/bin/python -m dore.eval.conversation`, `-m dore.eval.learning` and `-m dore.eval.stream` (~10 s each, no LLM).
- Learning rules must work for anyone's wording: decide by shape, grammar or meaning, never by lists of topic or action words; design on DEV cases, judge on HELDOUT and fresh real prompts (`learning-change` skill).
- Explain results in plain, simple English with tables; mark estimates as estimates. Commit or push only when the user asks.
- Update the rule file whose measured behaviour changed, and the roadmap below when a step finishes.
- **Few comments.** Write no comment that repeats the code or the function name. Keep only a short one-line comment for a non-obvious *why* (a hidden constraint, a measured threshold, a workaround). Module docstrings: one or two lines saying what the file is for. No dates, measurement logs, example sentences or history in code comments; put those in the rule files or the roadmap.

| Changing | Read | Skill |
|---|---|---|
| What is learned, merged, replaced, demoted or retrieved (`src/memory/`, `src/learn/`), prompts | [memory-learning](.agents/rules/memory-learning.md) | `learning-change`, then `review-learning` on the diff |
| Anything a coding agent sees or runs (`plugin/`, `src/integrations/`) | [claude-code](.agents/rules/claude-code.md) | `hook-cost` |
| Checks, benchmarks, reports | [testing](.agents/rules/testing.md) | — |

## Layout

`src/` **is** the `dore` package (`package-dir = {"dore" = "src"}`); import with full paths (`from dore.memory import MemoryStore`). Each layer imports only earlier ones: `config.py` → `memory/` (types, schema, rules, store, embed, ingest; no model) → `learn/` (what to learn from a message: `statements` shape and word rules, `grammar` spaCy gate) → `integrations/` (hooks, hookd, hookclient, bridge, server, backfill) → `eval/` (cases, learning, conversation, stream, scale, bench, demo).

- Git-ignored, never commit: `data/` (models, memory DB, caches), `reports/` (one machine's results).
- fastembed caches in `/tmp` by default (wiped on reboot): always pass `cache_dir=cfg.cache_dir / "fastembed"`.
- Setup: `uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -e ".[dev]"`

## Roadmap (one step at a time)

Done: memory store, learning from plain chat, replace/merge/correct, implicit feedback, projects, hybrid search,
Claude Code hooks (0 tokens when nothing matches, ~0.07 s), `bench stream` (2026-11-25), grammar gate for what is
learned + structural updates + newer-first notes (2026-11-25; junk on fresh real prompts 27/118 -> 5/118), topic keys per note + updates that name the old value (2026-11-26; scale correct 72 -> 79%, repeat mistakes 13 -> 7.6). Dropped: model training.
Success = `bench stream`: correct up, stale/leak/junk/repeat mistakes down, tokens per prompt not up.

1. Done (2026-11-26; real replay 70 -> 46 notes, every real fact kept; echo check; hub correction; stale weeks 3–4 2.0/2.8). Left for meaning, not rules: synonym topics ("db" / "database", "deploy" / "hosted"). Details: [memory-learning](.agents/rules/memory-learning.md).
2. Learn from Claude's side at SessionEnd: measured 2026-11-25 on 117 real sessions, "a failed shell command then a similar one that worked" gave 2 lessons, both junk (exploratory reads in long chained commands; 145 of 186 real failures are long multi-step commands): not adopted. Commit messages only repeat `git log`. Next signal to measure: the user accepting a proposal ("yes, keep that").
3. Consolidation and forgetting. Done: `dore.learn.recheck` archives notes today's rules would not store (2026-11-25); raw memory of every typed sentence that is not a note, consolidated while idle and judged again when the rules change, so a fixed rule also learns past sentences (`memory.episodes`, `hooks.consolidate`, `integrations.backfill`; 2026-11-26; recall of raw sentences on a cue measured ~3 useful of 11: off). Done 2026-11-26: notes on trial, Voyager-style (shown only on questions until Claude's reply clearly uses them or the user says them again; tried 3 times unused -> archived; real replay 280 -> 121 note lines; tokens per work prompt 3.7 -> 0.4). Next: a raw sentence that tells something, said again in another session, becomes a note. Left: score (use + recency + trust), decay, archive (never delete; protected exempt), merge similar notes.
4. Scope redesign (plan: [scope-redesign](.agents/plans/scope-redesign.md), 2026-11-26): a project is its git repo
   (worktrees and subfolders share it), not its folder name; scope belongs to what a fact is about, not its wording;
   updates stay in their level; levels user / workspace / repo / home, most specific wins; promotion by evidence
   (same value in 2+ repos; project copies kept, linked; one repo's names/paths/IDs never go general); no
   cross-project fallback; the user can move a note's scope. Steps S1–S5 in the plan, one at a time; S1 (project = git repo, start folder without git), S2 (updates keep their scope, no cross-project notes), S3 safe part (where a fact was said decides who its change reaches) done 2026-11-26.
5. Retrieval: topic keys done (2026-11-26, retrieval 5/8 -> 7/8; `bge-base-en-v1.5` measured: +1 to +3 points for 2x hook time, not adopted). Left: synonym questions ("What is my job?" vs "I work as a nurse"), profile card (once per session), small reranker.
6. Other languages: multilingual parser + embedder (Khmer is neither learned nor found today).

