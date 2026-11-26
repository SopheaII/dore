"""Standing rules come to mind like a habit (`memory.activation`): strength from repeats and uses, fading with time,
no fixed number; a session start reads only rule notes, marked once when saved."""

import time

from dore.integrations.hooks import _State, prompt_context
from dore.memory import MemoryStore
from dore.memory.activation import DAY, THRESHOLD, strength
from dore.memory.embed import HashEmbedder

NOW = 1_800_000_000.0


def ago(days):
    return NOW - days * DAY


def make(tmp_path):
    return MemoryStore(tmp_path / "m.db", None, HashEmbedder())


def rule(s, text, said=2, days_ago=1.0, project="p"):
    """A proven rule (said `said` times), last said `days_ago` days ago."""
    from dore.integrations.hooks import mark_instructions
    i = s.add(text, kind="statement", source="user", trust="verified", project=project)
    mark_instructions(s, [i])
    t = time.time() - days_ago * DAY
    s.db.execute("UPDATE memories SET times_seen=?, created=?, last_seen=? WHERE id=?", (said, t, t, i))
    s.db.commit()
    return i


def test_strength_grows_with_repeats_and_fades_with_time():
    assert strength(1, ago(0), ago(0), NOW) > THRESHOLD           # just said
    assert strength(1, ago(40), ago(40), NOW) < THRESHOLD         # said once, long ago: faded
    assert strength(2, ago(100), ago(100), NOW) > THRESHOLD       # said twice: lasts longer
    assert strength(5, ago(730), ago(365), NOW) > THRESHOLD       # said often: fades slowly (spacing effect)
    assert strength(5, ago(10), ago(1), NOW) > strength(2, ago(10), ago(1), NOW)


def test_no_fixed_number_of_rules_none_cut_one_budget_per_session(tmp_path):
    s = make(tmp_path)
    # Short rules: how many fit is set by the token ceiling, not a count (12 of these fit; long ones fewer).
    texts = [f"never import module m{k}" for k in range(12)] + [
        f"always prefer the standard library over package number {k} when both can do the job" for k in range(6)]
    for t in texts:
        rule(s, t)
    st = _State(tmp_path, "a")
    first = prompt_context(s, "rename a variable", "p", st)
    n_first = sum(t in first for t in texts)
    assert n_first > 6                                    # more than the old fixed 6
    assert "…" not in first                               # a rule is never cut
    rest = "".join(prompt_context(s, f"small change {k}", "p", st) for k in range(4))
    shown = first + rest
    from dore.integrations.hooks import RULES_PER_SESSION
    rule_chars = sum(len(line) + 1 for line in shown.splitlines() if line.startswith("- #"))
    assert rule_chars <= RULES_PER_SESSION                # one budget per session (the old block's most)
    assert not any(t in rest for t in texts)              # the rest wait for a message that matches them


def test_a_faded_rule_does_not_start_sessions_but_search_still_finds_it(tmp_path):
    s = make(tmp_path)
    rule(s, "never deploy on fridays", said=2, days_ago=400)
    assert "fridays" not in prompt_context(s, "rename a variable", "p", _State(tmp_path, "a"))
    assert "fridays" in prompt_context(s, "can we deploy on fridays?", "p", _State(tmp_path, "b"))


def test_instructions_are_marked_by_form_when_saved_and_old_notes_once(tmp_path):
    from dore.integrations.hooks import RULE_FORM, on_prompt, remark_instructions
    s = make(tmp_path)
    on_prompt(s, "never push straight to main", "p", _State(tmp_path, "a"))
    on_prompt(s, "we decided to keep the cart in redis", "p", _State(tmp_path, "b"))  # an event: a fact
    assert [m.content for m in s.rule_notes("p")] == ["Never push straight to main"]
    # notes saved by an older version: marked once by their form, then never re-read at a start
    old = s.add("always pin dependency versions", trust="verified", project="p")
    s.meta("rule_form", "old")
    while remark_instructions(s, limit=1):  # a little at a time, while idle
        pass
    assert old in [m.id for m in s.rule_notes("p")] and s.meta("rule_form") == RULE_FORM
    s.close()

def test_a_repeat_in_the_same_session_does_not_prove_a_rule(tmp_path):
    from dore.integrations.hooks import on_prompt
    s = make(tmp_path)
    st = _State(tmp_path, "one")
    on_prompt(s, "never push straight to main", "p", st)
    on_prompt(s, "ok, and never push straight to main", "p", st)
    assert "push straight" not in prompt_context(s, "rename a variable", "p", _State(tmp_path, "two"))
    on_prompt(s, "never push straight to main", "p", _State(tmp_path, "three"))  # another session: proven
    assert "push straight" in prompt_context(s, "rename a variable", "p", _State(tmp_path, "four"))


def test_said_for_this_repo_stays_in_the_project():
    from dore.learn.statements import scope_for
    assert scope_for("In this repo never push straight to main", "shop") == "shop"
    assert scope_for("Here we always squash commits before merging", "shop") == "shop"
    assert scope_for("Never push straight to main", "shop") == ""  # no place: a habit of the user


def test_a_rule_splits_into_wanted_and_forbidden_by_grammar():
    from dore.learn.grammar import rule_parts
    assert rule_parts("don't use npm, use pnpm") == (["use", "pnpm"], ["npm"])
    assert rule_parts("never use print for logging, use the logger") == (["use", "logger"], ["print", "logging"])
    assert rule_parts("I prefer short answers without emojis")[1] == ["emojis"]
    assert rule_parts("do not call the database from the view layer")[0] == []  # only forbids


def test_practice_is_doing_what_the_rule_wants_and_nothing_it_forbids(tmp_path):
    from dore.integrations.hooks import practised, reply_words
    s = make(tmp_path)
    acts = lambda a: reply_words(a)  # noqa: E731
    assert practised(s, "always use pnpm", set(), acts("pnpm add lodash"))
    assert not practised(s, "always use pnpm", reply_words("I would use pnpm"), acts("git status"))  # only talk
    assert practised(s, "never use print for logging, use the logger", set(), acts("logger.info(x)"))
    assert not practised(s, "never use print for logging, use the logger", set(), acts("logger.info(x); print(x)"))
    assert not practised(s, "never use tabs in this repo", set(), acts("def f():\n    return 1"))


def test_last_turn_reads_what_claude_did(tmp_path):
    import json
    from dore.integrations.hooks import last_turn
    log = tmp_path / "t.jsonl"
    ev = [{"type": "user", "message": {"content": "add lodash"}},
          {"type": "assistant", "message": {"content": [{"type": "text", "text": "Adding it."},
                                                        {"type": "tool_use", "name": "Bash",
                                                         "input": {"command": "pnpm add lodash"}}]}},
          {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
          {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}}]
    log.write_text("\n".join(json.dumps(e) for e in ev))
    text, actions = last_turn(log)
    assert "Adding it." in text and "Done." in text and actions == "pnpm add lodash"


def test_what_claude_code_logs_between_two_messages_does_not_cut_the_answer(tmp_path):
    import json
    from dore.integrations.hooks import last_turn
    said = lambda t: {"type": "assistant", "message": {"content": [{"type": "text", "text": t}]}}  # noqa: E731
    ev = [{"type": "user", "message": {"content": "add lodash"}}, said("Adding it."),
          {"type": "user", "isMeta": True, "message": {"content": "Caveat: local command output follows."}},
          {"type": "user", "message": {"content": "<command-name>/model</command-name>"}},
          {"type": "user", "message": {"content": "<local-command-stdout>Set model</local-command-stdout>"}},
          {"type": "user", "message": {"content": "<task-notification>tests finished</task-notification>"}},
          said("Tests pass too."), {"type": "user", "message": {"content": "next one"}}]
    log = tmp_path / "t.jsonl"
    log.write_text("\n".join(json.dumps(e) for e in ev))
    assert last_turn(log)[0] == "Adding it.\nTests pass too."


def test_being_found_by_a_search_is_not_being_used(tmp_path):
    from dore.integrations.hooks import rules_in_mind
    s = make(tmp_path)
    i = rule(s, "never deploy on fridays", said=2, days_ago=120)
    assert i not in [m.id for m in rules_in_mind(s, "p", set())]
    s.search("never deploy on fridays", k=3, project="p")  # what dore's MCP tool does
    assert i not in [m.id for m in rules_in_mind(s, "p", set())]
