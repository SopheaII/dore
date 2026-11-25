---
name: learning-change
description: Procedure for changing what dore learns, merges, replaces, demotes or retrieves (src/memory/rules.py, store.py, src/learn/statements.py). Use before editing those rules.
---

# Learning change

A learning rule must fix the class of bug, not the example that showed it, and work for any user's
wording (typos, non-native English, terse, polite), not one person's words.

- **Decide by shape, grammar or meaning, not by lists of topic or action words.** Allowed: closed
  grammatical classes (pronouns, modals, question words, prepositions, want/think/look verbs,
  always/never) and concrete-detail checks (`learn/grammar.py`). Not allowed: growing lists of verbs,
  nouns or phrases ("use", "deploy", "looks good, now…").

1. **Reproduce** the wrong result with a real message sequence through the hook
   (`hooks.on_prompt` or `python -m dore.eval.conversation`); name the rule at `file:line`.
2. **List 3+ other messages that fail the same way, and 3+ look-alikes that must not change**
   (e.g. `I have a dog Buddy` + `Max` keeps both; `My car is red` is not `bought in 2020`;
   a different subject is not an update). Measured limits: [memory-learning](../../rules/memory-learning.md).
3. **When unsure, keep both notes.** Hiding a true fact is worse than showing an extra one.
4. **Add the failing pattern to DEV in `src/eval/cases.py` in your own wording**, then fix; judge
   on HELDOUT and the fresh real sample (`python -m dore.eval.learning --real`), which you never tune on.
   **Unit-test both lists with new sentences.** HashEmbedder can't score meaning: test the rule
   function directly, and rely on step 5 for real similarity.
5. **Run** `.venv/bin/pytest -q`, `python -m dore.eval.conversation`, `python -m dore.eval.learning`
   and `python -m dore.eval.stream seeds 5`; stay at or above the baseline in [testing](../../rules/testing.md).
6. If the old rule could already have hidden notes, check `data/memory.db` read-only
   (`file:data/memory.db?mode=ro`) and report; change nothing.
7. Add the new rule and its numbers to `memory-learning.md` in one or two lines.
