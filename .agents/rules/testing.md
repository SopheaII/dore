# Testing, measuring and conventions

Checks from cheapest to dearest, baselines, conventions.

## Checks (cheapest first)

| Check | Command | Cost | When |
|---|---|---|---|
| Unit tests | `.venv/bin/pytest -q` | ~6 s, no model | every change (all pass on macOS and Linux) |
| Conversation check | `.venv/bin/python -m dore.eval.conversation` | ~10 s, embedder only | any memory, learning or hook change |
| Learning check | `.venv/bin/python -m dore.eval.learning [--real] [--styles]` | ~10 s, embedder + parser | any change to what is learned, replaced or retrieved |
| Lists check | `.venv/bin/python -m dore.eval.lists` (recorded Haiku answers, 0 tokens; `--live` asks for new ones) | ~5 s | long messages, groups, pastes, `BLOCK_SYSTEM` |
| Rules check | `.venv/bin/python -m dore.eval.rules` | ~5 s, embedder only | any change to standing rules, session start, trial |
| Stream check | `.venv/bin/python -m dore.eval.stream` (= `bench stream`); `… stream seeds 5` for varied wording | ~7 s per seed | any learning, scope or hook change |
| Install smoke test | `sh tests/smoke/smoke.sh` (Windows: `tests\smoke\smoke.ps1`): installs from this checkout into a temp folder, saves and recalls a fact through the real hook command, uninstalls | ~40 s, downloads packages | any change to `npm/`, `plugin/hooks/` or the helper |
| CI (`.github/workflows/ci.yml`) | runs on every push and pull request: unit tests on Linux x64/arm64, macOS arm64/x64, Windows x64 (Windows arm64 optional); evals on Linux x64; the install smoke test on all of them | GitHub's machines | before publishing to npm |
| Scale check | `.venv/bin/python -m dore.eval.scale [projects] [weeks] [seed]` | ~95 s (12 projects, 24 weeks, 8,640 prompts) | retrieval, ranking or growth changes |
| Real replay | replay every real prompt from `~/.claude/projects/*/*.jsonl` (with Claude's replies as echo) into a throw-away store and read what is stored (script kept outside the repo: private data) | ~60 s | learning changes; report counts only |
| Lint | `uvx pyflakes src tests` | ~1 s | after moving or splitting code |
| README demo | `.venv/bin/python -m dore.eval.demo` | ~5 s | after a change that alters the README example's output (update the README) |
| Benchmarks | `.venv/bin/python -m dore.eval.bench search\|embed\|memory\|scale\|stream` | minutes | speed claims |

Baselines (2026-11-25, after the grammar gate). A change must not lower "correct/learned" or raise junk, stale, leaks, missed or tokens:

| Check | Baseline |
|---|---|
| Conversation | short 5/7, old shown 0/3; long 80/80, 0/53, ~49 tokens per question |
| Rules (2026-11-26) | 30/31 with replies that do not contain the rule words (31/31 before was partly from invented replies holding them; fails: a preference about the user reaching every project) cases incl. practice, noise (yes/ok, repeated requests, tastes, facts said twice) and a 60-message session (quoting a rule: known gap); rules per session 70 / 122 / 157 / 158 / 160 tokens for 3 / 6 / 10 / 20 / 40 proven rules (old most ~167) |
| Learning: facts right scope / junk | DEV 58/62, 7/81; HELDOUT 43/46, 3/46 (2026-11-26, + clause split cases); before: DEV 55/59, 7/80; HELDOUT 40/43, 3/45; updates 35/35; retrieval 9/10 (2026-11-26, + 18 quick non-native cases for the junk plan: 8 of 13 such chatter lines stored, 5 of 5 such facts learned; before them DEV 52/56, 2/73, HELDOUT 38/41, 0/39) |
| Learning `--real` (private, `data/eval/`) | sample 1: 0/2, junk 2/119; fresh sample: 3/3, junk 5/118 (both have now been used for error analysis: label a new sample for an unbiased number) |
| Stream, seeds 1–5 mean (2026-11-26, notes on trial + scope S2) | correct per week 28.6, 28.4, 27.6, 27.6 /30; stale 0, 0.4, 2.0, 2.4; leaks 0; repeat mistakes 5.0; junk 10.8 of ~467; missed 0 of 29; 2.0 notes in the 220-prompt session; 0.8 tokens per work prompt (0.3 before same words counted as the same note whatever the punctuation, `store.same_words`: true repeats now prove a fact, which is then shown on strongly matching work prompts; correct/stale/leak unchanged) |
| Scale, 12 projects × 24 weeks (2026-11-26, notes on trial + scope S2) | correct 86, 81, 80, 80, 80, 81 % at weeks 4–24; stale 2/12 at week 24; leak ≤1; junk 195 of ~8,500 noise; missed 3 of 112; 29 tokens per question, 0.4 per work prompt (rules on trial); hook 6–7 ms median, 13–17 ms p95 (parse cache) |
| Real replay (1,036 prompts, 2026-11-26, raw memory on, consolidating between sessions) | 191 rows (notes + hidden requirements), 314 episodes, 7.3 tokens added per prompt, hook 24 ms median, 250 ms p95 |
| Lists (2026-11-27) | entries found later: word rules 6/16, Haiku 15/16; ~66 tokens per answer; recall 50/50; noise notes 0 of 8 messages; secrets 0; similar-word work prompts given list text: word rules 1/72, Haiku 3/72; Haiku ~1,550 tokens per call |
| Stream, seed 7 | 24, 24, 23, 22 /30; stale 0, 1/2, 3/10, 4/11; junk 14 (8 notes); hook 9 ms median |

## Conventions

- Write measured results to `reports/` (git-ignored: they describe one machine) and give the numbers in the handoff.
- Every learning change must be measurable: extend `dore.eval.conversation` (cheapest), or add a `dore.eval.bench` measurement.
- **Generalisation discipline** (`src/eval/cases.py`): design on DEV, judge on HELDOUT and real prompts. Add new DEV cases in your own wording before fixing a pattern; never add HELDOUT or real sentences to a rule. A rule that lifts DEV but not HELDOUT learned the wording, not the meaning. Once real prompts were used for error analysis, label a fresh unseen sample for the honest number (`data/eval/`, git-ignored, private: report counts only, never quote them in commits or public files).

| Haiku consolidation | `.venv/bin/python -m dore.eval.consolidation` (recorded answers, 0 tokens; `--live` asks for new ones, `--real` private) | ~10 s | `learn/judge.py`, `learn/consolidate.py` |
