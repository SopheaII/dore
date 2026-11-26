"""Raw memory: nothing the user types is lost, and a fixed rule also learns what was said before it.
Sentences here are new (not from src/eval/cases.py)."""

import json

import pytest

from dore.integrations.hooks import RULES_VERSION, _State, consolidate, on_prompt
from dore.memory import MemoryStore, episodes
from dore.memory.embed import HashEmbedder

grammar = pytest.importorskip("dore.learn.grammar")
needs_parser = pytest.mark.skipif(grammar.nlp() is None, reason="spaCy model not installed")


def make(tmp_path):
    return MemoryStore(tmp_path / "m.db", None, HashEmbedder())


def rows(s, sql):
    return s.db.execute(sql).fetchall()


@needs_parser
def test_preposition_at_the_end_of_a_describing_clause_is_a_whole_statement():
    from dore.eval.learning import learn
    got = learn("Kubernetes is the platform I deploy everything to.")
    assert got and got[0][1] == "general"                        # "I" in the clause: about the user
    assert learn("Haskell is the language our team argues about")  # a whole statement, any subject
    for piece in ("we are waiting for", "the bug is in", "I was going to ask about"):
        assert learn(piece) == [], piece                         # cut off on the main verb: not a note


@needs_parser
def test_past_action_in_the_describing_clause_stays_in_the_project():
    from dore.eval.learning import learn
    assert learn("Render is the host I deployed the blog to")[0][1] == "proj"   # an action on a thing
    assert learn("Kep is the town I grew up in")[0][1] == "general"              # about the user


def test_a_long_paste_on_one_line_is_not_kept_sentence_by_sentence():
    from dore.learn.statements import episode_sentences
    article = " ".join(f"The river number {i} floods every spring." for i in range(25))
    assert episode_sentences(article, []) == []


@needs_parser
def test_tells_is_a_statement_not_a_request_or_question():
    assert grammar.tells("the old printer only accepts A4 paper")
    assert grammar.tells("i don't want alerts on weekends")
    assert not grammar.tells("ok plese ship the build for me")   # polite, misspelt too
    assert not grammar.tells("so can we keep the old printer")   # asks
    assert not grammar.tells("ship the build tonight")           # no subject: a command


@needs_parser
def test_every_typed_sentence_that_is_not_a_note_is_kept_as_raw_memory(tmp_path):
    s = make(tmp_path)
    st = _State(tmp_path, "s1")
    on_prompt(s, "ok plese ship the build for me", "shop", st)             # a request: kept raw
    on_prompt(s, "which printer do we use?", "shop", st)                   # a question: asks, tells nothing
    on_prompt(s, "line one is here.\nline two is here.\nline three.", "shop", st)  # a paste
    on_prompt(s, "The receipt printer is an Epson TM-T20.", "shop", st)    # a fact: a note, not raw
    kept = [r[0] for r in rows(s, "SELECT content FROM episodes")]
    assert kept == ["ok plese ship the build for me"]
    assert rows(s, "SELECT session, vector, judged FROM episodes") == [("s1", None, RULES_VERSION)]  # text only


@needs_parser
def test_consolidation_learns_old_sentences_with_new_rules_dated_when_said(tmp_path):
    s = make(tmp_path)
    old = 1_700_000_000.0
    episodes.add(s, ["Kubernetes is the platform I deploy everything to"], "infra", "old", judged="older-rules",
                 created=old)
    episodes.add(s, ["ok plese ship the build for me"], "infra", "old", judged="older-rules", created=old)
    done = consolidate(s)
    assert done == {"embedded": 2, "judged": 2, "learned": 1, "remarked": 0}  # a new store: nothing to re-mark
    note = s.search("Which platform do I deploy to?", k=1)[0]
    assert note.content.startswith("Kubernetes") and note.created == old and note.project == ""
    assert rows(s, "SELECT note_id IS NOT NULL, told, scope FROM episodes ORDER BY id") == [(1, 1, ""), (0, 0, "infra")]
    assert consolidate(s) == {"embedded": 0, "judged": 0, "learned": 0, "remarked": 0}  # once per rules version


@needs_parser
def test_consolidation_never_brings_back_a_note_the_user_archived(tmp_path):
    s = make(tmp_path)
    nid = s.add("The receipt printer is an Epson TM-T20.", kind="statement", source="user", trust="verified",
                project="shop")
    s.archive(nid)
    episodes.add(s, ["the receipt printer is an Epson TM-T20"], "shop", "old", judged="older-rules")
    assert consolidate(s)["learned"] == 0
    assert rows(s, "SELECT count(*) FROM memories") == [(1,)]


@needs_parser
def test_a_fact_learned_later_never_replaces_a_newer_note(tmp_path):
    s = make(tmp_path)
    new = s.add("We deploy to Render.", kind="statement", source="user", trust="verified", project="blog",
                supersede=True)
    episodes.add(s, ["We deploy to Heroku."], "blog", "old", judged="older-rules", created=1_700_000_000.0)
    consolidate(s)
    old = [m for m in (s.get(i) for (i,) in rows(s, "SELECT id FROM memories")) if "Heroku" in m.content][0]
    assert s.get(new).replaced_by is None                 # the newer note stays
    assert old.replaced_by == new                         # the older fact is replaced by it (kept, not searched)


@needs_parser
def test_backfill_reads_old_session_logs_once(tmp_path, monkeypatch):
    import dore.integrations.backfill as backfill_mod
    from dore.integrations.backfill import backfill
    log = tmp_path / "logs" / "-home-me-shop"
    log.mkdir(parents=True)
    (tmp_path / "shop").mkdir()
    cwd = str(tmp_path / "shop")
    events = [{"type": "user", "cwd": cwd, "timestamp": "2026-10-01T09:00:00Z",
               "message": {"content": "Kubernetes is the platform I deploy everything to"}},
              {"type": "assistant", "message": {"content": [{"type": "text", "text":  # quotes the user afterwards
                  "Noted: Kubernetes is the platform I deploy everything to."}]}},
              {"type": "user", "cwd": cwd, "timestamp": "2026-10-01T09:05:00Z",
               "message": {"content": "ok plese ship the build for me"}}]
    (log / "abc.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    monkeypatch.setattr(backfill_mod, "TEMP_ROOTS", set())  # tmp_path stands in for a real project folder here
    s = make(tmp_path)
    dry = backfill(s, apply=False, root=tmp_path / "logs")
    assert dry["new_facts"] == 1 and dry["facts"][0].startswith("Kubernetes")       # listed for the user to read
    assert (dry["sessions"], dry["sentences"]) == (1, 2) and rows(s, "SELECT count(*) FROM episodes") == [(0,)]
    backfill(s, apply=True, root=tmp_path / "logs")
    assert [m.content for m in s.search("Which platform do I deploy to?", k=1)][0].startswith("Kubernetes")
    assert backfill(s, apply=True, root=tmp_path / "logs")["sessions"] == 0  # a second run changes nothing


@needs_parser
def test_backfill_still_reads_a_session_the_prompt_hook_joined_halfway(tmp_path, monkeypatch):
    import dore.integrations.backfill as backfill_mod
    from dore.integrations.backfill import backfill
    log = tmp_path / "logs" / "-home-me-shop"
    log.mkdir(parents=True)
    (tmp_path / "shop").mkdir()
    cwd = str(tmp_path / "shop")
    said = ["Kubernetes is the platform I deploy everything to", "ok plese ship the build for me"]
    (log / "s9.jsonl").write_text("\n".join(json.dumps(
        {"type": "user", "cwd": cwd, "timestamp": f"2026-10-01T09:0{i}:00Z", "message": {"content": m}})
        for i, m in enumerate(said)))
    monkeypatch.setattr(backfill_mod, "TEMP_ROOTS", set())
    s = make(tmp_path)
    episodes.add(s, [said[1]], "shop", "s9", judged=RULES_VERSION)  # the hook went live after the first message
    r = backfill(s, apply=True, root=tmp_path / "logs")
    assert (r["sessions"], r["sentences"], r["new_facts"]) == (1, 1, 1)   # the first half is not lost
    assert s.db.execute("SELECT times_seen FROM episodes WHERE content=?", (said[1],)).fetchone() == (1,)  # not counted twice
    assert s.search("Which platform do I deploy to?", k=1)[0].content.startswith("Kubernetes")


def test_backfill_skips_test_runs_in_temp_folders(tmp_path):
    from dore.integrations.backfill import backfill
    log = tmp_path / "logs" / "-tmp-scratch"
    log.mkdir(parents=True)
    (log / "t.jsonl").write_text(json.dumps({"type": "user", "cwd": str(tmp_path), "timestamp": "2026-10-01T09:00:00Z",
                                             "message": {"content": "My cat is called Biscuit"}}))
    assert backfill(make(tmp_path), apply=True, root=tmp_path / "logs")["sessions"] == 0  # pytest's tmp is a temp folder
