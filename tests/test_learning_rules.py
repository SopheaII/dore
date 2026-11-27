"""Learning rules on new sentences (not from cases.py), so these also check generalisation."""

import pytest

from dore.learn.statements import message_facts, scope_for, structured_line
from dore.memory.rules import changes, embed_text, replaces

grammar = pytest.importorskip("dore.learn.grammar")
needs_parser = pytest.mark.skipif(grammar.nlp() is None, reason="spaCy model not installed")


def test_pasted_output_is_not_learned_whatever_its_words():
    assert message_facts("<task-notification>\n<summary>Agent done</summary>\n</task-notification>") == []
    assert message_facts('look\n\n<pasted_content id="x">\nThe cache is cold.\n</pasted_content id="x">') == []
    assert message_facts("line one is here.\nline two is here.\nline three is here.") == []  # 3+ lines
    assert message_facts("✔ Deployed.\nVisit the dashboard for logs") == []  # 2 lines, one shaped like output
    for line in ("  at Object.<anonymous> (index.js:3:9)", "- moved helpers into utils", "see `a.py` and `b.py`",
                 "src/app.ts:14 has the bug", "id=3 status=ok", "NAME   READY   STATUS"):
        assert structured_line(line), line
    assert not structured_line("Our billing service runs on port 7001.")


@needs_parser
@pytest.mark.parametrize("text", [
    "The worker queue is Kafka.", "we keep logs for 90 days", "Invoices are numbered INV-2026-0001 style.",
    "our mobile api are written in kotlin", "Production lives in eu-west-1.", "the cron runs hourly at minute 15",
])
def test_lasting_facts_in_any_style_are_learned(text):
    assert message_facts(text), text


@needs_parser
@pytest.mark.parametrize("text", [
    "swap the icons on the toolbar", "i need the export to be faster", "could you tidy this up",
    "why the chart empty", "it crashes again", "I suspect the cache.", "the toolbar looks cramped",
    "maybe the queue could be the problem", "I will check it tonight", "great thanks", "cache it please",
    "is the queue fine or not", "the deploy failed",
])
def test_requests_questions_reactions_are_not_learned(text):
    assert message_facts(text) == [], text


@needs_parser
@pytest.mark.parametrize("text", [
    "last week i say tabs right why you put spaces", "the cart still empty what you remove from the store",
    "I gave you the schema already so why you guess the columns", "Before I said vitest but you wrote jest tests",
    "the script you edited broke the cron",
])
def test_remarks_on_what_the_assistant_did_are_not_learned(text):
    assert message_facts(text) == [], text


@needs_parser
@pytest.mark.parametrize("text", [
    "The worker retries when you kill it with SIGTERM", "We pin Node 20 so you can build on any machine",
    "you wrote jest tests but we test with vitest here", "I told you our queue is Kafka",
    "The files you upload are kept in S3 for 30 days", "The sidebar lists everything you star in Linear",
])
def test_generic_you_and_facts_told_to_the_assistant_are_learned(text):
    assert message_facts(text), text


@needs_parser
def test_a_question_word_about_what_the_assistant_does_asks_without_a_question_mark():
    assert grammar.asks("last week i say tabs right why you put spaces")
    assert grammar.asks("the cart still empty what you remove from the store")
    assert not grammar.asks("The worker retries when you kill it with SIGTERM")
    assert not grammar.asks("We pin Node 20 so you can build on any machine")


@needs_parser
def test_fact_inside_a_request_is_kept_without_the_request():
    got = message_facts("tidy up the worker since our queue is Kafka")
    assert got and "Kafka" in got[0] and "tidy" not in got[0].lower()


@needs_parser
def test_scope_by_subject_not_by_the_word_i():
    assert scope_for("I bumped the API client to 4.2.", "shop") == "shop"     # an action on the project
    assert scope_for("I prefer tabs over spaces.", "shop") == ""             # about the user
    assert scope_for("Spanish is my first language.", "shop") == ""
    assert scope_for("The worker queue is Kafka.", "shop") == "shop"


def test_updates_any_verb_and_reworded_change():
    assert replaces("We host the docs on Netlify.", "We host the docs on Vercel now.")
    assert replaces("Builds target Node 18.", "Builds target Node 20.")
    assert replaces("Our CI is Jenkins.", "We switched our CI to GitHub Actions.")
    # keep both
    assert not replaces("We use black for formatting.", "We use mypy for typing.")
    assert not replaces("The invoice is due on Monday.", "I mailed the invoice to Sok.")
    assert not replaces("Alice owns the billing service.", "Bob owns the billing service.")
    assert not replaces("I have a cat named Pepper.", "I have a cat named Salt.")
    assert not replaces("We shipped release 3.1 on Monday.", "We shipped release 3.2 on Monday.")  # events


def test_time_words_are_not_embedded():
    assert embed_text("Our CI is GitHub Actions now.") == "Our CI is GitHub Actions."
    assert embed_text("now") == "now"


@needs_parser
@pytest.mark.parametrize("text", [
    "pleese update the footer", "the footer and header are should be fix for me plz",   # politeness, any spelling
    "the cache is warm by now, right", "staging is fine or not",                       # questions as statements
    "Because the export is slow on big files", "when i press back the page reload",    # hang off something said before
    "I added it to my bashrc", "i wnat dark mode on reports", "I should restart the worker",
    "git pull && npm run build", "zsh: yarn: command not found", "Total · 3 items · paid",
    "the report page will have a filter and the export will show totals for each month of the year too",  # wanted
])
def test_more_non_facts_in_real_world_styles(text):
    assert message_facts(text) == [], text


@needs_parser
def test_fact_kept_from_polite_or_question_sentences():
    assert message_facts("we deploy with Ansible, so please check the playbook")[0].startswith("We deploy with Ansible")
    got = message_facts("is this alert right for me because currently i use go, postgres, redis... but is it urgent or not")
    assert got and "postgres" in got[0] and "urgent" not in got[0]


def test_text_claude_wrote_is_not_learned_again():
    from dore.integrations.hooks import not_echoed
    claude = "The importer retries three times before it gives up, then writes the row to the dead-letter table."
    pasted = ["The importer retries three times before it gives up", "Our importer runs on Lambda"]
    assert not_echoed(pasted, claude) == ["Our importer runs on Lambda"]


def test_generic_note_does_not_crowd_out_the_answer():
    from dore.memory import MemoryStore
    from dore.memory.embed import HashEmbedder
    import tempfile
    from pathlib import Path
    s = MemoryStore(Path(tempfile.mkdtemp()) / "m.db", None, HashEmbedder())
    s.add("Jobs go through Kafka", trust="verified", project="p")
    s.add("How do I set this up? What version are we on? Where is the config file?", trust="verified", project="p")
    hits = s.search("Which queue do jobs go through?", k=2, project="p", touch=False)
    assert hits[0].content == "Jobs go through Kafka" and hits[0].focus >= hits[-1].focus


def test_reworded_updates_with_a_change_word():
    from dore.memory.rules import changes
    assert changes("Our CI runs on Jenkins.", "We moved CI to Buildkite.")
    assert changes("The dev database port is 5432", "we switched the database port to 6543")
    assert changes("Emails go through Mailgun.", "emails are sent with Postmark now")
    # keep both
    assert not changes("The web-api pod has 2 replicas.", "The web-worker pod now has 4 replicas.")   # other name
    assert not changes("Our CI runs on Jenkins.", "We moved the docs to Netlify.")                  # other thing
    assert not changes("We have a staging cluster in Frankfurt.", "We have a staging cluster in Oregon now.")  # multi
    assert not changes("Our CI runs on Jenkins.", "Our CI is fast.")                                # no change word


@needs_parser
def test_recheck_archives_old_junk_but_keeps_facts_and_standing_rules(tmp_path):
    from dore.learn.recheck import recheck
    from dore.memory import MemoryStore
    from dore.memory.embed import HashEmbedder
    s = MemoryStore(tmp_path / "m.db", None, HashEmbedder())
    keep = ["Our worker queue is Kafka.", "Never push straight to main.", "I use a Kinesis 360 keyboard."]
    junk = ["now enable it and put it on the status bar too", "● Agents   Claude · Cursor", "why the deploy slow or not"]
    ids = {t: s.add(t, kind="statement", source="user", trust="verified", project="p") for t in keep + junk}
    p = s.add("● pinned UI line", kind="statement", source="user", trust="verified", protected=True)
    found = {i for i, _ in recheck(s, apply=True)}
    assert found == {ids[t] for t in junk}
    assert all(not s.get(ids[t]).archived for t in keep) and not s.get(p).archived
    assert all(s.get(ids[t]).archived for t in junk)  # archived, not deleted


@needs_parser
def test_standing_dont_and_promotion_to_general(tmp_path):
    from dore.integrations.hooks import save_facts
    from dore.memory import MemoryStore
    from dore.memory.embed import HashEmbedder
    assert message_facts("please don't rewrite comments you did not change")
    assert message_facts("i don't want the bot to post on weekends")
    assert message_facts("don't change the code right now") == [] and message_facts("please do not touch it") == []
    s = MemoryStore(tmp_path / "m.db", None, HashEmbedder())
    save_facts(s, ["Don't rewrite comments you did not change"], "shop")
    [b] = save_facts(s, ["Don't rewrite comments you did not change."], "blog")   # a second project
    assert s.get(b).project == ""                                                 # now general
    save_facts(s, ["The database is PostgreSQL 16"], "shop")
    [d] = save_facts(s, ["The database is PostgreSQL 16."], "blog")
    assert s.get(d).project == "blog"                                             # values never move


def test_long_instruction_kept_as_hidden_requirement(tmp_path):
    from dore.integrations.hooks import _State, on_prompt
    from dore.learn.statements import requirement_text
    from dore.memory import MemoryStore
    from dore.memory.embed import HashEmbedder
    long_msg = ("i want the export to keep every column the user picked and not drop empty ones, and also "
                "make sure the dates stay in the user's own timezone")
    assert "not drop empty ones" in requirement_text(long_msg)
    assert requirement_text("why is the export so slow when i pick many columns at the same time today") == ""
    s = MemoryStore(tmp_path / "m.db", None, HashEmbedder())
    on_prompt(s, long_msg, "p", _State(tmp_path, "a"))
    [r] = s.db.execute("SELECT id, trust FROM memories WHERE kind='requirement' AND source='user'").fetchall()
    assert r[1] == "unverified"                                   # kept, low trust
    assert "export" not in on_prompt(s, "the export columns", "p", _State(tmp_path, "b"))  # not shown yet
    on_prompt(s, long_msg + ".", "p", _State(tmp_path, "c"))       # said again
    assert s.get(r[0]).trust == "verified" and s.db.execute(
        "SELECT count(*) FROM memories WHERE kind='requirement' AND source='user'").fetchone()[0] == 1  # not doubled


def test_broken_fragments_are_not_notes():
    from dore.learn.grammar import complete
    from dore.learn.statements import message_facts
    for broken in ["My purpose is that", "I don't need the parser i", "The config lives in (the repo",
                   "The app has caching not"]:
        assert not complete(broken), broken
    for whole in ["We turn the cache off", "You can't get the money back", "The API runs on port 8080"]:
        assert complete(whole), whole
    # a time like 11:05 is one word: never cut into "05 AM now are 13"
    assert message_facts("after the manual run at 11:05 AM now it is 13:34 PM but no job ran, please check") == []


def test_rule_inside_long_request_verified_when_repeated_in_other_words(tmp_path):
    from dore.integrations.hooks import RULE_SOURCE, _State, on_prompt
    from dore.learn.grammar import rule_cores
    from dore.memory import MemoryStore
    from dore.memory.embed import HashEmbedder
    assert rule_cores("please review the payment flow again and do not touch the old code since it is sensitive")
    assert rule_cores("i don't want to update code right now, just tell me") == []      # tied to the moment
    assert rule_cores("is it fast or not? i don't think so") == []                      # question, a thought
    s = MemoryStore(tmp_path / "m.db", None, HashEmbedder())
    q = "SELECT trust FROM memories WHERE source=?"
    on_prompt(s, "please review the payment flow again and check the totals, and do not touch the old code",
              "p", _State(tmp_path, "a"))
    assert [r[0] for r in s.db.execute(q, (RULE_SOURCE,))] == ["unverified"]          # hidden at first
    on_prompt(s, "the refund screen has a bug with rounding on totals, fix it but do not touch the old code",
              "p", _State(tmp_path, "b"))
    assert [r[0] for r in s.db.execute(q, (RULE_SOURCE,))] == ["verified"]            # repeated: shown


@needs_parser
def test_verbless_my_phrase_is_about_the_user():
    from dore.learn.statements import scope_for
    for mine in ["my brother name Rithy", "my hometown kampot", "My boss name Sokha", "my car model Toyota Vios"]:
        assert scope_for(mine, "p") == "", mine
    for other in ["His name King", "the staging port 8443", "the repo name dore-api"]:
        assert scope_for(other, "p") == "p", other


@needs_parser
def test_reports_and_questions_are_not_rules():
    from dore.learn.grammar import rule_cores
    from dore.learn.statements import requirement_text
    # A report about a thing, an "or not" tag, a rule pointing only at "it": no hidden rule.
    assert rule_cores("the export still not work on safari, it not download the file when i click") == []
    assert rule_cores("please run the migration and check the table get the new column or not") == []
    assert rule_cores("thanks, i dont want to change it, the old one was fine for the team") == []
    # Real rules, any subject that says how things should be, stay.
    assert rule_cores("we do not deploy on fridays because nobody is around to fix the release")
    assert rule_cores("the bot should never send me debug logs at night, only critical ones")
    assert rule_cores("please never commit secrets to it, we had a leak last year") == ["Never commit secrets"]
    assert rule_cores("never rename the columns, it breaks the reports for finance") == ["Never rename the columns"]
    assert rule_cores("i dont want to touch it seem fine to me if you use something else") == []
    # A long message that asks is not a standing instruction.
    assert requirement_text("i was thinking about the menu so should we move it to the left side or not, "
                            "i am not sure about the layout") == ""


def test_repeat_inside_one_session_does_not_verify(tmp_path):
    from dore.integrations.hooks import _State, on_prompt
    from dore.memory import MemoryStore
    from dore.memory.embed import HashEmbedder
    s = MemoryStore(tmp_path / "m.db", None, HashEmbedder())
    msg = ("i want the export to keep every column the user picked and not drop empty ones, and also "
           "make sure the dates stay in the user's own timezone")
    st = _State(tmp_path, "one")
    on_prompt(s, msg, "p", st)
    on_prompt(s, msg + ".", "p", st)                                     # pressing the same task
    q = "SELECT DISTINCT trust FROM memories WHERE kind='requirement'"
    assert [r[0] for r in s.db.execute(q)] == ["unverified"]
    on_prompt(s, msg, "p", _State(tmp_path, "dup"))                     # same text again at once: one message twice
    assert [r[0] for r in s.db.execute(q)] == ["unverified"]
    on_prompt(s, msg + "!", "p", _State(tmp_path, "two"))                # another session: lasting
    assert "verified" in [r[0] for r in s.db.execute(q)]


@needs_parser
def test_topic_key_names_the_topic_not_the_value():
    # New sentences, any style: the label is the common nouns; names, numbers and unknown words are values.
    assert grammar.topic_key("we keep the invoices in a bucket called acct-files").startswith("invoice, bucket:")
    assert grammar.topic_key("My favourite shell is Fish.").startswith("shell:")
    assert grammar.topic_key("i prefer tiny commits").startswith("commit:")
    # No common noun and no place: no key (the note is searched by its own vector only).
    assert grammar.topic_key("We ship with Bun.") is None
    assert grammar.topic_key("Dara is on leave.") is not None  # "leave" is the topic
    # A place value: the key is the "Where …?" question the note answers.
    assert grammar.topic_key("i stay in Battambang").startswith("Where do I stay?")
    assert grammar.topic_key("The backups are kept in Wasabi").startswith("Where are the backups kept?")
    assert grammar.topic_key("my sister works at ACLEDA").startswith("Where does my sister work?")
    for no_place in ["We use jest in this project", "The API runs on port 9000", "I fixed the bug in the parser"]:
        assert not (grammar.topic_key(no_place) or "").startswith("Where"), no_place


def test_update_that_names_the_old_value_it_left():
    assert changes("Our CI runs on Travis.", "ci is github actions now, we moved off travis")
    assert changes("I draw diagrams in Visio.", "i draw them in excalidraw now instead of visio")
    assert changes("We bundle with Rollup.", "we switched from rollup to esbuild")
    # Look-alikes that must keep both: another thing left the value, or another value was left.
    assert not changes("Our docs are on Confluence.", "The weekly status report moved off Confluence to Notion.")
    assert not changes("We log with Loki.", "We use Grafana instead of Kibana for dashboards.")
    assert not changes("The cache is Redis.", "we moved the session store off Memcached")
    assert not changes("Standup is on Monday.", "I moved the meeting from Monday.")  # "from X" alone


def test_topic_key_vector_is_searched_kept_in_step_and_backfilled(tmp_path):
    from dore.memory import MemoryStore
    from dore.memory.embed import HashEmbedder
    s = MemoryStore(tmp_path / "m.db", tmp_path / "m.faiss", HashEmbedder())
    a = s.add("I prefer short answers.", kind="statement", trust="verified", key="answer length: short answers")
    b = s.add("Logs live in /var/log/app.", kind="statement", trust="verified")  # no key given: backfill later
    assert s.key_index.ntotal == 1
    hit = s.search("answer length", k=1, min_similarity=0.0, keyword=False)[0]
    assert hit.id == a and hit.similarity == pytest.approx(
        float(s._key_vector(a) @ s.embedder.embed(["answer length"])[0]), abs=1e-5)
    assert [i for i, _ in s.missing_keys()] == [b]
    s.set_keys([(b, "log, path: Logs live in /var/log/app.")])
    assert s.missing_keys() == [] and s.key_index.ntotal == 2
    s.archive(a)
    assert s.key_index.ntotal == 1  # archived notes leave both indexes
    s.restore(a)
    s.save(force=True)
    s.close()
    s2 = MemoryStore(tmp_path / "m.db", tmp_path / "m.faiss", HashEmbedder())
    assert s2.key_index.ntotal == 2 and (tmp_path / "m.keys.faiss").exists()  # saved with the main index
    s2.close()


def test_two_clauses_with_their_own_subjects_are_two_facts():
    from dore.learn.statements import user_facts
    assert user_facts("the api is on port 3000 and the worker is on port 3001") == [
        "The api is on port 3000", "The worker is on port 3001"]
    assert user_facts("the queue is SQS and the cache is Redis") == ["The queue is SQS", "The cache is Redis"]
    assert user_facts("I have a dog and a cat") == ["I have a dog and a cat"]
    assert user_facts("we use Postgres and it runs on RDS") == ["We use Postgres and it runs on RDS"]


def test_a_judgement_half_is_kept_only_when_it_parallels_a_value():
    from dore.learn.statements import user_facts
    near, far = (lambda a, b: 0.72), (lambda a, b: 0.5)
    assert user_facts("the frontend is react and the backend is django", near) == [
        "The frontend is react", "The backend is django"]
    assert user_facts("the frontend is react and the backend is django", far) == ["The backend is django"]
    assert user_facts("the page is slow and the api is on port 3000") == ["The api is on port 3000"]


def test_a_side_clause_before_the_fact_is_dropped():
    from dore.learn.statements import user_facts
    assert user_facts("heads up, the db is postgres 16") == ["The db is postgres 16"]
    assert user_facts("quick note, we use pnpm") == ["We use pnpm"]
    assert user_facts("Locally, the app listens on 3001") == ["Locally, the app listens on 3001"]
    assert user_facts("In production, the api runs on port 443") == ["In production, the api runs on port 443"]


def test_an_instruction_is_known_by_its_form_not_its_words():
    """`grammar.instruction`: commands with never/always/don't and the user's own standing way are instructions;
    descriptions, events, plain commands, questions and states of mind are not (DEV, then HELDOUT wording)."""
    from dore.learn.grammar import instruction
    yes = ["never use tabs, always 2 spaces", "Never use tabs in this repo, always 2 spaces",
           "please don't reformat existing code", "I prefer short answers", "I don't want ai to summary any thing",
           "we always squash commits before merging", "Do not just assume", "always pin dependency versions",
           "I like to write small functions", "Rule 1: always keep the code python 3.9 compatible",
           "Note: we never deploy on fridays",
           # HELDOUT
           "never log personal data", "don't touch the migrations folder", "I like to keep pull requests small",
           "we usually write the docs in markdown", "I never use semicolons in javascript"]
    no = ["We decided to keep the cart in redis", "Finance decided the max discount is 50%", "the upload limit is 10 MB",
          "commit this for me", "can you never use tabs?", "the api runs on port 8080", "I moved the dev server to 3001",
          "tests are required for every endpoint", "I don't know why it fails", "I like jazz music",
          "I think we never deploy on fridays", "FYI: the api runs on port 8080", "I didn't use docker",
          "because I don't use the right tool", "if we never test it, it breaks",
          # HELDOUT
          "the board has 8MB of psram", "we trained the model for 3 epochs", "the max batch size is 64",
          "restart the service", "I don't think this is right", "I love the new logo"]
    assert [t for t in yes if not instruction(t)] == []
    assert [t for t in no if instruction(t)] == []


def test_here_is_the_codebase_only_when_the_sentence_is_not_about_the_user():
    from dore.learn.statements import scope_for
    assert scope_for("I live here in Phnom Penh", "shop") == ""            # the user's, in every project
    assert scope_for("Here we never push straight to main", "shop") == "shop"
    assert scope_for("In this repo I always use tabs", "shop") == "shop"   # the codebase named


@needs_parser
def test_a_polite_word_glued_to_the_previous_one_ends():
    assert message_facts("the cron has stopped running.pls restart the box tonight") is not None


@needs_parser
def test_setup_said_in_a_second_project_becomes_the_users(tmp_path):
    from dore.learn.statements import promoted
    from dore.memory import MemoryStore
    from dore.memory.embed import HashEmbedder
    s = MemoryStore(tmp_path / "m.db", None, HashEmbedder())
    for text in ("I build with bun", "The queue is RabbitMQ", "I lint with ruff"):
        s.add(text, kind="statement", source="user", trust="verified", project="shop")
    assert promoted(s, "I build with bun", "I build with bun", "blog")           # the user's own setup, twice
    assert not promoted(s, "I build with bun", "I build with bun", "shop")       # the same project again
    assert not promoted(s, "The queue is RabbitMQ", "The queue is RabbitMQ", "blog")  # a value shared by chance
    assert not promoted(s, "I lint with flake8", "I lint with flake8", "blog")   # another tool


@needs_parser
def test_with_haiku_a_long_message_leaves_no_hidden_word_rule_notes(tmp_path):
    from dore.integrations.hooks import _State, on_prompt
    from dore.memory import MemoryStore
    from dore.memory.embed import HashEmbedder
    s = MemoryStore(tmp_path / "m.db", None, HashEmbedder())
    msg = ("the report page should show totals without refunded orders, and do not touch the old csv exporter "
           "because finance still uses it every month for the audit")
    on_prompt(s, msg, "p", _State(tmp_path, "h"), learn="haiku")
    assert s.db.execute("SELECT count(*) FROM memories WHERE kind='requirement'").fetchone()[0] == 0
    assert s.db.execute("SELECT count(*) FROM episodes").fetchone()[0] >= 1  # waits for Haiku
    w = MemoryStore(tmp_path / "w.db", None, HashEmbedder())
    on_prompt(w, msg, "p", _State(tmp_path, "r"), learn="rules")  # word rules alone (checks) still keep the gist
    assert w.db.execute("SELECT count(*) FROM memories WHERE kind='requirement'").fetchone()[0] >= 1
