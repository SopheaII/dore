# Plan: fewer junk notes from real messages (evidence over time)

Status (2026-11-26): **built** as notes on trial (Voyager-style), fully automatic and invisible to the user (user's choice; options A–C dropped). Details and numbers: `rules/memory-learning.md`, "Notes on trial". Roadmap step 3 in `AGENTS.md` points here. Comes before scope step S2.

## Why

Real memory (one user, quick non-native English): of 17 notes shown as verified, ~9 useful, ~6 junk (a question or
request saved as a fact, a passing event), 2 vague or outdated, 1 wrong scope. In one session the hook added 5
notes, 2 useful. The test sets say "chatter saved 0 of 39" because their sentences are clean English.

Checked 2026-11-26 on 16 paraphrased real sentences (6 junk, 10 facts), one sentence at a time:

| Judge | Junk caught | Facts lost |
|---|---|---|
| Today's grammar gate | 1 of 6 | 2 of 10 |
| Zero-shot NLI, `nli-deberta-v3-xsmall` (int8, ~10 ms) | 4 of 6 | 6 of 10 |
| Typos (spaCy out-of-vocabulary words) | 2 of 6 | 1 of 10 |

No judge of **one sentence at the moment it is typed** works on this kind of text, so a better rule or a
ready-made model there is not the fix (and no new AI models are used: the user's choice). The missing part is **evidence after the fact**: whether the note was any use.

## J0 baseline (done 2026-11-26)

Real sessions (26 sessions, 50 prompts got notes; labels kept locally in `reports/j0/`, never in the repo):

| Measure | Value |
|---|---|
| Note lines shown to Claude | 65: 32 useful, 33 junk or vague (~50%) |
| Prompts that got notes | 50: 28 with at least one useful note, 22 with only junk |
| Notes marked verified (active) | 19: 7 useful, 3 true but low value, 1 mixed, 1 vague, 7 junk |
| Raw sentences not stored | 53, nearly all requests: real facts are rarely missed; the problem is junk kept |
| Most shown junk | one complaint shown 8 times as "your repeated request"; one question shown 7 times |

Test sets: 18 new quick non-native cases (`eval/cases.py`, new wording): 8 of 13 chatter lines stored as notes,
5 of 5 facts learned. Learning check now DEV 55/59 right scope, junk 7/80; HELDOUT 40/43, 3/45.

## J1 findings (2026-11-26): Claude's reply is a weak judge

Replayed the 50 real prompts that got notes (47 with a reply), against the J0 labels. Nothing built.

| Check | Useful notes | Junk notes | Verdict |
|---|---|---|---|
| Reply repeats >= 1/3 of the note's words not in the prompt | used 13 / 29 | used 17 / 30 | no separation |
| Same, words weighted by rarity in this machine's 859 replies (IDF) | median 0.10 | median 0.25 | no separation |
| Rarity score >= 0.6 ("clearly used") | 6 / 29 | 0 / 30 | a reliable **good** sign only |
| Claude's reaction to the message the note came from (reply words, tools) | long replies, tools | long replies, tools | no separation (facts are said inside work messages) |

Why: most shown notes don't fit that prompt (a rule shown at session start is rarely relevant), so "not used"
says little; and in this project nearly every reply talks about memory, sessions and Claude. Archiving notes
Claude ignores would archive good rules. Small data too: 16 different notes shown in 26 sessions.

Options for the user (decision pending):
- **A. The user is the judge:** dore shows the user what it saved (one short line) and "forget that" archives it.
  ⚠️ Needs a check that such a line can reach the user without entering Claude's context (hook docs are unclear).
- **B. Safe automatic part only:** a note Claude clearly used is protected; nothing archived automatically.
- **C. Wait for more data** and measure again.

## Design

1. **Claude is the checker (0 tokens).** When the hook shows a note, the next prompt's hook already reads Claude's
   reply (`hooks.assistant_text`, used for echo). If the reply uses the note (its value: names, numbers, the
   topic key's words), that's a *use*; if not, a *miss*. Per note: `times_shown`, `times_used`.
2. **The user is a checker too (exists):** a re-ask after a note (-), a "No, ..." correction (wrong), the same
   sentence again in another session (+, roadmap step 3 "Next").
3. **Score and archive** (roadmap step 3 "Left", idle consolidation): use + repeats + recency + trust. A note
   shown several times and never used is archived (kept in SQLite, never deleted; protected notes exempt).
   A note never matched by any question for weeks decays.
4. **New notes start unproven.** Shown on a strong match as today, but the first misses count most; a note
   used once is safe.
5. **Vague subjects** ("his/her/their/it ..." with nothing in the message it points to) stay raw memory, not a
   note: the note can't be understood alone (grammar, closed class).
6. **Hidden requirements** follow the same score: a request repeated in another session is shown, then kept only
   if Claude uses it.

Not chosen: Claude or Haiku judging at SessionEnd (tokens, the user doesn't want them); training a classifier (no
training rule; an exemplar judge on embeddings was tried and added junk).

## Speed (estimates)

| Part | Cost |
|---|---|
| Use check | <1 ms on the next prompt: the reply is already read; a set check per shown note (<= 6) |
| Scores, archive | idle consolidation, 0 on the prompt path |
| Schema | two counters on `memories` |

## Steps (one at a time, measured)

| Step | Builds | Measure |
|---|---|---|
| **J0** ✅ | Baseline: label real notes and raw sentences locally (`reports/`, git-ignored, never in the repo); add synthetic non-native DEV/HELDOUT cases (no personal data) | shown-note precision per session (today ~2/5); junk among verified notes (~6/17) |
| **J1** | Use check from Claude's reply (counters only, nothing archived yet). Replay real transcripts first: does "used" match the labels? | agreement with labels on real sessions |
| **J2** | Score + archive in consolidation; re-judge existing notes (`learn.recheck` exists) | junk among shown notes down; real facts lost = 0; `bench stream`, `bench scale` correct not down |
| **J3** | Vague subjects stay raw memory | DEV/HELDOUT |
| then | Scope S2 (`scope-redesign.md`) | — |
