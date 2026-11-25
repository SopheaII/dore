# Testing, measuring and conventions

Checks from cheapest to dearest, baselines, conventions.

## Checks (cheapest first)

| Check | Command | Cost | When |
|---|---|---|---|
| Unit tests | `.venv/bin/pytest -q` | ~5 s, no model | every change (the code-sandbox and warm-helper tests need Linux) |
| Conversation check | `.venv/bin/python -m dore.eval.conversation` | ~10 s, embedder only | any memory, learning or hook change |
| Learning check | `.venv/bin/python -m dore.eval.learning [--real] [--styles]` | ~10 s, embedder + parser | any change to what is learned, replaced or retrieved |
| Stream check | `.venv/bin/python -m dore.eval.stream` (= `bench stream`); `… stream seeds 5` for varied wording | ~7 s per seed | any learning, scope or hook change |
| Scale check | `.venv/bin/python -m dore.eval.scale [projects] [weeks] [seed]` | ~95 s (12 projects, 24 weeks, 8,640 prompts) | retrieval, ranking or growth changes |
| Real replay | replay every real prompt from `~/.claude/projects/*/*.jsonl` (with Claude's replies as echo) into a throw-away store and read what is stored (script kept outside the repo: private data) | ~60 s | learning changes; report counts only |
| Lint | `uvx pyflakes src tests` | ~1 s | after moving or splitting code |
| Benchmarks | `.venv/bin/python -m dore.eval.bench llm\|search\|embed\|memory\|remember` | minutes | speed claims |
| Real-model self-test | `.venv/bin/python -m dore.eval.selftest [seeds] [scenario]` | minutes, needs the model | only when the user asks (prompt changes for dore's own chat) |

Baselines (2026-11-25, after the grammar gate). A change must not lower "correct/learned" or raise junk, stale, leaks, missed or tokens:

| Check | Baseline |
|---|---|
| Conversation | short 5/7, old shown 0/3; long 80/80, 0/53, ~52 tokens per question |
| Learning: facts right scope / junk | DEV 39/42, 1/51; HELDOUT 38/41, 0/39; updates 19/19; retrieval 5/8 |
| Learning `--real` (private, `data/eval/`) | sample 1: 0/2, junk 2/119; fresh sample: 3/3, junk 5/118 (both have now been used for error analysis: label a new sample for an unbiased number) |
| Stream, seeds 1–5 mean | correct per week 26.0, 26.2, 23.6, 23.2 /30; stale 0, 0.8, 6.8, 7.4; leaks 0; repeat mistakes 13.4; junk 10.8 of ~467; missed 0 of 29; 1.8 notes in the 220-prompt session; 3.7 tokens per work prompt |
| Scale, 12 projects × 24 weeks | correct 77, 72, 71, 70, 69, 70 % at weeks 4–24; stale 5/12 at week 24; leak ≤1; junk 195 of ~8,500 noise; missed 3 of 112; 33 tokens per question; hook 10 ms median, 19 ms p95 |
| Real replay (1,033 prompts) | 46 notes stored, ~7.9 tokens added per prompt, hook 18 ms median |
| Stream, seed 7 | 24, 24, 23, 22 /30; stale 0, 1/2, 3/10, 4/11; junk 14 (8 notes); hook 9 ms median |

## Conventions

- Write measured results to `reports/` (git-ignored: they describe one machine) and give the numbers in the handoff.
- Every learning change must be measurable: extend `dore.eval.conversation` (cheapest), or add a `dore.eval.bench` measurement.
- **Generalisation discipline** (`src/eval/cases.py`): design on DEV, judge on HELDOUT and real prompts. Add new DEV cases in your own wording before fixing a pattern; never add HELDOUT or real sentences to a rule. A rule that lifts DEV but not HELDOUT learned the wording, not the meaning. Once real prompts were used for error analysis, label a fresh unseen sample for the honest number (`data/eval/`, git-ignored, private: report counts only, never quote them in commits or public files).
