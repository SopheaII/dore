# Memory learning rules

How learning, replacing, demoting and retrieval work, with measured limits. Procedure for changes: the `learning-change` skill.

## How it works (Claude Code hooks and dore's own chat)

The default check is `python -m dore.eval.conversation`. The rules here apply to the Claude Code hooks; the section
"dore's own chat only" applies to the local 1B model, which the user does not run day to day.

- **Statements in plain chat are learned automatically**: `Agent.remember_statements` splits the user's message into sentences, skips questions (ending in `?` or starting with a `QUESTION_START` word) and sentences under 3 words, and stores each one as `kind="statement"`, `source="user"`, `trust="verified"`. One fact per memory matches questions far better than a whole message.
- **The model's own answers (`kind="answer"`) are stored but kept out of the vector index until the user approves them with `/good`** (which makes them `verified`; `memory.searchable()` is the single rule). Otherwise made-up answers come back as "memory" and reinforce themselves (observed: an invented "Elm Street" address), and they used to crowd real facts out of the top-20 search candidates. They are also never merged with other memories, so `/correct` can't mark a user's fact wrong.
- **What a Claude Code prompt teaches** (`learn/statements.py: message_facts` -> `user_facts` -> `learn/grammar.py: fact_text`), decided by shape and grammar, not by lists of topic or action words (2026-11-25):
  - *Shape* (`structured_line`, any language): `<tag>…</tag>` blocks (pasted content, task notifications) are removed; a message of 3+ lines, or 2 lines with one shaped like output (bullets, indentation, stack frames, `file:line`, 2+ backtick spans, `k=v` pairs, columns, status symbols, many ALL-CAPS words, code symbols), is a paste: nothing stored.
  - *Grammar* (spaCy `en_core_web_md`, ~1 ms/sentence, 0.6 s load, preloaded by the warm helper): not facts = questions (question word, inverted auxiliary, "… or not"), commands (a base-form verb with no subject, any verb; "Always/never …" is a standing rule and is kept), fragments, a subject that is only it/this/that, "you …", I/we + wanting (want/need/would like) or cognition verbs (think/suspect/saw/mean/try…), possibility (may/might/could) or I/we + can/will, appearance verbs (look/seem) or "X is ADJ" with no concrete detail, a bare event with no object or detail ("the build passed"), an object that is only "it"/"this approach". A fact in a joined clause, a clause before a command, or a reason clause (since/because) is kept alone ("fix the worker since our queue is Kafka" -> "Our queue is Kafka").
  - *Concrete detail* (`grammar._detail`): a proper noun, number, identifier, path, or a word the model's vocabulary doesn't know ("vitest", "pnpm"; typos like "teh" are known). 3-word facts need one ("tests use vitest"). When the parse has no verb at all (md misreads "Our staging server runs on port 8443" as a noun phrase), the old word rules decide, and only with a detail.
  - *Added after replaying all 1,033 real prompts (2026-11-25)*: a polite sentence ("please", misspelt too: by spelling closeness) is a request; only a separate part before the marker, with a strong detail or starting with I/we/my/our, is kept ("we deploy with Ansible, so please check …"). "…, right" / "… or not" make a question (a "because …" clause inside can still be kept). Sentences that start with because/since/after/if… hang off something said before. Whole-sentence facts are at most 20 words (run-ons give up only a short clause, cut at but/so/because/"…"). Future will/would, I + any modal, I + misspelt want/think words (content words only: "with" is not "wish"), "I/we … it/this" without a strong detail, and shell or error lines (`&&`, `|`, "bash: x: not found", "·" separators) are not facts.
  - *Echo* (`hooks.not_echoed`): a sentence of 5+ words that Claude already wrote in this session (transcript tail) is not a new user fact, in any language.
  - Real replay (`all 1,033 prompts, 14 projects`): 70 -> 46 notes stored, tokens added 12.4 -> 7.9 per prompt, every real fact kept (checked by reading every stored note; details in the private report).
  - Without spaCy, the old word lists run unchanged (`QUESTION_START`, `IMPERATIVE`, `WANT`, `VAGUE`, `PLEASE`).
  - Measured (`python -m dore.eval.learning`): facts learned with the right scope DEV 39/42, HELDOUT 38/41 (word rules: 30/42, 32/41); junk DEV 1/51, HELDOUT 0/39 (word rules: 24/51, 18/39). Real prompts, fresh unseen sample: facts 3/3 (1/3), junk 7/118 (27/118).
- **dore's own chat** (`split_statements`, local 1B only): "Please remember / FYI / can you note that X" stores X (even in question form); small talk and requests ("Summarize the following text") are not stored.
- **`/correct` (or "No, …" / "Actually, …" after an answer) marks wrong the used notes that conflict with the correction**: similarity >= 0.7 AND `memory.same_frame` (same words around one changed detail). Without this the model answered "a Honda or a Toyota" 3/3; with similarity alone, all four car notes ("red", "bought 2020", "broken mirror", "Toyota") were marked wrong. Known limit: "My car is red" still matches "My car is a Honda"; embedding the changed words can't tell detail kinds apart (same-kind 0.52–0.94 vs different 0.50–0.66). Protected notes are never demoted. Kept, never deleted (`Agent.last_demoted_ids`).
- **A new statement replaces the older one it updates** (`add_many(supersede=True)`, `memory.replaces`): same frame, one detail changed, and a single-value verb (is/live/work/use/prefer/called…), not have/like/friend… ("I have a dog Buddy" + "I have a dog Max" keeps both). Any other verb in the present tense replaces when what changed is one concrete value on both sides ("We deploy to Heroku" -> "… Render now", "targets SDK 34" -> "35"); past tense is an event and piles up ("We fixed bug 12" / "13"). "<someone> <verb> <the/my thing> to <value>" is a change of that thing ("I switched my editor to Helix" replaces "My editor is Neovim"), only when both values are concrete ("I sent the report to Dara" doesn't replace "The report is due on Friday"). Different prepositional roles keep both ("We use pytest for tests" / "ruff for linting"). `python -m dore.eval.learning`: 19/19 update cases. Time words (now/currently/still) are ignored; long sentences are compared by their main clause ("Finance decided the max discount is 50% because…" -> "The max discount is 40%"); the change must come after the verb ("Sophal works on the mobile team" doesn't replace "Piseth works on…"). A project note replaces an older general one, never the reverse. The old note gets `replaced_by`/`valid_to`, stays in SQLite, leaves search. An unverified note never replaces a verified one. Shortlist bar 0.6 (real updates 0.76–0.90).
- **Reactions are feedback** (`Agent._react`, `hooks.react`), only after a question: asked again (similarity >= 0.80 and not one-detail-changed: dog/cat 0.82 is a new question) = -1 to the notes used; moving on = +1; `/good` `/bad` = ±3. Ranking adds `0.06*tanh(feedback/4)`: reorders close notes, can't lift unrelated ones.
- **Duplicates merge only when words and numbers match exactly, in order** (plus similarity >= 0.95): bge-small scores "server IP 10.0.0.5" vs "10.0.0.6" at 0.985, and a word set merged "Alice reports to Bob" with "Bob reports to Alice". A merge keeps `created` (first date) and sets `last_seen`.
- **Not facts**: `[Request interrupted by user]`, `/commands`, hypotheticals ("If I were…", "Pretend…") (`NOT_A_FACT`).
- **Long messages** (more than 20 statements or 3000 characters) are stored as `unverified` document chunks (`source="chat-paste"`), not as verified facts.
- **Notes are embedded without time words** (`rules.embed_text`: now/currently/still…; stored text unchanged): "Which editor do I use?" vs "My editor is Helix now" 0.638 -> 0.678 (hook bar 0.65), unrelated prompts unchanged. The bge query-instruction prefix was measured and not used: it lowered matches and unrelated prompts alike.
- **Newer wins in what the hook shows** (`hooks.prompt_context`): a newer note about the same thing as a shown one (note-to-note >= `SAME_THING` 0.72, and within 0.10 of the best match) is shown too, first. Reworded updates keep both notes, and the old one often matched the question better (Neovim 0.77 vs Helix 0.68). Updates measure 0.73–0.82 note-to-note but different facts reach 0.82 too, so this only adds notes, never hides one; cost ~+6 tokens per question on `conversation long`.
- **Hub correction** (`MemoryStore.search`, `HUB_QUESTIONS`, `HUB_WEIGHT` 0.7): a note close to many generic developer questions ("Our production servers are on Ubuntu 22.04") is ranked down relative to the other candidates (`Memory.focus`); the hook's "near the best" gap uses `focus`, the 0.65 bar stays on raw similarity. Scale store: right note first 67 -> 76 of 100; end to end +1 point (most remaining misses are below 0.65 raw). Lowering the bar to 0.58 answers 70 vs 66 but gives a note to 46 vs 25 of 86 noise prompts: not done.
- **Relevance cut-off `min_similarity = 0.5`** (bge-small, cosine). Measured: a fact asked about directly scores ~0.68–0.83; differently-phrased personal questions only ~0.51–0.55 ("Where do I live?" vs "I live in Phnom Penh"); unrelated items are mostly below 0.5 but can reach ~0.57. The prompt tells the model to use only notes that answer the question.

## Project vs general (scope)

- A note's `project` is the folder name of the session (`hooks._project`; home or `/` -> general `""`). Search sees
  the current project + general.
- `learn/statements.py: scope_for`: organisation facts (`ORG`: "our production server", "we always…", "all our
  services", "every project") and facts about the user go to general; everything else stays in the project.
  "About the user" is decided by the sentence's subject (`grammar.about_user`): "I…" / "my…" / "X is my Y" or a
  standing rule with no subject ("Always use spaces") is general; "I set the dev server to port 3001" (past action
  on a thing) is the project's. Without spaCy: any I/my/me makes it general.
- A project note replaces an older general one, never the reverse.
- Not yet (roadmap step 4): promoting a project fact to general when it shows up in 2+ projects; telling
  apart two folders with the same name.

## dore's own chat only (local 1B model)

- **Questions about the user get `NO_GUESS`** ("If no note above answers this, say you don't know.") after the question. Measured with 7 questions × 8 seeds: 54/56 strict vs 42/56 without (the model invented "Your dog is called Kavi"). Longer wordings were worse (one turned "Calmette Hospital" into "Pasteur Institute"). One run of the real-model check is not enough to compare prompts: sample several seeds with `llm.set_seed`.
- **Memory notes go in the user turn, right before the question**, not in the system prompt: the 1B model ignored system-prompt notes.
- **Notes are labelled with their origin and date** (`[verified, told by the user, 2026-11-25]`, `[unverified, from a document, …]`, `tested`); dates did not change selftest results. Without "told by the user", the 1B model read "My favourite language is…" as being about itself.
- **The 1B model ignores notes marked `[unverified]`**, which is why user statements are stored as `verified`.

### Real-model check (dore's own chat; only when the user asks)

Use a throw-away data folder so the real memory is untouched, then delete it:

```bash
export DORE_DATA=$PWD/data/tmp-check && mkdir -p $DORE_DATA && ln -s ../models $DORE_DATA/models && ln -s ../cache $DORE_DATA/cache
printf 'My cat is called Mochi and I live in Phnom Penh.\nI work as a nurse at Calmette Hospital.\n/quit\n' | .venv/bin/dore
printf 'What is my cat called?\nWhere do I live?\nWhat is my job?\nWhat is my dog called?\nWhat is the capital of France?\n/quit\n' | .venv/bin/dore
rm -rf $DORE_DATA
```

Expected: Mochi / Phnom Penh / nurse at Calmette Hospital / "no information about your dog" / Paris. As of 2026-11-25 the dog answer is invented in most runs (1B guess, prompt unchanged); everything else passes.

## Known weaknesses (open)

Measured 2026-11-25 (`dore.eval.learning`, `dore.eval.stream seeds 5`):
- **The embedder is the retrieval ceiling.** `bge-base-en-v1.5` (measured 2026-11-25 on the scale store, same noise level): answered 73 vs 65 of 100, right note first 76 vs 67; cost 11.4 vs 2.9 ms per text, more RAM; needs every threshold recalibrated (bar ~0.60) and a re-embed. Candidate next step.
- **Rephrased questions miss their note** (retrieval 5/8): "How long should your answers be?" vs "I prefer short answers…" 0.61, "What is my job?" vs "I work as a nurse…" 0.55, "What is my name?" vs "I'm Dara, by the way". The biggest cause of stream misses. Fix: likely-question keys per note (roadmap step 5); lowering the 0.65 bar would add unrelated notes (unrelated prompts reach 0.72).
- **Reworded updates keep both notes** ("we migrated the database to DynamoDB" after "our db are MongoDB"; "the blog is hosted on Cloudflare now" after "We deploy to Netlify"): stale shown 7/11 in weeks 3–4 over 5 seeds, though the newer note is shown first.
- **Organisation facts said without "our"** ("we upgraded the production server to Ubuntu 24.04") stay in one project (roadmap step 4: promotion).
- **Long run-on non-native sentences** that mix a description with requests are sometimes stored (real fresh sample: 7/118 junk, all this kind); the parser misreads them.
- **English only**: Khmer and other languages are neither learned (the parser can't read them) nor retrievable (`bge-small-en-v1.5`). Needs a multilingual parser and embedder and a full re-embed.
- Some parser misreads lose a fact ("Call me Sok.", "The mobile app talks to the gateway at …" with sm; md fixes most).
- Questions with no answer still get loosely related notes (`bench scale`: 0/100 empty).
- Every add checks duplicates with a flat search (O(n)): fine for chat, slow for bulk loads of 100k (440 items/s).
- Re-ask detection misses big rewordings ("What is my job?" / "What do I do for work?" 0.79).
