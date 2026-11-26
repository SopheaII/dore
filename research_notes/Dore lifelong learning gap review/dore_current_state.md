# dore today: what it can and cannot do for "learning over time like a human grows"

Scope: the local codebase at `/Users/jacky/Documents/dore` (12 commits, 2026-11-24 to 2026-11-25), read on 2026-11-25. Sources are repo files; "[run 2026-11-25]" marks numbers I measured myself by running the no-LLM checks in this session (outputs saved in the session scratchpad, not in the repo). The local LLM was not run. Day-to-day use is the Claude Code hook path (`plugin/hooks` -> `dore-hook prompt|end`), so that path is what is described below; the local 1B chat path is noted only where it differs.

Abbreviations for sources:
- CLAUDE = [/Users/jacky/Documents/dore/CLAUDE.md](/Users/jacky/Documents/dore/CLAUDE.md)
- ML = [.agents/rules/memory-learning.md](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)
- CC = [.agents/rules/claude-code.md](/Users/jacky/Documents/dore/.agents/rules/claude-code.md)
- TEST = [.agents/rules/testing.md](/Users/jacky/Documents/dore/.agents/rules/testing.md)
- REF = [REFERENCES.md](/Users/jacky/Documents/dore/REFERENCES.md)
- RPT = [reports/learning-2026-11-25/README.md](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md) (private, git-ignored)
- LONG = [reports/long-conversation/README.md](/Users/jacky/Documents/dore/reports/long-conversation/README.md)
- SCALE = [reports/learning-2026-11-25/data/scale-after-hub-correction.txt](/Users/jacky/Documents/dore/reports/learning-2026-11-25/data/scale-after-hub-correction.txt)
- Code: [src/memory/store.py](/Users/jacky/Documents/dore/src/memory/store.py), [src/memory/rules.py](/Users/jacky/Documents/dore/src/memory/rules.py), [src/memory/types.py](/Users/jacky/Documents/dore/src/memory/types.py), [src/memory/schema.py](/Users/jacky/Documents/dore/src/memory/schema.py), [src/integrations/hooks.py](/Users/jacky/Documents/dore/src/integrations/hooks.py), [src/learn/grammar.py](/Users/jacky/Documents/dore/src/learn/grammar.py), [src/learn/statements.py](/Users/jacky/Documents/dore/src/learn/statements.py), [src/learn/recheck.py](/Users/jacky/Documents/dore/src/learn/recheck.py), [src/assistant/agent.py](/Users/jacky/Documents/dore/src/assistant/agent.py)

## 1. How dore's memory works today (encode, store, update, forget, consolidate, retrieve, feedback)

### Takeaway
dore is a rule-based, zero-Claude-token episodic fact store: it learns only from the user's own typed messages (one sentence = one note), using shape + spaCy grammar rules, stores each note with trust/scope/dates in SQLite + FAISS, replaces outdated notes by structural "same frame, one value changed" rules, never deletes, and retrieves by hybrid vector+keyword search with a strict 0.65 bar. There is no abstraction, no procedure learning on the Claude Code path, no decay/scoring-based forgetting, and only a tiny implicit feedback signal.

### Cited Findings

**Architecture and hard rules**
- Model training is dropped; facts live only in "fast memory" (SQLite + FAISS); the core LLM never changes. — [CLAUDE](/Users/jacky/Documents/dore/CLAUDE.md)
- Never hard-delete; low-score notes are archived; protected notes never auto-archived; replaced/wrong notes stay in SQLite. — [CLAUDE](/Users/jacky/Documents/dore/CLAUDE.md)
- Trust levels `verified` (user-stated/confirmed or test-passed), `unverified` (agent-written, search results), `wrong` (kept, never returned). Unverified never overrules verified. Newer wins on conflict. — [CLAUDE](/Users/jacky/Documents/dore/CLAUDE.md); enforced in `searchable()` / `SEARCHABLE_SQL` — [types.py](/Users/jacky/Documents/dore/src/memory/types.py)
- Hooks: `UserPromptSubmit` and `SessionEnd` only; the plugin's MCP server was removed 2026-11-25 to save ~200 tokens per request. — [CC](/Users/jacky/Documents/dore/.agents/rules/claude-code.md), [plugin/hooks](/Users/jacky/Documents/dore/plugin/hooks)
- CPU-only baseline (4+ cores AVX2, 8 GB RAM, no GPU). Embedder `bge-small-en-v1.5` via fastembed; parser spaCy `en_core_web_md`. — [CLAUDE](/Users/jacky/Documents/dore/CLAUDE.md), [REF](/Users/jacky/Documents/dore/REFERENCES.md)

**Encoding (what is learned)**
- Only the user's own messages are learned (prompt hook + SessionEnd backfill). Claude's replies, tool calls and commits are not read. — [CC](/Users/jacky/Documents/dore/.agents/rules/claude-code.md)
- Pipeline `message_facts -> user_facts -> grammar.fact_text`: a shape filter drops pastes/logs/code (any language); a spaCy grammar gate drops questions, commands, wishes (want/need), cognition verbs (think/suspect), modals/possibility, future, "it/this" subjects, bare events, opinions without a concrete detail; 3-word facts need a concrete detail (proper noun, number, identifier, path, or out-of-vocabulary word); whole-sentence facts max 20 words. Decided by "shape and grammar, not lists of topic or action words". — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)
- Standing "don't" instructions ("please don't reformat existing code") are kept as lasting preferences unless tied to the moment ("right now", "this time"). — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)
- Long instructions (15+ words, no short fact, constraint grammar) keep a gist (<=240 chars) as `kind="requirement"`, `trust="unverified"`, project scope, **hidden** until said again near-identically (>= 0.85). Showing at 0.75 doubled tokens (8.3 -> 17.6 per prompt) without improving repeat coverage (3/13). 137 gists stored hidden in the real replay. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md); `REQ_SHOW = 1.01`, `REQ_SAME = 0.85` — [hooks.py](/Users/jacky/Documents/dore/src/integrations/hooks.py)
- "Rule cores" inside long requests (negated verb phrase, 2+ content words, e.g. "do not touch old code") are kept as hidden `source="user-rule"` notes; verified and shown when repeated at >= 0.85 (any project). Real sessions: 34 kept hidden, 2 verified, both true. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)
- Echo check: a 5+ word sentence Claude already wrote in this session is not treated as a new user fact. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)
- Learning from Claude's final replies was measured and rejected: 701 real turns gave 3,830 task-log lines; restated user rules matched only 0.60–0.82. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md), [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md)

**Storage (trust, scope, dates)**
- Schema columns: content, kind, source, trust, protected, archived, created, last_used, times_used, times_seen, feedback, vector, last_seen, replaced_by, valid_to, project; plus an FTS5 keyword index kept in step by triggers. — [schema.py](/Users/jacky/Documents/dore/src/memory/schema.py), [types.py](/Users/jacky/Documents/dore/src/memory/types.py)
- User statements are stored `kind="statement"`, `source="user"`, `trust="verified"`. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)
- Scope: a note's project = the session's folder name (`hooks._project`); search sees current project + general. Facts about the user (subject I/my, or subject-less standing rule) and organisation phrasing ("our production server", "we always…") go general; everything else stays in the project. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)
- Long messages (>20 statements or >3000 chars) are stored as `unverified` document chunks. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)

**Updating (replace / merge / correct)**
- Replace: same frame + one detail changed + single-value verb (is/live/work/use/prefer…) -> the new note replaces the old (`replaced_by`, `valid_to` set; old kept in SQLite, leaves search). Multi-value verbs (have/like) keep both. Past tense = events, pile up. "<verb> my X to Y" is a change. Reworded updates with a change word (now/switched/migrated…) replace when most topic words recur and both name a different concrete value. Project note replaces general, never the reverse; unverified never replaces verified. Shortlist bar 0.6. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md), [rules.py](/Users/jacky/Documents/dore/src/memory/rules.py), `_supersede` in [store.py](/Users/jacky/Documents/dore/src/memory/store.py)
- Known limit: synonym topics ("Login uses Auth0" -> "the auth provider is Clerk now") still keep both notes. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)
- Merge: duplicates merge only when words and numbers match exactly in order plus similarity >= 0.95 (bge-small scores "10.0.0.5" vs "10.0.0.6" at 0.985). Merge keeps first `created`, sets `last_seen`. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)
- Correct: "No, …" / "Actually, …" after shown notes marks wrong (kept) every note shown this session that is >= 0.7 similar AND `same_frame` with the correction. Known limit: "My car is red" still matches "My car is a Honda". — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md), `react()` in [hooks.py](/Users/jacky/Documents/dore/src/integrations/hooks.py)

**Forgetting**
- Only forgetting mechanism built: `python -m dore.learn.recheck [--apply]` re-judges user statements with today's rules and archives those that would no longer be stored (reversible via `MemoryStore.restore`); never protected notes, documents, Claude's notes or standing "don't/never/no need" lines. Applied to real memory 2026-11-25: 12 of 15 archived (pasted UI lines, requests); the real rule "Don't run those local model…" kept. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md), [recheck.py](/Users/jacky/Documents/dore/src/learn/recheck.py)
- Forgetting by age was deliberately not built: "the 6-month scale run shows flat speed (10 ms) and accuracy with 282 notes, so there is no measured need yet; ageing out true facts risks hiding them". — [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md)
- In code, `times_used` and `last_used` are written by search but no code reads them for scoring, decay or archiving (grep of `src/`: only written in `store.search`). — [store.py](/Users/jacky/Documents/dore/src/memory/store.py)

**Consolidation**
- Promotion (`hooks._promoted`): a value-free habit said with the same content words in a second project (>= 0.85) is saved as general ("Don't reformat existing code"). Facts with a name or number never move. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md), [hooks.py](/Users/jacky/Documents/dore/src/integrations/hooks.py)
- Repetition-as-strengthening: a requirement or rule core said again (>= 0.85) gets `times_seen+1` and becomes `verified`/shown. — [hooks.py](/Users/jacky/Documents/dore/src/integrations/hooks.py)
- The project itself says rules can't tell a lasting principle from a one-off task: "these gists are the raw material for a later consolidation step"; suggested "a small Haiku call per project, measured cost first". Not built. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md), [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md) Round 4

**Retrieval**
- Hybrid search: FAISS meaning candidates + SQLite FTS5 keyword candidates; rank = similarity + 0.15×keyword share + 0.1 if an identifier matches + 0.05 if verified + 0.03×exp(−age_days/30) + 0.06×tanh(feedback/4); near-duplicate diversity filter; hub correction subtracts 0.7×(closeness to generic developer questions − median). — `search()` in [store.py](/Users/jacky/Documents/dore/src/memory/store.py)
- Hook shows notes only at raw similarity >= 0.65 (`STRONG`), max 3 notes, 160 chars each, 600 chars total (~150 tokens); verified rules of the project are shown once per session (max 6); a newer note about the same thing (note-to-note >= 0.72) is shown first ("newer wins"); a very strong match (>= 0.75) from another project may be shown if nothing local matched. — `prompt_context()` in [hooks.py](/Users/jacky/Documents/dore/src/integrations/hooks.py)
- Notes are embedded without time words (now/currently/still): "Which editor do I use?" vs "My editor is Helix now" 0.638 -> 0.678. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)
- Hub correction on the scale store: right note first 67 -> 76 of 100; end to end +1 point. Lowering the bar to 0.58 answers 70 vs 66 but gives a note to 46 vs 25 of 86 noise prompts — not done. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)
- Cost: 0 tokens when nothing matches; ~55 tokens per note shown; hook ~0.07 s per prompt warm; first prompt after idle ~1.5 s. — [CC](/Users/jacky/Documents/dore/.agents/rules/claude-code.md)

**Feedback (reactions)**
- After a question: the same question asked again (>= 0.80, not one-detail-changed) = −1 to the notes shown; moving on = +1; `/good` `/bad` = ±3 (local chat only). Ranking effect capped at 0.06 — "reorders close notes, can't lift unrelated ones". — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md), `react()` in [hooks.py](/Users/jacky/Documents/dore/src/integrations/hooks.py)
- Known limit: re-ask detection misses big rewordings ("What is my job?" / "What do I do for work?" 0.79). — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)

### Inferences
- In human-memory terms, dore implements a careful episodic/semantic fact store with gated encoding, interference handling (replacement), source monitoring (trust/source labels) and reconsolidation-on-correction; it does not implement schema formation, skill/procedural memory, or usage-driven strengthening/decay beyond a ±0.06 ranking nudge.
- "Repetition makes it stick" (requirement/rule-core verification on repeat) is the only spaced-repetition-like mechanism, and it depends on near-verbatim repetition (>= 0.85), which real users mostly don't produce (0.74–0.81 for the same rule reworded, per RPT Round 5).

### Gaps
- I did not inspect `src/learn/grammar.py` (417 lines) and `statements.py` line by line; descriptions of the gate come from the rule file, which the project keeps in sync by policy.
- No measurement exists of how much `feedback` actually changes which note is shown in real use.

## 2. Measured results (numbers exactly as measured)

### Takeaway
On synthetic and real data, encoding is now clean (HELDOUT 38/41 facts, 0/39 junk) and updates are handled (28/28), but retrieval of rephrased questions is the ceiling (5/8), weekly correctness in the 4-week stream drops from 24/30 to 22/30 as facts change, and over 6 simulated months correctness sits flat at ~70%. On real use, only ~14 of 52 stored facts were clean and useful and dore covered 3 of 13 real repeated instructions.

### Cited Findings

**Checks I ran today (2026-11-25, this session, no LLM)**

`python -m dore.eval.stream` (default seed 7) [run 2026-11-25]:

| Week | Correct | Stale shown | Other-project leak |
|---|---|---|---|
| 1 | 24/30 | 0/0 | 0 |
| 2 | 24/30 | 0/2 | 0 |
| 3 | 23/30 | 2/10 | 0 |
| 4 | 22/30 | 3/11 | 0 |

| Measure | Value |
|---|---|
| Messages (facts) | 496 (29) |
| Repeat mistakes (missed 2 weeks in a row) | 16 |
| Junk: noise messages stored | 14 (8 notes) |
| Missed: fact messages not stored | 0 |
| Notes stored per normal session | 1.5 |
| Notes stored in the long session | 1 |
| Tokens added per work prompt | ~5 |
| Long session: tokens per prompt, first 50 / last 50 | ~3 / ~0 |
| Store size (searchable) | 36 (33) |
| Hook time per prompt, median / p95 | 9 / 20 ms |
| Run time | 6.6 s |

Misses were dominated by two rephrased questions every week in all three projects ("How long should your answers be?" want short; "Which editor do I use?" want Neovim/Helix), plus "What port does the dev server use?" (3001) in weeks 3–4 and "Where does this project deploy to?" (Cloudflare) in week 4. Only junk listed: "hmm that's not right, the test still fails". — [run 2026-11-25], [src/eval/stream.py](/Users/jacky/Documents/dore/src/eval/stream.py)

`python -m dore.eval.learning` [run 2026-11-25]:

| Set | Facts learned, right scope | Facts learned | Junk stored |
|---|---|---|---|
| DEV | 43/47 | 45/47 | 2/70 |
| HELDOUT | 38/41 | 39/41 | 0/39 |

| Check | Result |
|---|---|
| Updates (replace or keep both, right) | 28/28 |
| Retrieval (note shown for a rephrased question) | 5/8 |

Listed failures: DEV wrong scope "i dont like long explanations, keep it simple" and "i alway write test with jest" (stored as project, should be general); DEV junk "hmm that's not right, the test still fails", "10 PM now are 22"; DEV missed Khmer "ខ្ញុំរស់នៅភ្នំពេញ" and "we self-host sentry, so please check the dsn"; HELDOUT missed "Call me Sok." and "I'm colorblind, so please don't rely on red vs green."; HELDOUT wrong scope "our server located in singapore region" (went general). Retrieval misses: "How long should your answers be?" vs "I prefer short answers without emojis."; "What is my job?" vs "I work as a nurse at Calmette Hospital."; "What baud rate should I use to flash?" vs "Firmware is flashed over UART at 115200 baud." — [run 2026-11-25], [src/eval/learning.py](/Users/jacky/Documents/dore/src/eval/learning.py)

`python -m dore.eval.conversation` [run 2026-11-25]:

| Check | Correct | Old value shown | Tokens/question | Time |
|---|---|---|---|---|
| short (7 questions) | 5/7 | 0/3 | ~73 | 1.2 s |
| long (80 questions) | 80/80 | 0/53 | ~51 | 7.5 s |

Short misses: "Which test framework should I use?", "What database do we use?". — [run 2026-11-25], [src/eval/conversation.py](/Users/jacky/Documents/dore/src/eval/conversation.py)

**Baselines recorded in the repo (2026-11-25)**
- Stream seeds 1–5 mean (after reworded-update fix): correct per week 26.0, 26.2, 24.0, 23.4 /30; stale 0, 0.2, 2.4, 3.2; leaks 0; repeat mistakes 13.4; junk 10.8 of ~467; missed 0 of 29; 3.7 tokens per work prompt. — [TEST](/Users/jacky/Documents/dore/.agents/rules/testing.md)
- Stream seed 7 baseline: 24, 24, 23, 22 /30; stale 0, 1/2, 3/10, 4/11; junk 14 (8 notes). My run today matched correct and junk exactly and was slightly better on stale (0/2, 2/10, 3/11). — [TEST](/Users/jacky/Documents/dore/.agents/rules/testing.md); [run 2026-11-25]
- Learning baseline in TEST lists DEV 39/43, 2/66; today's DEV set is larger (47 facts, 70 junk cases) so DEV numbers are not directly comparable; HELDOUT is unchanged at 38/41, 0/39. — [TEST](/Users/jacky/Documents/dore/.agents/rules/testing.md); [run 2026-11-25]
- Scale, 12 projects × 24 weeks (8,640 prompts, 112 facts): correct 77% (44/57) at week 4, 72% week 8, 71% week 12, 70% week 16, 69% week 20, 70% week 24; stale shown 0/1 -> 5/12 by week 24; leak ≤1; searchable notes 81 -> 286; junk 195 noise messages; missed 3 facts; ~33 tokens per question; hook 10 ms median, 19 ms p95. — [SCALE](/Users/jacky/Documents/dore/reports/learning-2026-11-25/data/scale-after-hub-correction.txt) (this file predates the reworded-update fix; TEST/ML report stale week 24 improved 5/12 -> 2/12 and correct 72% after it — [TEST](/Users/jacky/Documents/dore/.agents/rules/testing.md), [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md) Round 2)
- Scale run: questions with no answer still get loosely related notes ("bench scale: 0/100 empty"). — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)
- Long conversation (20 sessions, ~600 messages, 53 facts changed 1–3 times, 80 questions): 80/80 correct, 0/53 old value shown, ~46 tokens/question (before fixes 68/80). — [LONG](/Users/jacky/Documents/dore/reports/long-conversation/README.md)

**Before/after of the grammar gate (rules at session start -> after)**

| Set | Facts learned right scope | Junk stored |
|---|---|---|
| DEV | 30/42 -> 39/43 | 24/51 -> 2/66 |
| HELDOUT | 32/41 -> 38/41 | 18/39 -> 0/39 |
| Real sample 1 | 0/2 -> 0/2 | 18/119 -> 2/119 |
| Real fresh sample | 1/3 -> 3/3 | 27/118 -> 5/118 |
| Updates | 7/14 -> 19/19 | |
| Rephrased question finds its note | 4/8 -> 5/8 | |

— [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md). Note: CLAUDE.md and ML say fresh real junk 7/118; RPT and TEST say 5/118 — the repo is inconsistent on this number. TEST also warns both real samples have now been used for error analysis, so a new labelled sample is needed for an unbiased number. — [CLAUDE](/Users/jacky/Documents/dore/CLAUDE.md), [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md), [TEST](/Users/jacky/Documents/dore/.agents/rules/testing.md)

**Real-replay numbers (user's own prompts, private)**
- All 1,033 real prompts, 14 projects: notes stored 70 -> 46 (final), tokens added 12.4 -> 7.9 per prompt, hook 18 ms median. — [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md)
- After "don't" instructions + promotion: replay 46 -> 52 notes, ~8.3 tokens per prompt. — [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md) Round 3
- Real repeat test: 13 of 108 lasting instructions/facts the user had to say again in a later session; Claude Code's own auto-memory covered 0 of 13; dore covered 3 of 13 (device and Khmer-font facts). — [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md) Round 3
- Round 5 audit of all 1,057 real prompts: 233 not typed; 342 short with nothing kept; 203 long with nothing kept (mostly questions); ~48 kept as facts (52 notes); 141 kept as hidden requirement gists (28 cut at 240 chars). Of 52 facts, ~14 clean and useful, ~25 broken fragments of run-on sentences. Only 4 of 141 requirements ever became visible. The same lasting rule reworded scores 0.74–0.81, below the 0.85 repeat bar, so it is never shown. — [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md) Round 5
- Round 5 explicit conclusion: "rules judge one sentence at a time; this user's lasting preferences come inside questions and requests and in long run-on sentences. Rules have reached their ceiling here; telling a lasting rule from a one-off task needs understanding of the session." — [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md)
- Round 6: dropping broken pieces removed 8 broken facts, 0 good lost; rule cores: 34 kept hidden, 2 verified, both true; tokens per prompt 10.1 -> 10.7; hook median ~21–26 ms. — [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md)
- Claude Code's own auto-memory (comparison baseline): 51 notes in 11 of 16 project folders; detail files rarely opened (2 in 32 sessions of one project, 0 in 21 + 19 of two others); stale references (3 of 5, 2 of 2, 8 of 140 in three projects). — [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md) Round 3

**Experiments measured and not adopted**
- `bge-base-en-v1.5`: answered 73 vs 65 of 100 at equal noise; end to end +1 to +3 points (76 -> 79% at week 12) for hook 10 -> 23 ms median; not adopted. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md), [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md)
- Meaning-only fact classifier (embedding centroid/kNN): HELDOUT 28/39 facts with 4 junk; real 16/92 junk — rejected for grammar. — [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md)
- Learning from failed-then-fixed shell commands: 117 real sessions -> 2 lessons, both junk. — [CLAUDE](/Users/jacky/Documents/dore/CLAUDE.md), [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md)

### Inferences
- The flat ~70% over 24 simulated weeks shows dore does not degrade as memory grows (no interference collapse), but also does not improve with use: there is no mechanism by which more exposure raises retrieval accuracy.
- The gap between synthetic (HELDOUT 38/41, conversation long 80/80) and real use (~14 of 52 stored facts clean; 3/13 repeats covered) suggests the synthetic suites over-represent clean declarative sentences relative to how this user actually expresses lasting knowledge.
- All measurements are from one machine and one user over two days of development; none is a longitudinal real-world measurement over weeks.

### Gaps
- No real-use measurement over calendar time (weeks/months) exists; "over time" numbers are simulated (stream: 4 weeks; scale: 24 weeks).
- I did not run `dore.eval.scale` (~95 s) or `stream seeds 5` myself; those numbers are from repo files.
- No measure of end-task outcome (did Claude do the task better because of a shown note) exists.

## 3. Roadmap: what is planned and not done

### Takeaway
Of six roadmap steps, step 1 (clean learning/updates) is "mostly done"; step 2 (learn from Claude's side) was measured and not adopted; steps 3–6 (forgetting score/decay, project->general promotion of facts, likely-question keys + profile card + reranker, multilingual) are open.

### Cited Findings
- Step 1 mostly done: real replay 70 -> 46 notes, every real fact kept. Left: reworded updates keep both notes (stale 7/11 weeks 3–4, as stated in CLAUDE.md — older figure; TEST baseline after the fix is 2.4/3.2 mean over seeds 1–5) and rephrased questions miss (retrieval 5/8). — [CLAUDE](/Users/jacky/Documents/dore/CLAUDE.md), [TEST](/Users/jacky/Documents/dore/.agents/rules/testing.md)
- Step 2 learn from Claude's side at SessionEnd: "failed shell command then a similar one that worked" gave 2 lessons, both junk (145 of 186 real failures are long multi-step commands); not adopted. Next signal to measure: the user accepting a proposal ("yes, keep that"). — [CLAUDE](/Users/jacky/Documents/dore/CLAUDE.md)
- Step 3 forgetting: first part done (recheck). Left: score (use + recency + trust), decay, archive (never delete; protected exempt), merge similar notes; idle time. — [CLAUDE](/Users/jacky/Documents/dore/CLAUDE.md)
- Step 4 project -> general promotion: a fact seen/helpful in 2+ projects becomes general; one project's names/paths/IDs never go general; identify a project by git root, not folder name. Today only value-free habits are promoted; organisation facts said without "our" stay in one project; two folders with the same name are not told apart. — [CLAUDE](/Users/jacky/Documents/dore/CLAUDE.md), [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)
- Step 5 retrieval: likely-question keys per note (biggest remaining miss "How long should your answers be?" vs "I prefer short answers"), then fact slots + profile card (once per session), small reranker. — [CLAUDE](/Users/jacky/Documents/dore/CLAUDE.md)
- Step 6 other languages: multilingual parser + embedder; Khmer is neither learned nor found today (confirmed by today's learning run: Khmer DEV case missed). — [CLAUDE](/Users/jacky/Documents/dore/CLAUDE.md); [run 2026-11-25]
- Also suggested but not on the numbered roadmap: an LLM consolidation step for hidden requirement gists ("a small Haiku call per project, measured cost first"). — [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md) Round 4
- REFERENCES.md still describes "nightly or idle-time training of the core", LoRA "Phase 5" and "exams with automatic rollback" as part of dore's combination, though CLAUDE.md says model training was dropped. — [REF](/Users/jacky/Documents/dore/REFERENCES.md); [CLAUDE](/Users/jacky/Documents/dore/CLAUDE.md)
- Other open weaknesses listed: duplicate check is a flat O(n) search (440 items/s for 100k bulk loads); some parser misreads lose a fact ("Call me Sok."). — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)

### Inferences
- REFERENCES.md's "Consolidation ('sleep')" and "Replay of old data" rows (Nested Learning, Letta sleep-time compute, EWC) describe inspirations whose dore implementations do not exist now; a report comparing dore to sleep-time/consolidation systems should treat these as aspirational, not features.

### Gaps
- No timeline or effort estimates exist for steps 3–6.

## 4. Human-like abilities absent entirely (or present only in a minimal form)

### Takeaway
On the Claude Code path dore has no abstraction into higher-level knowledge, no procedural/skill learning, no metacognition or abstention, no learning from task outcomes, and no temporal reasoning over history, even though the schema keeps the history (`valid_to`, `replaced_by`) that temporal reasoning would need.

### Cited Findings
- **Consolidation / abstraction**: none beyond exact-content-word habit promotion across projects and repeat-based verification. The repo states rules "can't tell a lasting principle from a one-off long task" and that turning gists into short rules "needs understanding". — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md), [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md)
- **Procedures/skills from successful work**: only in dore's own local chat — `Agent.solve_code` stores a `kind="lesson"` ("Task… Working solution… Mistakes fixed on the way") with `source="checker"` after code passes a real test. The Claude Code hooks never read tool calls or outcomes; the shell-failure-then-fix experiment yielded 2 junk lessons from 117 sessions. — [agent.py](/Users/jacky/Documents/dore/src/assistant/agent.py) lines ~244–275; [CC](/Users/jacky/Documents/dore/.agents/rules/claude-code.md); [CLAUDE](/Users/jacky/Documents/dore/CLAUDE.md)
- **Metacognition / abstention**: the hook stays silent below 0.65 (so "nothing relevant -> nothing added"), but there is no notion of "I don't know this" signalled to Claude; in the scale test, questions with no stored answer still got loosely related notes (0/100 empty). A `NO_GUESS` instruction ("If no note above answers this, say you don't know.") exists only for the local 1B chat (54/56 vs 42/56 without). — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md), [agent.py](/Users/jacky/Documents/dore/src/assistant/agent.py)
- **Learning from outcomes**: the only outcome signal is the user's next prompt (re-ask = −1, move on = +1, correction = mark wrong), capped at 0.06 of rank; test results, build success, or the user accepting a proposal are not used on the Claude Code path. "User accepting a proposal" is named as the next signal to measure. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md), [CLAUDE](/Users/jacky/Documents/dore/CLAUDE.md)
- **Usage-based strengthening/decay**: `times_used`/`last_used` are written on search but never read by any scoring or forgetting code; recency enters ranking only as `0.03×exp(−age_days/30)` on created/last_seen. — [store.py](/Users/jacky/Documents/dore/src/memory/store.py)
- **Temporal reasoning over history**: replaced notes keep `replaced_by`/`valid_to`, but search excludes them (`SEARCHABLE_SQL … replaced_by IS NULL`) and no code path answers "what did we use before?" or "when did this change?"; `replaced_by` is read only by the searchable filter, recheck and an eval. Dates are shown as labels on notes. — [types.py](/Users/jacky/Documents/dore/src/memory/types.py), [store.py](/Users/jacky/Documents/dore/src/memory/store.py), [hooks.py](/Users/jacky/Documents/dore/src/integrations/hooks.py)
- **Understanding the session as a whole**: rules judge one sentence at a time; lasting preferences embedded in questions/requests are lost (e.g. "must work for everybody" dropped because it was said as a question-like sentence). — [RPT](/Users/jacky/Documents/dore/reports/learning-2026-11-25/README.md) Round 5
- **Associative / paraphrase recall**: the embedder is "the retrieval ceiling"; rephrased personal questions score ~0.51–0.61 vs the 0.65 bar. — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)
- **Multilingual**: English only (bge-small-en, spaCy en). — [ML](/Users/jacky/Documents/dore/.agents/rules/memory-learning.md)

### Inferences
- What dore has that maps to human memory: selective encoding (attention gate), interference resolution (newer replaces older, old kept = no true erasure), source monitoring (trust/source/date), reconsolidation on correction, repetition-driven strengthening for rules, and context-dependent recall (project scope). What is missing maps to semantic consolidation (schemas/gist), procedural memory, metamemory (feeling-of-knowing), reward-driven learning, and episodic time-travel.
- Because all learning is per-sentence rules, dore's quality is bounded by how much lasting knowledge users express as clean declarative sentences; the real audit suggests that for this user that is a minority (≈14 useful facts from 1,057 prompts).
- The project's own measurements point to an LLM-based session-level step (consolidation) as the lever with the most headroom, which conflicts with the "~0 Claude tokens" design goal; this trade-off is unmeasured.

### Gaps
- No measurement exists of how often a shown note changed Claude's behaviour or outcome.
- No evaluation of temporal questions ("what was the port before?") exists in any eval suite I saw.
- No measured cost for the proposed per-project Haiku consolidation call.
