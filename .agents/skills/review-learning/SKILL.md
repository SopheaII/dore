---
name: review-learning
description: Read-only review axis for changes to learning, memory rules or retrieval. Finds facts that are lost, hidden, wrongly merged or wrongly trusted.
---

# Learning review

Review only the current diff. Inspect code, diffs and recorded checks; no file writes or runs.

For every changed rule, look for a concrete message sequence that:

1. hides a true fact (wrong replace, merge or demote), or keeps an outdated one searchable;
2. stores a request, question, paste or the assistant's own text as a verified fact;
3. lets an agent or unverified note overrule a user fact, or archives a protected note;
4. deletes anything that is not noise (a real note, a wrong note, an old value), or trains anything (hard rules);
5. crosses projects wrongly: a general note replacing a project's own note, or one project's
   names, paths or IDs stored as general (shown in every other project);
6. misses something it should learn: a plain fact, decision or correction the user stated that
   is no longer saved (learning that silently got stricter);
7. only works for the wording it was written for: a rule keyed on a list of content words, or a
   gain on DEV cases with none on HELDOUT;
8. grows without limit: a long session (hundreds of prompts) or Claude's own output adding many
   notes per session, or notes that can never be archived.

Report each finding as `file:line`, the messages in order, the wrong result, and the smallest
fix. A suspicion without a sequence is not a finding. A clean result is normal.
