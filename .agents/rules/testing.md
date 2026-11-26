# Testing, measuring and conventions

Checks from cheapest to dearest, baselines, conventions.

## Checks (cheapest first)

| Check | Command | Cost | When |
|---|---|---|---|
| Unit tests | `.venv/bin/pytest -q` | ~6 s, no model | every change (the warm-helper test needs Linux) |
| Conversation check | `.venv/bin/python -m dore.eval.conversation` | ~10 s, embedder only | any memory, learning or hook change |
| Learning check | `.venv/bin/python -m dore.eval.learning [--real] [--styles]` | ~10 s, embedder + parser | any change to what is learned, replaced or retrieved |
| Stream check | `.venv/bin/python -m dore.eval.stream` (= `bench stream`); `… stream seeds 5` for varied wording | ~7 s per seed | any learning, scope or hook change |
| Scale check | `.venv/bin/python -m dore.eval.scale [projects] [weeks] [seed]` | ~95 s (12 projects, 24 weeks, 8,640 prompts) | retrieval, ranking or growth changes |
| Real replay | replay every real prompt from `~/.claude/projects/*/*.jsonl` (with Claude's replies as echo) into a throw-away store and read what is stored (script kept outside the repo: private data) | ~60 s | learning changes; report counts only |
| Lint | `uvx pyflakes src tests` | ~1 s | after moving or splitting code |
| README demo | `.venv/bin/python -m dore.eval.demo` | ~5 s | after a change that alters the README example's output (update the README) |
| Benchmarks | `.venv/bin/python -m dore.eval.bench search\|embed\|memory\|scale\|stream` | minutes | speed claims |

Baselines (2026-11-25, after the grammar gate). A change must not lower "correct/learned" or raise junk, stale, leaks, missed or tokens:

| Check | Baseline |
|---|---|
| Conversation | short 5/7, old shown 0/3; long 80/80, 0/53, ~49 tokens per question |
| Learning: facts right scope / junk | DEV 52/56, 2/73; HELDOUT 38/41, 0/39; updates 35/35; retrieval 9/10 (2026-11-26, clause-end prepositions) |
| Learning `--real` (private, `data/eval/`) | sample 1: 0/2, junk 2/119; fresh sample: 3/3, junk 5/118 (both have now been used for error analysis: label a new sample for an unbiased number) |
| Stream, seeds 1–5 mean (2026-11-26, place keys, session repeats) | correct per week 28.6, 28.4, 26.2, 26.0 /30; stale 0, 0.4, 2.0, 2.4; leaks 0; repeat mistakes 6.4; junk 10.8 of ~467; missed 0 of 29; 2.0 notes in the 220-prompt session; 3.7 tokens per work prompt |
| Scale, 12 projects × 24 weeks (2026-11-26, place keys) | correct 86, 81, 80, 80, 80, 81 % at weeks 4–24; stale 2/12 at week 24; leak ≤1; junk 195 of ~8,500 noise; missed 3 of 112; 32 tokens per question, 6.4 per work prompt; hook 11 ms median, 23 ms p95 |
| Real replay (1,036 prompts, 2026-11-26, raw memory on, consolidating between sessions) | 191 rows (notes + hidden requirements), 314 episodes, 7.3 tokens added per prompt, hook 24 ms median, 250 ms p95 |
| Stream, seed 7 | 24, 24, 23, 22 /30; stale 0, 1/2, 3/10, 4/11; junk 14 (8 notes); hook 9 ms median |

## Conventions

- Write measured results to `reports/` (git-ignored: they describe one machine) and give the numbers in the handoff.
- Every learning change must be measurable: extend `dore.eval.conversation` (cheapest), or add a `dore.eval.bench` measurement.
- **Generalisation discipline** (`src/eval/cases.py`): design on DEV, judge on HELDOUT and real prompts. Add new DEV cases in your own wording before fixing a pattern; never add HELDOUT or real sentences to a rule. A rule that lifts DEV but not HELDOUT learned the wording, not the meaning. Once real prompts were used for error analysis, label a fresh unseen sample for the honest number (`data/eval/`, git-ignored, private: report counts only, never quote them in commits or public files).
