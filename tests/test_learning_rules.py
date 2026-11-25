"""What is learned from any writing style: grammar gate, paste shapes, scope, updates.
Sentences here are new (not from src/eval/cases.py), so these tests also check generalisation."""

import pytest

from dore.learn.statements import message_facts, scope_for, structured_line
from dore.memory.rules import embed_text, replaces

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
