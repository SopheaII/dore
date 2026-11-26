# Memory consolidation with Haiku (built 2026-11-26, opt-in; measurements in rules/memory-learning.md)

Goal: learn facts and rules like a person (keep everything, strengthen what is repeated and used, recall only on a
cue), with less code, fewer Claude tokens, and a model only for the hard part, rarely.

## Why change

Review of the current design (2026-11-26, read and run, not assumed):

| Problem | Evidence |
|---|---|
| Learning policy lives in the Claude Code adapter | `integrations/hooks.py`: 43 functions; other adapters import its private helpers; 7 raw SQL writes bypass the store |
| No single "same note?" | ~10 checks with different bars (0.95 + same words, 0.85 x3, 0.72, 0.7, 0.6, exact text in 10 min, lower/trim) |
| No single "how sure?" | 9 columns (trust, times_seen, uses, tries, times_used, feedback, archived, protected, rule), 3 meanings of "proven" |
| Two language engines | ~70 word/regex lists in `memory/rules.py`, `learn/statements.py`, `learn/grammar.py`; ~20 hand-set similarity bars |
| Bugs (reproduced) | same sentence with "." vs "!" -> two notes (0.9487 < 0.95); a "don't" rule said in 2 sessions archived after 3 silent follows; one MCP search revives a faded rule (`last_used`); the previous answer is lost or cut in 142 of 689 real turns (meta events, `/model`, task notifications start a "turn") |
| Rules check leaks | its invented Claude replies contain the rule words the checks look for |

## Design: three memories, one model call per session at most

| Memory (like a brain) | What it holds | When written | Tokens |
|---|---|---|---|
| Raw memory (`episodes`) | every sentence the user typed, forever | every prompt, local | 0 |
| Notes (facts and rules) | short consolidated notes, with history (replaced notes kept) | consolidation | Haiku, batched |
| Strength | said / used counts and dates per note (ACT-R, `memory.activation`) | every prompt, local | 0 |

Recall is by cue only: each prompt searches notes (meaning + keywords) and adds the few strong matches (<= 600
chars); standing rules come to mind once per session within the rules budget (600 chars) by strength. Nothing is
loaded whole; nothing is deleted; a faded note is still found when a prompt matches it.

### Easy cases: local, free, every prompt

- Exact repeat (same words in order, any case/punctuation): +1 said, no model. A stored, indexed `same_words` key
  replaces the nearest-neighbour + 0.95 check (bug 1) and the three other "same words" checks.
- Shape filter for what can be a note (shape only, no topic words): typed by the user (not pasted, not Claude's
  text echoed back), not a question, 3-40 words, not code or a log. Everything else stays in raw memory only.
- Use and practice: Claude's reply and actions vs the note (word rarity, as `use_check` today); a rule's
  "look for" / "must not" words are stored when the rule is made, so no parser at prompt time.

### Hard cases: Haiku, batched, rarely

A sentence that passed the shape filter and is not an exact repeat goes to a queue (the raw-memory row,
`judged=''`). The queue is judged in one call:

- When: not tied to SessionEnd. Closing the terminal (SIGHUP) may skip or cut SessionEnd, so it is only a bonus.
  The queue is in the memory file (raw memory is saved at every prompt), and any of these runs the batch when
  it is due: the warm helper while idle (it runs in its own session with no terminal, so closing the terminal does
  not stop it; idle work starts 20 s after the last prompt, it exits after 30 min), SessionEnd if it runs, or the
  next session's first prompt (spawned detached, the prompt is not delayed). A lock lets only one run at a time.
- Due = the queue holds >= 10 sentences, or its oldest sentence is >= 1 day old. Small queues wait and merge,
  so the fixed part of a call is paid rarely (real logs: ~3 sessions a day, median 4 typed messages each -> about
  one call a day, estimate). A note is not needed in the session it was said in: Claude has that chat.
- Input per sentence: the sentence + its 3 closest notes (FAISS, this project + general) + the notes shown in that
  session (so a correction sees what it corrects).
- Output per sentence (compact JSON): `skip` | `new {text, form: fact|rule, about: user|project}` |
  `same #id` (a reworded repeat: +1 said) | `updates #id` (old note kept, marked replaced) | `wrong #id`.
- Checks on the answer (local): ids must come from that sentence's shortlist; every name and number in a new note
  must appear in the user's sentence (no invented facts); unparsable answer -> the sentence stays queued.
- Each sentence is judged once (verdict stored); no re-judging all memory when code changes.
- Daily token cap; over it, the queue waits. Offline or rate-limited: the queue waits. Nothing is lost.
- Few tokens by design: a short fixed prompt (~300 tokens); one line in per sentence (`7 <text>`) and one line out
  (`7 same 41`), no JSON keys; neighbours only above a similarity bar (most sentences have none), at most 3;
  exact repeats never sent. Estimate for a batch of 10: ~0.9k tokens in, ~0.1k out, plus Claude Code's per-call
  overhead (measured in step 2; if it is large, the batch size goes up, not the number of calls).

### Limits, size and retries

- Input is only what the user typed (`hooks.typed_text`), never Claude's replies, tool output, pasted blocks or
  logs, plus the few close notes. A sentence over 40 words is not sent (a task or a paste; it stays in raw memory).
- Size: one batch is at most 30 sentences and ~6,000 characters (~1.5k tokens), far below Haiku's context. A
  bigger queue is split, one batch per run, so a backlog never becomes one big call. Haiku's answer is one short
  line per sentence; a cut or unreadable answer keeps the lines that parsed, the rest stay queued.
- Failure (no network, `claude` missing or logged out, rate or usage limit, overloaded): nothing is marked judged;
  the next try waits 30 min, then 1 h, 2 h, 4 h, up to 24 h (or until the reset time if the error gives one); a
  success resets the wait. One try at a time (lock), so no retry storm, and dore backs off at once when the user's
  plan is at its limit instead of using what is left of it. dore's own daily token cap (from the usage the call
  reports) stops it before that.

How it calls Haiku: `claude -p --model haiku --system-prompt <dore's prompt> --tools "" --strict-mcp-config
--no-session-persistence --output-format json`, with an env flag so dore's own hooks ignore that session
(recursion). `--bare` needs an API key (subscription login is not read), so it is not the default. Backends behind
one `Judge` interface: Claude CLI (default), API key if set, recorded answers (tests, 0 tokens), none (queue only).

### Rules: intent kept, noise fades

- Haiku tells a standing rule ("from now on", "always", "never", "in this repo") from a one-off request, a
  complaint or chatter, reading the batch together. A clear standing rule comes to mind from the next session on
  (no need to say it twice); an unclear one waits for a repeat or for Claude to use it.
- For each rule Haiku also gives its situation words and its forbidden words ("never push straight to main":
  situation `git push`, forbidden `main`). Practice = Claude acts in that situation without the forbidden part, so a
  "never" rule that is being followed stays strong (today "doing nothing leaves no trace" and it fades).
- Fading only moves a rule from "every session start" to "when a message or Claude's work matches it"; it is
  never deleted. A rule ends only when the user changes it (`updates #id`).
- Noise that slips through costs little: it is never repeated or practised, so it fades from session starts and
  is only shown on a strong match.

### Notes model (one way to say "how sure")

`status` (note | replaced | wrong), `form` (fact | rule), `trust` (user | agent), `said` (count, sessions, first,
last), `used` (count, last). Strength = f(said + used, first, last). Search hits do not add strength (bug 3).
Replaces: on_trial, tries, times_used, feedback, rule, the requirement / rule-core kinds. Migration adds and copies
columns; it never drops data.

### What goes away (estimate)

`learn/statements.py`, most of `learn/grammar.py` (and the 56 MB spaCy model, ~1.5 s cold start), the update and
frame rules in `memory/rules.py`, the request / rule-core / promotion / re-judging code in `hooks.py`,
`learn/recheck.py`: ~1,500 lines, ~60 of ~70 word lists, ~12 of ~20 bars. `hooks.py` becomes an adapter only; the
learning loop moves to `learn/consolidate.py`. One session-log reader (a turn starts only at a typed message).

## Cost (estimates until step 2 measures them)

| | Today | Plan |
|---|---|---|
| Claude tokens per work prompt | ~0.3-0.4 | same (recall unchanged) |
| Prompt hook | 6-7 ms median | same or less (no parser) |
| Model calls | 0 | when >= 10 new sentences or 1 day old: about 1 a day on the real logs |
| Haiku tokens per call | - | ~0.9k in + ~0.1k out for 10 sentences, plus Claude Code's own per-call overhead (unknown, step 2) |

README changes from "~0 Claude tokens" to "~0 tokens while you work; one small Haiku call at the end of a session
when there is something new to learn".

## Steps (one at a time, each measured)

1. Fix what holds in any design: one session-log reader (bug 4), search hits add no strength (bug 3), rules check
   without leaked replies. Measure: real-log turns read right, rules check honest numbers.
2. `Judge` interface + one real Haiku call with dore's hooks off and a temporary memory: tokens, latency, errors.
   Go / no-go on cost.
3. Consolidation on the real replay (local, `reports/`), against today's learner: junk notes, real facts kept,
   reworded repeats merged (labelled pairs), updates right, Haiku tokens per session. Go / no-go on quality.
4. Switch learning to consolidation; one notes model (migration); delete the replaced code and lists.
5. README, `AGENTS.md` rule ("no new ready-made models" -> "Haiku only in batched consolidation"), roadmap.

## Terms (checked 2026-11-26, code.claude.com/docs/en/legal-and-compliance)

Allowed: "an end user ... signing in to the unmodified Claude Code binary with their own Claude subscription";
plan limits "assume ordinary, individual usage of Claude Code and the Agent SDK". Not allowed: third-party
tools offering Claude.ai login, routing requests through plan credentials "on behalf of their users", or
"collect, store, or intermediate Claude.ai credentials or session tokens". "Developers building products ...
including those using the Agent SDK, should use API key authentication". So dore only runs the user's own
unmodified `claude` command (never reads or copies a login token), at about one small call a day. Because dore
is also a published package, the Claude Code login is used only after the user says yes once (install asks:
Claude Code login / API key / off); an API key, when set, is preferred.

## Open decisions (defaults proposed)

- Clients without the `claude` command (opencode, other MCP clients): keep raw memory; a later Claude Code session
  (or an API key) consolidates it. Alternative: keep the old learner for them (keeps the lists).
- Batch size: 10 sentences or 1 day (default); bigger batches = fewer calls, slower learning.
