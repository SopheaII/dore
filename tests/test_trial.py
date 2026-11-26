"""Notes learned from chat start are on trial until used, or archived after unused tries."""

import json

from dore.integrations.hooks import (_State, judge_last, last_reply, prompt_context, reply_words, use_check)
from dore.memory import MemoryStore, on_trial
from dore.memory.embed import HashEmbedder
from dore.memory.store import ARCHIVE_TRIES

NOTE = "images live in bucket shop-assets on cloudflare r2"


def make(tmp_path, replies: int = 500):
    s = MemoryStore(tmp_path / "m.db", None, HashEmbedder())
    for _ in range(replies):
        s.count_reply({"code", "test", "change", "file"})
    return s


def statement(s, text=NOTE):
    return s.add(text, kind="statement", source="user", trust="verified", project="shop")


def ask(s, st, prompt, reply_before=""):
    judge_last(s, st, reply_before)
    out = prompt_context(s, prompt, "shop", st)
    st.d["last_prompt"] = prompt
    return out


def test_on_trial_only_on_questions_then_proven_by_use(tmp_path):
    s = make(tmp_path)
    i = statement(s)
    assert on_trial(s.get(i))
    assert NOTE not in prompt_context(s, "images live in bucket shop-assets", "shop", _State(tmp_path, "w"))  # work
    st = _State(tmp_path, "q")
    assert NOTE in ask(s, st, "where do images live in bucket shop-assets?")
    judge_last(s, st, "They are in the shop-assets bucket on Cloudflare R2.")
    assert s.get(i).uses == 1 and not on_trial(s.get(i))
    assert NOTE in prompt_context(s, "images live in bucket shop-assets", "shop", _State(tmp_path, "w2"))


def test_never_used_on_its_questions_is_archived_and_comes_back_when_said_again(tmp_path):
    s = make(tmp_path)
    i = statement(s)
    for n in range(ARCHIVE_TRIES):
        st = _State(tmp_path, f"q{n}")
        assert NOTE in ask(s, st, "where do images live in bucket shop-assets?")
        judge_last(s, st, "I changed the test file.")
    m = s.get(i)
    assert m.archived and m.tries == ARCHIVE_TRIES
    assert statement(s) == i  # the user says it again: same note, back and proven
    m = s.get(i)
    assert not m.archived and m.times_seen == 2 and not on_trial(m)


def test_no_evidence_no_try(tmp_path):
    s = make(tmp_path, replies=3)  # too few replies: even a full repeat could be luck
    i = statement(s)
    st = _State(tmp_path, "q")
    assert NOTE in ask(s, st, "where do images live in bucket shop-assets?")
    judge_last(s, st, "I changed the test file.")
    assert s.get(i).tries == 0 and not s.get(i).archived


def test_one_common_word_does_not_prove_a_note(tmp_path):
    s = make(tmp_path, replies=0)
    for _ in range(300):
        s.count_reply({"instal", "claude", "code"})
    for _ in range(300):
        s.count_reply({"test"})
    used, testable = use_check(s, "I install this to my claude code", "is this saved to claude?",
                               reply_words("You can install it with npx."))
    assert not used


def test_last_reply_is_the_answer_to_the_previous_message(tmp_path):
    log = tmp_path / "t.jsonl"
    ev = [
        {"type": "user", "message": {"content": "first question"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "old answer"}]}},
        {"type": "user", "message": {"content": "where are images?"}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "In shop-assets."}]}},
    ]
    log.write_text("\n".join(json.dumps(e) for e in ev))
    assert last_reply(log) == "In shop-assets."
    log.write_text("\n".join(json.dumps(e) for e in ev + [{"type": "user", "message": {"content": "next one"}}]))
    assert last_reply(log) == "In shop-assets."  # the log may already hold the new message
    assert last_reply(None) == ""
