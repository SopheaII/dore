# Memory learning rules

How learning, replacing, demoting and retrieval work, with measured limits. Procedure for changes: the `learning-change` skill.

## How it works (Claude Code hooks)

The default check is `python -m dore.eval.conversation`. The rules here apply to the Claude Code hooks and the bridge
for other agents. (dore's own chat with a local 1B model, its web page and the code checkers were removed on 2026-11-26:
the user uses dore only through coding agents. Their findings are in git history before that date.)

- **What a Claude Code prompt teaches** (`learn/statements.py: message_facts` -> `user_facts` -> `learn/grammar.py: fact_text`), decided by shape and grammar, not by lists of topic or action words (2026-11-25):
  - *Shape* (`structured_line`, any language): `<tag>…</tag>` blocks (pasted content, task notifications) are removed; a message of 3+ lines, or 2 lines with one shaped like output (bullets, indentation, stack frames, `file:line`, 2+ backtick spans, `k=v` pairs, columns, status symbols, many ALL-CAPS words, code symbols), is a paste: nothing stored.
  - *Grammar* (spaCy `en_core_web_md`, ~1 ms/sentence, 0.6 s load, preloaded by the warm helper): not facts = questions (question word, inverted auxiliary, "… or not"), commands (a base-form verb with no subject, any verb; "Always/never …" is a standing rule and is kept), fragments, a subject that is only it/this/that, "you …", I/we + wanting (want/need/would like) or cognition verbs (think/suspect/saw/mean/try…), possibility (may/might/could) or I/we + can/will, appearance verbs (look/seem) or "X is ADJ" with no concrete detail, a bare event with no object or detail ("the build passed"), an object that is only "it"/"this approach". A fact in a joined clause, a clause before a command, or a reason clause (since/because) is kept alone ("fix the worker since our queue is Kafka" -> "Our queue is Kafka").
  - *Concrete detail* (`grammar._detail`): a proper noun, number, identifier, path, or a word the model's vocabulary doesn't know ("vitest", "pnpm"; typos like "teh" are known). 3-word facts need one ("tests use vitest"). When the parse has no verb at all (md misreads "Our staging server runs on port 8443" as a noun phrase), the old word rules decide, and only with a detail.
  - *Added after replaying all 1,033 real prompts (2026-11-25)*: a polite sentence ("please", misspelt too: by spelling closeness) is a request; only a separate part before the marker, with a strong detail or starting with I/we/my/our, is kept ("we deploy with Ansible, so please check …"). "…, right" / "… or not" make a question (a "because …" clause inside can still be kept). Sentences that start with because/since/after/if… hang off something said before. Whole-sentence facts are at most 20 words (run-ons give up only a short clause, cut at but/so/because/"…"). Future will/would, I + any modal, I + misspelt want/think words (content words only: "with" is not "wish"), "I/we … it/this" without a strong detail, and shell or error lines (`&&`, `|`, "bash: x: not found", "·" separators) are not facts.
  - *Standing "don't" instructions* (`grammar.STANDING_DONT`): "please don't reformat existing code", "i don't want debug logs in commits", "do not touch the payment module" are lasting preferences, polite or not; not when tied to the moment ("right now", "yet", "this time") or pointing only at "it/this". Found by the real repeat test: the instructions users repeat across sessions are mostly of this kind.
  - *Long instructions -> hidden requirements* (`statements.requirement_text`, `hooks.save_requirement`): a 15+ word message with no short fact but with constraint grammar (not/never/keep/make sure/only/without/should…) keeps its gist (constraint sentences, no paths, <=240 chars) as `kind="requirement"`, `trust="unverified"`, project scope. **Not shown** until said again near-identically (>= 0.85, then verified and shown). Measured on all real sessions: showing them at 0.75 doubled tokens (8.3 -> 17.6 per prompt) and the "repeats" at 0.75 were mostly different requests about one screen; repeat-test coverage stayed 3/13. Stored hidden: 137 gists, ~10.1 tokens per prompt. Rules alone can't tell a lasting principle from a one-off long task: these gists are the raw material for a later consolidation step.
  - *Rules inside long requests* (`grammar.rule_cores`, `hooks.save_rule_cores`): every negated action-verb phrase with 2+ content words ("do not touch old code", "not invent new sentences") is kept as a short hidden note (`source="user-rule"`), also when the message held a fact. Said again in other words (>= 0.85, any project) it is verified and shown. Left out: questions, "right now" moments, thoughts with no object, judgements ("not look good", "are not valid"). Real sessions: 34 kept hidden, 2 verified, both true (true repeats 0.86-0.93, the next pair 0.77); ~10.7 tokens per prompt.
  - *Reports and questions are not rules* (2026-11-26, from real junk: short broken negations): a negation whose subject is a thing ("it not save on X", "the job does not run") is a report, unless a modal says how things should be ("the bot should never …"); "… or not" is a question tag; a rule whose object is only it/this/that points at the moment. A long message whose sentences ask ("should i add X or not", `grammar.asks`: auxiliary right before its subject) gives no hidden requirement.
  - *A repeat counts only from another session* (`hooks._seen_again`, state `saved`): a hidden note said again in the same session is still the task at hand (a one-off "please test …" said twice in one chat was shown as "your repeated request"); the same gist again within 10 minutes is one message handled twice (helper timeout + inline run, `_handled_just_now`). The prompt hook marks every message it handled (`handled`), so SessionEnd never counts it again.
  - *Broken pieces are dropped* (`grammar.complete`, `_inside_word`): a note must close its brackets and quotes, not end on a word that needs more ("is that", "... the parser i", "... has caching not"), and not cut a written word ("11:05"). Real replay: 8 broken notes gone, 0 good ones lost.
  - *A preposition at the end of a clause that describes a noun is whole* (2026-11-26; a real fact shaped like "rust is the language that i care most about" was dropped as a broken piece): `complete` accepts a final preposition (by its role `prep`: without a full stop "to" is tagged PART) with a relative clause above it ("the town I grew up in"); on the main verb it is still cut off ("I care about", "we should look into"). `about_user`: "I" in a clause describing the subject or its complement makes it the user's ("Rust is the language I enjoy working with" -> general). DEV 48 -> 52/56, HELDOUT 38/41 and junk unchanged; real replay +1 note (that fact).
  - *Claude's final replies are not learned* (measured 2026-11-25, 701 real turns): as facts they give 3,830 task-log lines ("Done — the new page is live"); they almost never restate the user's rule (best match 0.60-0.82, mostly "what I did"). Existing no-LLM tools (regex on replies for decisions/changes) are word lists with no measured results.
  - *Echo* (`hooks.not_echoed`): a sentence of 5+ words that Claude already wrote in this session (transcript tail) is not a new user fact, in any language.
  - Real replay (`all 1,033 prompts, 14 projects`): 70 -> 46 notes stored, tokens added 12.4 -> 7.9 per prompt, every real fact kept (checked by reading every stored note; details in the private report).
  - Without spaCy, the old word lists run unchanged (`QUESTION_START`, `IMPERATIVE`, `WANT`, `VAGUE`, `PLEASE`).
  - Measured (`python -m dore.eval.learning`): facts learned with the right scope DEV 39/42, HELDOUT 38/41 (word rules: 30/42, 32/41); junk DEV 1/51, HELDOUT 0/39 (word rules: 24/51, 18/39). Real prompts, fresh unseen sample: facts 3/3 (1/3), junk 5/118 (27/118).
- **Raw memory: nothing the user types is lost** (`memory/episodes.py`, table `episodes`, 2026-11-26). The rules decide once, at the prompt, and a sentence they drop was gone for good, so a rule fixed later could not bring it back. Like the hippocampus, every typed sentence that is not a note (`statements.episode_sentences`: same paste checks; questions left out) is kept as plain text on the prompt path (~1.9 ms, no embedding). `hooks.consolidate` (warm helper after 20 s idle in batches of 64, SessionEnd) gives episodes a vector, marks whether each one *tells* something (`grammar.tells`: a subject, no politeness marker, asks nothing) and its scope, and judges again every episode not judged with today's rules (`RULES_VERSION`, a hash of `learn/statements.py` + `grammar.py`): a fact a fixed rule now learns is saved dated when it was said (`add_many(created=)`; an older date never replaces a newer note, and a newer note it would have updated replaces it); words that are already a note in any state (archived, wrong, replaced) are never learned again. Past sessions: `python -m dore.integrations.backfill [--apply]` (dry run by default, lists the facts it would learn; skips sentences already kept for that session (per sentence, not per session: a session the hook joined halfway, keeps its first half) and sessions in temp folders or folders that are gone, i.e. test runs; only Claude's text *before* a message counts as echo: Claude quoting the user later hid a real fact in the first dry run). Real dry run (98 session logs, 2026-11-26): 43 facts not yet notes, ~20 real, ~20 junk (reports, a pasted error, requests): the gate's real precision on history. Real replay (1,036 prompts): 314 episodes, hook median 23 -> 24 ms, tokens unchanged.
  - *Recall on a cue, measured, off* (`EPISODE_STRONG = 1.01`): a question matching an episode from an earlier session. Real replay, all episodes at 0.75: a line on ~40 questions, nearly all old requests ("please build it again"); only telling episodes and real questions (`hooks._asks`; "please …" is not one) at 0.75: 11 questions, ~3 useful, ~8 noise (old requests), +0.4 tokens per prompt; 0.80: 1, noise. The embedder can't tell a lasting sentence from chatter.
  - *A meaning judge at write time, measured, not used*: kNN over bge-small vectors of the DEV labels ("is this a lasting fact?"): HELDOUT facts 11-27/41 vs the grammar gate's 39/41, real junk 9-47/237 vs 7/237, 0 facts rescued. Embeddings group sentences by topic, not by "lasting or for now".
  - Next (roadmap step 3): an episode that tells something, said again in another session, becomes a note (repetition, not similarity alone, decides).
- **A correction ("No, …" / "Actually, …" after notes were shown) marks wrong the used notes that conflict with the correction**: similarity >= 0.7 AND `memory.same_frame` (same words around one changed detail). Without this the model answered "a Honda or a Toyota" 3/3; with similarity alone, all four car notes ("red", "bought 2020", "broken mirror", "Toyota") were marked wrong. Known limit: "My car is red" still matches "My car is a Honda"; embedding the changed words can't tell detail kinds apart (same-kind 0.52–0.94 vs different 0.50–0.66). Protected notes are never demoted. Kept, never deleted (`hooks.react`).
- **A new statement replaces the older one it updates** (`add_many(supersede=True)`, `memory.replaces`): same frame, one detail changed, and a single-value verb (is/live/work/use/prefer/called…), not have/like/friend… ("I have a dog Buddy" + "I have a dog Max" keeps both). Any other verb in the present tense replaces when what changed is one concrete value on both sides ("We deploy to Heroku" -> "… Render now", "targets SDK 34" -> "35"); past tense is an event and piles up ("We fixed bug 12" / "13"). "<someone> <verb> <the/my thing> to <value>" is a change of that thing ("I switched my editor to Helix" replaces "My editor is Neovim"), only when both values are concrete ("I sent the report to Dara" doesn't replace "The report is due on Friday"). Reworded updates with a change word (now, switched, moved, migrated, instead…; `rules.changes`, note-to-note >= 0.6): replace when most of the old note's topic words are named again (4-letter stems; identifiers must match whole: "billing-api" is not "billing-worker"), the subject is what comes before the verb ("We use SQS for queues": SQS is a value), and both name a different concrete value ("We switched the cache to Redis" replaces "We cache with Memcached"). Synonym topics ("Login uses Auth0" -> "the auth provider is Clerk now") still keep both. Stream stale weeks 3–4: 6.8/7.4 -> 2.4/3.2; scale week 24: 5/12 -> 2/12. Different prepositional roles keep both ("We use pytest for tests" / "ruff for linting"). `python -m dore.eval.learning`: 19/19 update cases. Time words (now/currently/still) are ignored; long sentences are compared by their main clause ("Finance decided the max discount is 50% because…" -> "The max discount is 40%"); the change must come after the verb ("Sophal works on the mobile team" doesn't replace "Piseth works on…"). A project note replaces an older general one, never the reverse. The old note gets `replaced_by`/`valid_to`, stays in SQLite, leaves search. An unverified note never replaces a verified one. Shortlist bar 0.6 (real updates 0.76–0.90).
- **Topic keys** (`grammar.topic_key`, `MemoryStore.key_index`, 2026-11-26): each user statement also gets a second vector for its common nouns put before it ("answer, emoji: I prefer short answers without emojis."); names, numbers, unknown words, capitalised words and identifier pieces are values, not topic. Search scores a note by the closer of its two vectors; merging, replacing and note-to-note checks use the main vector only. Notes saved earlier get a key when the hook opens the store (`missing_keys`/`set_keys`). The key index is saved next to the main index (`memory.keys.faiss`). Question 0.61 -> 0.74. Measured: retrieval 5/8 -> 7/8; stream correct 26.0/26.2/24.0/23.4 -> 28.2/28.0/25.8/25.2, repeat mistakes 13.0 -> 7.6; scale correct 72 -> 79% at week 24, tokens per work prompt 6.2 -> 6.4, hook +1 ms. Tried and not used: "What about X?" prefix (more noise), the nouns alone as the key (noise 32 -> 40 of 66 prompts).
- **Place questions in the key** (`grammar._where_question`, 2026-11-26): a verb with a subject + in/at/to/from/near + a concrete name gets the "Where …?" question it answers first in its key ("I live in Siem Reap" -> "Where do I live? …"): 0.63 -> 0.72 for "where do I live?", unrelated "where …" questions 0.49-0.53. Retrieval 8/10 -> 9/10; stream week 4 25.6 -> 26.0, stale 2.8 -> 2.4; scale 79 -> 81% at week 24. Not done: a generic "What do we use?" key (noise questions reached 0.65); spaCy's entity recognizer (missed "Siem Reap", +0.8 ms a sentence). Notes saved before keep their old key until keys are rebuilt.
- **An update that names the old value it left** (`rules._names_old_value`): "i use helix now instead of neovim" / "we moved off MongoDB" / "we switched from webpack to vite" (instead of, rather than, off, away from, or "from X to Y" + one of the old note's values; "I moved the meeting from Monday" is not an update of "Standup is on Monday") replaces the old note when it names no other thing (at most one new topic word, two when the old topic is named again). "The nightly backup job moved off Jenkins" keeps "We run CI on Jenkins". Updates 35/35; stream stale weeks 3–4: 2.4/3.2 -> 2.0/2.8.
- **Re-check old notes** (`python -m dore.learn.recheck [--apply]`): re-judges the user's statements with today's rules and archives what they would not store (kept, reversible with `MemoryStore.restore`); never protected notes, documents or Claude's notes, never a standing "don't / never / no need" instruction. Real memory (2026-11-25, after a SQLite `.backup` to `data/memory-backup-2026-11-25.db`): 12 of 15 archived (pasted UI lines, requests), a real standing "don't" rule kept and still found by the hook.
- **Reactions are feedback** (`hooks.react`), only after a question: asked again (similarity >= 0.80 and not one-detail-changed: dog/cat 0.82 is a new question) = -1 to the notes used; moving on = +1. Ranking adds `0.06*tanh(feedback/4)`: reorders close notes, can't lift unrelated ones.
- **Duplicates merge only when words and numbers match exactly, in order** (plus similarity >= 0.95): bge-small scores "server IP 10.0.0.5" vs "10.0.0.6" at 0.985, and a word set merged "Alice reports to Bob" with "Bob reports to Alice". A merge keeps `created` (first date) and sets `last_seen`.
- **Not facts**: `[Request interrupted by user]`, `/commands`, hypotheticals ("If I were…", "Pretend…") (`NOT_A_FACT`).
- **Long messages** (more than 20 statements or 3000 characters) are stored as `unverified` document chunks (`source="chat-paste"`), not as verified facts.
- **Notes are embedded without time words** (`rules.embed_text`: now/currently/still…; stored text unchanged): "Which editor do I use?" vs "My editor is Helix now" 0.638 -> 0.678 (hook bar 0.65), unrelated prompts unchanged. The bge query-instruction prefix was measured and not used: it lowered matches and unrelated prompts alike.
- **Newer wins in what the hook shows** (`hooks.prompt_context`): a newer note about the same thing as a shown one (note-to-note >= `SAME_THING` 0.72, and within 0.10 of the best match) is shown too, first. Reworded updates keep both notes, and the old one often matched the question better (Neovim 0.77 vs Helix 0.68). Updates measure 0.73–0.82 note-to-note but different facts reach 0.82 too, so this only adds notes, never hides one; cost ~+6 tokens per question on `conversation long`.
- **Hub correction** (`MemoryStore.search`, `HUB_QUESTIONS`, `HUB_WEIGHT` 0.7): a note close to many generic developer questions ("Our production servers are on Ubuntu 22.04") is ranked down relative to the other candidates (`Memory.focus`); the hook's "near the best" gap uses `focus`, the 0.65 bar stays on raw similarity. Scale store: right note first 67 -> 76 of 100; end to end +1 point (most remaining misses are below 0.65 raw). Lowering the bar to 0.58 answers 70 vs 66 but gives a note to 46 vs 25 of 86 noise prompts: not done.
- **Relevance cut-off `min_similarity = 0.5`** (bge-small, cosine). Measured: a fact asked about directly scores ~0.68–0.83; differently-phrased personal questions only ~0.51–0.55 ("Where do I live?" vs "I live in Phnom Penh"); unrelated items are mostly below 0.5 but can reach ~0.57. The prompt tells the model to use only notes that answer the question.

## One fact per note (2026-11-26)

- **Two clauses with their own subjects are two notes** (`grammar.split_clauses`, run before `fact_text`): "the
  api is on port 3000 and the worker is on port 3001". A whole note mixing two facts could never be updated (the
  update rules rightly refuse to hide the true half). Not split: one subject with two objects ("I have a dog and
  a cat"), a second subject pointing back ("... and it runs on RDS"), questions. A half the parser reads as a
  judgement ("is react" like "is slow") is kept only when it parallels the other half in meaning (dore's
  embedder on the content words >= `statements.PARALLEL` 0.6: "frontend react" ~ "backend django" 0.72, "page
  slow" ~ "api django" 0.55). Parser misreads stay ("the web uses Vite and the mobile app uses Expo").
- **A side clause before the comma is dropped** (`grammar.strip_lead`): no subject, no object or complement, no
  detail ("heads up, ...", "quick note, ..."); kept: "Keep your answers short, ..." (an instruction), "Locally, ..."
  and "In production, ..." (a place).
- Measured: DEV 55/59 -> 58/62 right scope, junk 7/81; HELDOUT 40/43 -> 43/46, junk 3/46 (every new case right,
  "kotlin and ktor" included); stream and scale unchanged. Parses are cached per sentence (`grammar._Cached`):
  scale hook median 10 -> 6–7 ms, p95 23 -> 13–16 ms.

## Notes on trial (Voyager-style check, 2026-11-26)

- A statement learned from chat starts **on trial** (`memory.on_trial`): shown only when the prompt asks something
  (`hooks._asks`), never added to work prompts. It is **proven** when Claude's next reply clearly uses it
  (`hooks.use_check`: most of what the note adds beyond the prompt is in the reply, words weighted by rarity in
  Claude's replies (`reply_words` table), and holding them by luck is under 1%), or when the user says it again
  in another session (`times_seen >= 2`). Standing rules still show once per session, on trial or not.
- Only the **best-matching** shown note is on test (a side note beside a better one says nothing). A try counts
  only when the check could have seen a use (enough replies counted, rare enough words). After `ARCHIVE_TRIES` = 3
  tries with no use the note (or a shown request) is archived, kept; said again, it comes back proven.
- Why not judge the sentence: on paraphrased real junk, the grammar gate, a zero-shot NLI model and a typo count
  all failed (1/6, 4/6, 2/6 junk caught; 2, 6, 1 of 10 facts lost). Claude's reply alone: share >= 0.6 for 6 of 29
  useful lines, 0 of 30 junk; lower shares separate nothing, so only a clear use proves.
- Measured: real replay (908 prompts, every project, fresh store): note lines shown 280 -> 121, 7 notes archived
  (5 junk; 2 true but never needed, they return if said again); every real question still got its note.
  `eval.stream seeds 5`: correct unchanged, tokens per work prompt 3.7 -> 0.4. Check cost ~1 ms per prompt.

- **Rules are on trial too** (2026-11-26, user's choice): a standing rule said once is not added at every
  session start (the most shown line in the real replay was a complaint shaped like a rule, 17 sessions); it is
  shown when a question matches it, and starts every session once proven (said again in another session, or
  used). An exemption that let rule-shaped notes onto work prompts made them immortal (real replay 145 -> 163
  lines): removed. Real replay now 280 -> 114 note lines; conversation short ~73 -> ~35 tokens per question.
- **Most specific wins when reading** (`hooks.prompt_context`): a general note about the same thing as one of this
  project's own notes (`replaces` either way) is left out in that project, whichever was said first.
- **A value is found by its place** (`rules._slot_change`): "<topic> is <x>" -> "<change word> <topic> to <y>",
  one word each, whatever its case ("The frontend is react" -> "We moved the frontend to vue"). A leading "-ly"
  adverb before the subject is ignored when comparing notes (`rules._unplace`; the note keeps its text).
- Left: a request written as a question ("can you add …?") counts as a question, so a note on trial can be tried
  there (it is archived if never used).

## Facts by situation, not by likeness: measured, not adopted (2026-11-27)

- Search finds a note only when the message sounds like it; a note that applies by situation never comes
  (a one-line feature request vs a security rule for every new feature: no shared words). Labelled real prompts
  (26, my labels):
  today's search 12/39 notes that apply; "applies when" keys written by Haiku 20/39 with 15 wrong; an index of every
  fact at the session start, the model picking, 32/39 (Haiku as the reader) for ~75 more tokens a session
  (`eval.stream` tokens per work prompt 0.8 -> 3.5). Built, then removed by the user (2026-11-27): facts Claude
  doesn't need should not be loaded. Skills-style topic titles opened on demand (63 notes): 23/39 for ~277 tokens a
  task (1.8 tool calls) vs full lines 17/39 for ~145: a note (~14 tokens) is too small for a pointer to save tokens.

## Rules come to mind like habits (2026-11-26)

- **An instruction is known by its form, lasting by evidence** (2026-11-26; the "never/must/decided/limit" word list is
  gone). `grammar.instruction`: a command with never/always/don't, or the user's own standing way ("I don't want…",
  "we always…", "I prefer…", "I like to <do>…"); not a description ("the upload limit is 10 MB"), an event (past
  tense: "we decided…", "I didn't…"), a plain command (usually a request for now: "commit this"), a question, a
  state of mind ("I don't think…"), a taste ("I like jazz"), a clause hanging off another ("because…"); after a
  short label ("Note: …") the rest is judged. DEV 22/22, HELDOUT 12/12; on real notes 6 of 8 statements it marks
  are real instructions (the word list: 5 of 9). Whether one *lasts* is left to evidence (said again in another
  session, practised): a real replay of 113 sessions over 12 projects found that the user almost never repeats a
  rule in the same words, "No, …" right after Claude acted was bug feedback every time (3 of 3, not a rule), and
  repeats by meaning (>= 0.75) were mostly different requests ("Don't use java" ~ "Never use tabs" 0.79): none of
  those is used as evidence. A first-person preference starts sessions only when it is about the work: most of its
  topic words come up in Claude's replies (`hooks.about_work`; "I don't like coffee" never does). Marked when saved
  by the hook (`mark_instructions`); notes saved before are re-marked once, while idle, a batch at a time
  (`remark_instructions` in `consolidate`; 3,000 notes took 4.2 s, too slow for the prompt path).
  Real replay: 1 note would start sessions (a real rule), 0 junk; 936 messages, 4.3 tokens per message on average,
  no long session grows. Research behind it: CoALA (facts vs how to act), LangMem (procedures from feedback),
  Wood & Neal (habits: context -> action, built by repetition) — `REFERENCES.md`.
- **A request never comes unprompted**: a request's whole text (`kind="requirement"`, `source="user"`) asks for
  something done now; only the rule parts taken out of it (`RULE_SOURCE`) and statements may start sessions (on a
  copy of the real memory, most marked instructions were such request texts, hidden until repeated).
- **"here" is the codebase only when the sentence isn't about the user** (`statements.scope_for`,
  `rules.codebase_place`): "I live here in Phnom Penh" is the user's (general); "here we never push…" and "in this
  repo…" are the project's (review finding 2026-11-26).
- **Marked once, when saved** (`memories.rule`, by `grammar.instruction`; old notes re-marked once while idle). A session start
  reads only rule notes through an index (`MemoryStore.rule_notes`): 20,400 notes with 400 rules, 8.6 ms (the old
  read of the newest 200 notes, re-tested each time: 15.2 ms, and rules older than those 200 were never seen).
- **Strength, not a count** (`memory.activation`, ACT-R base-level learning): every repeat (`times_seen`) and every
  clear use by Claude (`uses`, `last_used`) adds strength; strength fades as a power of time; often-repeated rules
  fade slowly. A proven rule starts sessions while at least as strong as one mention 30 days ago (`FADE_DAYS`):
  said twice it lasts ~4 months, said 5 times over a year it lasts past a year without repeats. A faded rule is not
  deleted or hidden: search still adds it when a message matches.
- **No fixed number, never cut, one budget per session**: the rules in mind, strongest and closest to the first
  prompt first (context primes memory), are picked while they fit `RULES_PER_SESSION` (600 characters, the old
  block's most), so the README's "only the notes that match your message" stays true. Notes that answer the prompt
  come first; a picked rule that doesn't fit that message comes whole with the next one. Rules not picked are not
  lost: search adds them when a message matches. Measured (`eval.rules`): 3 / 6 / 10 / 20 / 40 proven rules cost
  70 / 122 / 157 / 158 / 160 tokens per session, one message (unlimited carry-over was 70 / 122 / 209 / 406 / 800).
- **Practice keeps a rule alive** (`hooks.practise_rules`, `practised`, `grammar.rule_parts`, 2026-11-26): what
  Claude did in its answer (tool inputs: commands run, code written; `hooks.last_turn`) is checked against every
  proven rule note of the project, once per rule per session. Practice = most of what the rule wants (light verbs
  left out, words weighted by rarity) is in Claude's text or actions, part of it in what it did, and nothing the
  rule forbids (what "never/don't/not", "without", "no" apply to) is in what it did: "never use print, use the
  logger" is practised by `logger.info`, broken by `print(`. A rule that only forbids ("never use tabs") can't be
  seen being followed and fades unless repeated. Practice never proves a rule on trial: in the real replay three
  feature requests with "should" were "practised" by Claude implementing them (note lines 109 -> 131); only
  rules the user said in two sessions are kept alive by practice. `eval.rules` 24/24.
- **A repeat in the same session doesn't prove a note** (`hooks.learn_message`): only another session does.
- **Notes and rules are one store**: a rule is a note with `rule=1` (an instruction by form). A note that is also a
  rule is shown once per message (it was shown twice: as the matching note and as a session-start rule; fixed
  2026-11-26, `eval.rules` case). Facts ("the upload limit is 10 MB", "we decided…") are never rules.
- **"in this repo", "here", "locally" keep a note in its project** (`statements.scope_for` uses `rules.local_value`):
  "Here we never push straight to main" went general through `ORG` ("we never"). Without a place word, a standing
  rule with no subject is still the user's (general).
- `python -m dore.eval.rules`: 17 cases (said once / twice / in one session, fading, spacing, changed, project vs
  user, personal "don't", complaint, long rule, notes first, over budget) all pass; quoting a rule ("you said
  'never use tabs'") is a known gap. Real memory today: 3 rule notes, all on trial, so none start a session.
- Left: quoting a rule ("you said 'never use tabs'") can still be saved as a hidden rule part (never shown unless
  said again in another session).

## Project vs general (scope)

- A note's `project` is the session's **git repo** (`integrations.project`, 2026-11-26): the remote
  (`host/owner/repo`, user and token dropped) or else the repo root path; subfolders and worktrees share it, two
  repos with the same folder name stay apart; a folder without git is its full path, or the session's start
  folder (`CLAUDE_PROJECT_DIR`, sent by `hookclient`) when it is under it (a folder above that dore knows is not
  joined: it may hold many projects; a moved folder without git loses its notes); the home folder (or `/`) is
  its own place `~`, not general (a repo in the home folder doesn't own the folders under it). Plain file reads,
  no `git` process: 0.2–0.6 ms the first time per folder, 0.02 ms cached; warm hook unchanged (~0.06 s). The first
  time a place is seen in a process (`hooks.resolve_project`), notes and raw memory stored under its older keys
  (repo and session folder names, the path key) move to it (`MemoryStore.rename_project`; general notes never
  move; old home-folder notes stay general, they can't be told apart). A real subfolder of this repo had been
  its own project. Search sees the current project + general.
- `learn/statements.py: scope_for`: organisation facts (`ORG`: "our production server", "we always…", "all our
  services", "every project") and facts about the user go to general; everything else stays in the project.
  "About the user" is decided by the sentence's subject (`grammar.about_user`): "I…" / "my…" / "X is my Y" or a
  standing rule with no subject ("Always use spaces") is general; "I set the dev server to port 3001" (past action
  on a thing) is the project's. Without spaCy: any I/my/me makes it general. A sentence with no verb ("my dog name
  Adam", "my hometown kampot") is the user's when its noun phrase is "my …" (the parser picked a different head each
  time: "My sister name Dara" went general, "My dog name Adam" stayed in one project; DEV 46 -> 48/52, 2026-11-26).
- **An update lives where the fact lives** (scope S2, 2026-11-26): a project note that replaces a general note
  becomes general, so every project sees the new value. Said with a place ("here", "locally", "in this repo";
  `rules.local_value`), it is that project's own value: the general note stays for the others and is hidden only
  there (`shadows` table, read by `MemoryStore.search`). Place words are ignored when comparing two notes
  (`rules._unplace`), like time words. **No cross-project fallback**: another project's note is never shown (it
  leaked values; with updates keeping their scope it rescued nothing). Stream weeks 3–4 correct 26.2/26.0 ->
  27.6/27.6, repeat mistakes 6.4 -> 5.0; scale unchanged (81% at week 24), tokens per work prompt 6.4 -> 1.4.
  Left: "Here **the** server…" vs "**Our** server…" is not seen as an update (determiners compared as words).
- **Where a general fact was said decides who its change reaches** (scope S3, 2026-11-26): every note records
  the project it was said in (`said_in`). Changed in that project, a general fact changes for everyone; changed
  in another project, the new value is that project's own (the general note is hidden only there; when unsure,
  keep both). A project's own value keeps hiding the general fact after the general value changes. Not done,
  measured as harmful: promoting a fact because 2 projects state the same value (projects share values by
  chance: three use Cognito in `eval.scale`); removing `ORG` ("our production server…") before evidence can
  replace it. `ORG` stays a first guess that later evidence overrides. Stream and scale unchanged.
- **Promotion** (`hooks._promoted`): a habit with no concrete value, said with the same content words in a second project, is saved as general ("Don't reformat existing code"). Close meaning is not enough: "We merge into develop" / "… into trunk" (0.9) differ in a value that is an ordinary word (it leaked 1.2/week in the stream test before this check).
- Not yet (roadmap step 4): promoting a project fact to general when it shows up in 2+ projects; telling
  apart two folders with the same name.

## Known weaknesses (open)

Measured 2026-11-25 (`dore.eval.learning`, `dore.eval.stream seeds 5`):
- **The embedder is the retrieval ceiling.** `bge-base-en-v1.5` (measured 2026-11-25 on the scale store, same noise level): answered 73 vs 65 of 100, right note first 76 vs 67; cost 11.4 vs 2.9 ms per text, more RAM; needs every threshold recalibrated (bar ~0.60) and a re-embed. End to end (12-week scale run, hook bar 0.60): only +1 to +3 points (76 -> 79% at week 12), hook 10 -> 23 ms median: not adopted.
- **Rephrased questions with a synonym miss their note** (retrieval 9/10 with topic and place keys; real test 2026-11-26: "which package manager should I use?" vs "we use pnpm, not npm" 0.61 needs knowing pnpm is a package manager): "What is my job?" vs "I work as a nurse…" 0.55, "Which editor do I use?" vs "I write all my code in Neovim" (the note never says editor), "What is the main branch called?" vs "We merge everything into develop". Topic keys fix only questions that name a word of the note; synonyms need meaning (a bigger embedder or an LLM). Lowering the 0.65 bar would add unrelated notes (unrelated prompts reach 0.72).
- **Reworded updates with a synonym topic keep both notes** ("we migrated the database to DynamoDB" after "our db are MongoDB"; "the blog is hosted on Cloudflare now" after "We deploy to Netlify"): stale shown 2.0/2.8 in weeks 3–4 over 5 seeds (the newer note is shown first). The stream counts "…, we moved off MongoDB" as stale too, though it is the new note.
- **Organisation facts said without "our"** ("we upgraded the production server to Ubuntu 24.04") stay in one project (roadmap step 4: promotion).
- **Long run-on non-native sentences** that mix a description with requests are sometimes stored (real fresh sample: 5/118 junk, all this kind); the parser misreads them.
- **English only**: Khmer and other languages are neither learned (the parser can't read them) nor retrievable (`bge-small-en-v1.5`). Needs a multilingual parser and embedder and a full re-embed.
- Some parser misreads lose a fact ("Call me Sok.", "The mobile app talks to the gateway at …" with sm; md fixes most).
- **One question that asks two things gets only the best-matching note** (real `claude -p` test 2026-11-26: "Which port does our staging server use, and where do we deploy the shop API?" got the port note, not the deploy note; the 0.05 gap near the best match drops the second). Asked one at a time, both are found.
- Questions with no answer still get loosely related notes (`bench scale`: 0/100 empty).
- Every add checks duplicates with a flat search (O(n)): fine for chat, slow for bulk loads of 100k (440 items/s).
- Re-ask detection misses big rewordings ("What is my job?" / "What do I do for work?" 0.79).

## Learning by Haiku consolidation (opt-in, 2026-11-26)

- `data/learner` = `haiku` (asked at install, default no; `DORE_LEARN` overrides): the word rules still learn at once
  (provisional notes, table `provisional`: the first session works before any batch), and the prompt hook also queues
  the message's sentences in raw memory (`hooks.queue_message`, shape filter `learn.consolidate.sentences`: 3-60 words,
  questions only with 12+ words, no code/logs, nothing from messages over 3,000 chars, at most 20 per message, not
  Claude's text pasted back). An exact repeat of a sentence that became a note counts at once (`said_again`, once per
  session, `note_sessions`).
- Only at a session end (SessionEnd), never while the user works, and only when 30 items wait or the oldest has
  waited 3 hours (2026-11-27, the user's choice). Real history (26 days, ~30 items a day): every session end 118 calls,
  ~238k tokens; 30 or 1 day 32 calls (measured ~150k); 30 or 3 h 46 calls, ~166k (estimate: ~1k fixed per call +
  ~120k content), 90% judged within 22 h. Past ~20 items the batch size barely matters; the floor is the content
  (each sentence with up to 3 nearby notes). Up to 3 batches per session end. Sentences and long blocks share one call
  (`judge.judge_all`). A batch goes to Haiku in one call (`learn.judge`), each with up to 3 notes
  >= 0.6 similar. Verdicts: skip / fact / rule (with situation and forbidden words for practice) / same #id or @line /
  update #id. Checks: ids only from that line's shortlist; every name and number in a note must be in the sentence
  (`grounded`); an update hides the old note only when a second focused question ("can both be true?") says no
  (`confirm_updates`): without it updates were 21-29/35, with it 34-35/35. If unsure: project scope.
- Measured (`python -m dore.eval.consolidation`, recorded answers): DEV facts 59/62, right scope 55/62, junk 1/81;
  HELDOUT 43/46, 42/46, junk 2/46 (both pasted assistant summaries); updates 35/35. Real labelled prompts: junk 8/237,
  mostly real rules stated inside requests. Real replay (810 messages): 71 notes, 18 rules, 3 proven, 13 rewordings
  merged (word rules: 216 notes, 45 rules, 0 proven). Low effort + thinking off: same answers, ~8x fewer output
  tokens; run outside any project folder (inside one Claude Code loads its CLAUDE.md: ~4.7k tokens a call).
- Failures (checked 2026-11-27 with a fake `claude`): usage limit -> nothing applied, retried after the reset time
  the message gives; not logged in, no internet, a hung call (180 s), no `claude` command -> retried in 30 min,
  doubling to a day; a reply with no verdict line (an apology, an error worded as text) counts as a failed call (it
  had emptied the queue and archived every provisional note); a line Haiku left unanswered stays queued with its
  note (it had counted as skip). Nothing is applied until every call of a batch has answered.
- Haiku answers vary run to run (updates 29-35/35 across prompt versions): judge a prompt change on HELDOUT, more
  than one run when the difference is small.
- **A rule is any instruction about how to work or answer, lasting by evidence** (2026-11-27): Haiku keeps an
  instruction said inside a task request too, in the user's words, <= 60 chars (not what to build in the product); it
  stays hidden on trial until said again in another session. DEV facts 56/62 (59 before; the same batch asked twice
  kept and dropped the same two facts), junk 1/81, hidden rule lines 6/81, HELDOUT 43/46, junk 0/46, updates 34/35.
- **Rule repeats are matched after the call, against one line per saved rule** (`consolidate.refine`, `judge.REFINE`;
  ExpeL/ACE-style; research: similarity can't tell "the same rule" from "related, with a new detail", and merging
  loses the detail, MEMOIR/Mem0 keep both): saved rules are no longer offered as neighbours (Haiku said "same #id"
  for a different rule). Code joins only near-identical wording (>= 0.95); saved rules >= 0.70 close (at most 5) go
  to one Haiku question with three answers: same (joined: replaced, kept; the saved rule said again), **adds a
  detail** (stays its own rule, linked to the saved one in `rule_links`; the saved one counts as said again), new.
  Only an answer line alone counts (Haiku reasons, then answers). A session start shows one line per family, its head
  (`hooks.prompt_context`); the others come when a message matches. Embedding similarity alone was measured and not
  used for the card: different rules "never import module m1 / m2" 0.93, rewordings of one rule 0.73-0.88.
  "same @M" for a line that gave two notes takes the closer one (it had linked a repeat to the line's other rule).
  Sentences up to 200 words are judged (43 typed run-ons over 60 words in all history, ~5k tokens; they held rules).
  Real replay (165 messages, 50+ sessions): the most repeated rule, 7 sayings in one family, said in 4+ sessions, one
  card line; a rule with a new detail (who does it) stays apart from the rule it details; task junk on the card 0;
  card 3 lines, ~270 chars. Left: Haiku linked one wrong detail under an unrelated rule, a wish about the reply said
  in passing ("... and keep it brief") is mostly not kept, ~44k tokens for 165 messages (13 calls; most of it output
  overhead).

## Long messages as groups (2026-11-27, plan: [long-text-groups](../plans/long-text-groups.md))

- A list is one **group**: a group note (its title, `kind="group"`) and one note per entry, word for word, linked by
  `group_id`; an entry is searched with the title beside it (key vector). Entries of one group never replace each
  other; an entry said before joins the group (`said_again`, once per session); recheck never re-judges entries.
- Word rules (Haiku off): only a list the user typed under their own lead line ending in ":" that tells or names
  something (`statements.list_group`); no entry may be a request, a question, code or indented. Lists without a lead
  line and every paste wait for Haiku. Real history (892 typed messages): 0 lists made (1, a pasted compose file,
  before the indent check).
- Haiku: a message with a paste, 3+ lines, over 3,000 chars or over 20 sentences is queued whole (raw memory, up to
  200k chars) and judged as one block (`judge.BLOCK_SYSTEM`; a long block by its first 40 and last 10 lines, each line
  once): skip, group (title, fields, entry lines), fact or rule. Pasted text: a fact or rule taken out of it is
  `unverified`; a pasted list is `verified` only when the user's words beside it tell something.
- Measured (`python -m dore.eval.lists`, recorded answers): entries found by a later question, word rules 6/16, Haiku
  15/16 (miss: "comes from" vs "live", 0.62 < 0.65); 50-entry list via recall 50/50; noise 0 of 8 messages (traceback,
  npm log, code, task list, bug list, article, pasted summary, build story); secrets stored 0. Real long messages (18):
  3 Haiku calls, ~13k tokens, 15 skipped. One prompt line ("bugs to fix are not a group") moved the bug list from kept
  to skipped: judge a block-prompt change on the whole noise set.
- A list's title is shown only on a question (like a note on trial) and carries no field names: with "(name, job,
  city)" in the title and titles on work prompts, 10 of 16 work prompts with the lists' words got a title; without,
  3/16 (2 of them this project's config, wanted). `eval.lists`: similar-word work prompts given list text 3/72, all
  "who is logged in right now?". Known miss: a command asking for the list ("List my students") is not a question.
- Haiku sees a long block by its first 20 and last 5 lines (160 chars each; whole up to 30 lines): same results on
  `eval.lists` (15/16, recall 50/50, noise 0) as with 40 + 10. A one-block call: ~1,500 tokens, ~60 output.
