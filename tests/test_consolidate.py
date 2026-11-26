"""Consolidation by a batched judge (`learn.judge`, `learn.consolidate`), with a fake judge: no tokens."""

from dore.learn.consolidate import Said, consolidate, sentences
from dore.learn.judge import CONFIRM, SYSTEM, Item, Recorded, confirm_updates, grounded, parse
from dore.memory import MemoryStore
from dore.memory.embed import HashEmbedder


class Fake:
    """Answers the batch with `lines` (and the update check with `confirm`), recording what it was asked."""

    def __init__(self, lines="", confirm=""):
        self.lines, self.confirm, self.asked = lines, confirm, []

    def __call__(self, prompt, system=SYSTEM):
        self.asked.append((system, prompt))
        return (self.confirm if system == CONFIRM else self.lines), {"input": 1, "output": 1, "usd": 0.0}


def store(tmp_path):
    return MemoryStore(tmp_path / "m.db", None, HashEmbedder())


def test_shape_filter_keeps_statements_not_questions_code_or_one_word_replies():
    msg = "yes\nok do it\nThe api runs on port 8080. Can you check the logs?\nfoo = bar(x) {y}; z[0] = 1"
    assert sentences(msg) == ["ok do it", "The api runs on port 8080."]


def test_answer_lines_with_unknown_ids_or_lines_are_dropped():
    items = [Item(1, "a b c", [(7, "old")]), Item(2, "d e f")]
    v = parse("1 same #99\n1 update #7 project: New value 2.\n3 fact user: invented\n2 skip", items)
    assert [x.action for x in v[1]] == ["update"] and v[1][0].ref == 7 and v[2][0].action == "skip" and 3 not in v


def test_a_note_may_not_name_what_the_user_never_said():
    assert grounded("The API runs on port 8080.", "the api runs on port 8080")
    assert not grounded("The API runs on port 9443.", "the api runs on port 8080")


def test_an_update_needs_a_second_no_or_both_notes_stay():
    items = [Item(1, "dog Max", [(4, "I have a dog called Buddy.")])]
    for confirm, kept in (("1 no", "update"), ("1 yes", "fact"), ("", "fact")):
        v = parse("1 update #4 user: I have a dog called Max.", items)
        v, _ = confirm_updates(v, items, Fake(confirm=confirm))
        assert v[1][0].action == kept


def test_facts_rules_and_scope(tmp_path):
    s = store(tmp_path)
    ask = Fake("1 fact project: The API runs on port 8080.\n2 rule user: Keep answers short. | when: answer | not:\n"
               "3 skip")
    st = consolidate(s, [Said("the api runs on port 8080", "shop", "a", 1.0),
                         Said("always keep your answers short", "shop", "a", 1.0),
                         Said("please fix the footer typo", "shop", "a", 1.0)], ask)
    notes = {m.content: m for m in s.get_many(list(range(1, 10))).values()}
    assert notes["The API runs on port 8080."].project == "shop"
    assert notes["Keep answers short."].project == "" and s.is_rule(notes["Keep answers short."].id)
    assert st["skipped"] == 1 and len(notes) == 2


def test_said_again_counts_once_per_session_in_any_words(tmp_path):
    s = store(tmp_path)
    consolidate(s, [Said("never push straight to main", "p", "a", 1.0)], Fake("1 rule project: Never push to main."))
    i = s.same_words("Never push to main.", "p")
    consolidate(s, [Said("dont push to main ok", "p", "a", 2.0)], Fake(f"1 same #{i}"))  # same session: no count
    assert s.get(i).times_seen == 1
    hits = s.search("Never push to main.", k=1, project="p", touch=False)
    assert hits and hits[0].id == i
    consolidate(s, [Said("main is protected, never push there", "p", "b", 3.0)], Fake(f"1 same #{i}"))
    assert s.get(i).times_seen == 2  # another session, other words: the repeat counts


def test_same_line_in_one_batch_is_one_note(tmp_path):
    s = store(tmp_path)
    st = consolidate(s, [Said("we use pnpm", "p", "a", 1.0), Said("we use pnpm!", "p", "a", 1.0)],
                     Fake("1 fact project: We use pnpm.\n2 same @1"))
    assert st["notes"] == 1 and s.get(st["lines"][1][0]).times_seen == 1


def test_a_project_update_of_a_general_note_hides_it_only_there(tmp_path):
    s = store(tmp_path)
    old = s.add("Deploys go to Heroku.", kind="statement", source="user", trust="verified", project="")
    s.replace(old, s.add("Deploys go to Render.", kind="statement", trust="verified", project="blog"),
              project_only="blog")
    assert s.get(old).replaced_by is None
    assert old not in [m.id for m in s.search("Deploys go to Heroku.", k=3, project="blog", touch=False)]
    assert old in [m.id for m in s.search("Deploys go to Heroku.", k=3, project="shop", touch=False)]


def test_recorded_answers_cost_nothing_the_second_time(tmp_path):
    inner = Fake("1 skip")
    ask = Recorded(tmp_path / "answers.json", inner)
    ask("1: hello there friend")
    _, usage = Recorded(tmp_path / "answers.json")("1: hello there friend")
    assert len(inner.asked) == 1 and usage.get("recorded")


def test_dores_own_judge_session_never_runs_dores_hooks(monkeypatch, capsys):
    from dore.integrations import hookclient
    from dore.learn import judge
    assert hookclient.SKIP_ENV == judge.SKIP_ENV
    monkeypatch.setenv(judge.SKIP_ENV, "1")
    monkeypatch.setattr("sys.stdin", None)  # would fail if it tried to read the event
    hookclient.main(["prompt"])
    assert capsys.readouterr().out == ""


def queue(s, texts, project="p", session="a", created=None):
    from dore.memory import episodes
    return episodes.add(s, texts, project, session, created=created)


def test_a_batch_runs_only_when_due_and_marks_what_was_judged(tmp_path):
    from dore.integrations import learner
    s = store(tmp_path)
    queue(s, ["the api runs on port 8080"])
    assert not learner.due(s)  # one fresh sentence: wait for more
    queue(s, [f"we keep config number {k} in vault" for k in range(29)])
    assert learner.due(s)
    st = learner.run_once(s, Fake("1 fact project: The API runs on port 8080."))
    assert st["notes"] == 1 and learner.queued(s) == []
    assert not learner.due(s)


def test_an_old_sentence_is_due_alone(tmp_path):
    from dore.integrations import learner
    s = store(tmp_path)
    queue(s, ["the api runs on port 8080"], created=1.0)
    assert learner.due(s)


def test_a_failed_call_keeps_the_queue_and_backs_off(tmp_path):
    from dore.integrations import learner
    from dore.learn.judge import JudgeError
    s = store(tmp_path)
    queue(s, ["the api runs on port 8080"], created=1.0)

    def limit(prompt, system=SYSTEM):
        raise JudgeError("limit", "usage limit reached", retry_at=4102444800.0)
    assert learner.run_once(s, limit) is None
    assert len(learner.queued(s)) == 1 and not learner.due(s)  # waits until the limit resets
    import json
    assert json.loads(s.meta("learner"))["next_try"] >= 4102444800


def test_the_daily_token_cap_stops_more_calls(tmp_path):
    import json
    import time
    from dore.integrations import learner
    s = store(tmp_path)
    queue(s, ["the api runs on port 8080"], created=1.0)
    s.meta("learner", json.dumps({"day": time.strftime("%Y-%m-%d"), "tokens": learner.DAILY_TOKENS}))
    assert not learner.due(s)


def test_haiku_learner_end_to_end_queue_batch_then_recall(tmp_path, monkeypatch):
    from dore.integrations import hooks, learner
    s = store(tmp_path)
    st = hooks._State(tmp_path, "one")
    out = hooks.on_prompt(s, "the staging api runs on port 8443", "shop", st, learn="haiku")
    assert out == "" and s.db.execute("SELECT count(*) FROM memories").fetchone()[0] == 0  # nothing judged yet
    for k in range(29):
        hooks.on_prompt(s, f"please rename variable number {k} in cart", "shop", st, learn="haiku")
    monkeypatch.setattr(learner, "ClaudeCLI", lambda: Fake("1 fact project: The staging API runs on port 8443."))
    hooks.consolidate(s, learn="haiku", wait=True)
    assert learner.queued(s) == []
    shown = hooks.prompt_context(s, "what port does the staging api run on?", "shop", hooks._State(tmp_path, "two"))
    assert "8443" in shown
    hooks.on_prompt(s, "the staging api runs on port 8443", "shop", hooks._State(tmp_path, "three"), learn="haiku")
    m = s.get(s.same_words("The staging API runs on port 8443.", "shop"))
    assert m.times_seen == 2  # the same sentence in another session: counted at once, no model


def test_session_end_queues_what_the_prompt_hook_missed(tmp_path):
    import json
    from dore.integrations import hooks, learner
    s = store(tmp_path)
    log = tmp_path / "t.jsonl"
    log.write_text(json.dumps({"type": "user", "message": {"content": "our deploys go through render"}}))
    hooks.save_session(s, log, "shop", learn="haiku")
    assert [r[1] for r in learner.queued(s)] == ["our deploys go through render"]


def test_haiku_runs_with_every_hook_off_and_no_tools():
    import json
    from dore.learn.judge import CLI_FLAGS
    settings = json.loads(CLI_FLAGS[CLI_FLAGS.index("--settings") + 1])
    assert settings["disableAllHooks"] is True  # any installed dore (old ones too) must not learn its prompt
    assert CLI_FLAGS[CLI_FLAGS.index("--tools") + 1] == "" and "--strict-mcp-config" in CLI_FLAGS
