# Long text as groups (plan, 2026-11-27)

A long message (a typed list, a pasted table, a document, a log) is learned as one **group**: a title, a short
summary and one note per item. A later prompt gets only the title, the summary and the matching item; Claude asks
for the rest when it needs it. Haiku decides what is worth keeping, code and logs included.

## Measured before (2026-11-27, made-up lists, real hook path)

| | Result |
|---|---|
| Word rules, message of 3+ lines (bullets, one person per line) | 0 notes, 0 raw sentences: 0/10 recalled |
| Word rules, one paragraph of 21+ facts, or over 3,000 chars | 0 notes: everything lost |
| Word rules, one paragraph of ≤20 facts | 20/20 saved and recalled |
| "List all my friends" after 20 were saved | 0 notes shown (max 3 notes, 600 chars) |
| Haiku queue | first 20 lines only; over 3,000 chars nothing; a 50-line list split over batches of 30 |
| Haiku verdicts (one real batch, 29 lines, 3.8k tokens, $0.0013, 9 s) | noise skipped 17/19 (traceback, npm log, code, one-time task, article); lasting facts kept 8/8; kept 2 lines of a one-time build-failure story |
| Haiku, line by line | lead lines ("Here are my friends:", "these are my team members") skipped, so the notes lose who the people are; no title, no group |
| Shape filter before Haiku | let 10 of 11 traceback/npm/code lines through anyway |

## Design

1. **Queue whole messages** (prompt hook, ~0.1 ms, 0 tokens). No 3,000-char or 20-line cut. In the session Claude
   already has the text, so nothing is shown back.
2. **No shape filter before Haiku**: code and logs can hold a lasting fact, so Haiku judges every block. Long blocks
   are trimmed to their start and end, repeated lines sent once; the daily token cap stays.
3. **Haiku judges a message as one item**: `skip` (logs, one-time tasks and events, text read once) or `group`:
   title + short summary + one note per item. Never keep passwords, keys or tokens. A short message stays as today.
4. **Haiku off**: the same group by shape (the user's lead line is the title, each line an item, no summary), on
   trial; a paste without the user's own words is `unverified`.
5. **Next session**: title + summary + the matching item + "+N more" (~30 tokens, estimate); nothing when no note
   matches.
6. **`dore-hook recall <id>`**: all items of a group, only when Claude runs it (0 tokens until then; no MCP tool).

Data model: a group note (title + summary) and item notes linked to it; items are searchable one by one; newer wins
per item; a group never overrules the user's verified facts; junk is deleted once Haiku judged it (`MemoryStore.forget_noise`).

## Measure

New check of lists (10/20/50 people as bullets, one per line, a paragraph, a pasted table) and a noise set
(tracebacks, logs, code, one-time tasks, articles, a log with one lasting fact, a block with a secret). Haiku answers
recorded (`judge.Recorded`) so reruns cost 0 tokens. Plus `bench stream`, tokens per prompt, hook ms.

## Steps (one at a time, each measured)

- S1 queue whole messages; Haiku gets a message as one item, with trimming.
- S2 Haiku `group` verdict: title, summary, items; secrets skipped.
- S3 groups by shape when Haiku is off.
- S4 show title + summary + matching item + "+N more".
- S5 `dore-hook recall <id>`.

## Status (2026-11-27)

Built S1–S5 with the review fixes: no trimming that loses entries (Haiku sees a sample, entries are stored from every
line); Haiku off makes groups only from typed lists under a lead line; typed lists are known at once (provisional
when Haiku is on); facts and rules taken out of a paste are `unverified`; a title is shown only with entries left;
block answers may also be rules. Measured: [memory-learning](../rules/memory-learning.md) "Long messages as groups".
Left: an updated list replacing the old one as a whole (today newer entries replace older ones one by one); secret
scrubbing without Haiku (`detect-secrets`, to measure); a trimmed copy of skipped raw blocks; "+N more" relies on
Claude running a shell command (measure how often it does in real sessions).
