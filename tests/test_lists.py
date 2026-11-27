"""Long messages as groups: a list is kept whole (title + entries), Haiku judges pastes, Claude gets one entry."""

import pytest

from dore.integrations import hooks
from dore.learn import grammar
from dore.learn.consolidate import Said, block_of, consolidate, is_block
from dore.learn.judge import BLOCK_SYSTEM, Block, _numbers, block_text, parse_blocks
from dore.learn.statements import list_group
from dore.memory import MemoryStore
from dore.memory.embed import HashEmbedder

needs_parser = pytest.mark.skipif(grammar.nlp() is None, reason="spaCy model not installed")


def store(tmp_path):
    return MemoryStore(tmp_path / "m.db", None, HashEmbedder())


def pasted(body, typed=""):
    return f'<pasted_content id="p">\n{body}\n</pasted_content id="p">\n{typed}'


class Fake:
    def __init__(self, blocks="", lines=""):
        self.blocks, self.lines, self.asked = blocks, lines, []

    def __call__(self, prompt, system=None):
        self.asked.append((system, prompt))
        return (self.blocks if system and BLOCK_SYSTEM in system else self.lines), {"input": 1, "output": 1}


@needs_parser
@pytest.mark.parametrize("msg", [
    "Here are my friends:\n- Sokha: nurse, lives in Battambang\n- Dara: teacher, lives in Kampot",
    "My team:\n1. Rithy, backend lead\n2. Bopha, designer\n3. Nimol, QA",
    "These are the people in my book club:\n* Maly from Kep\n* Thida from Takeo",
    "Our servers:\nweb-1 runs nginx in Singapore\nweb-2 runs nginx in Tokyo",
])
def test_a_typed_list_under_a_lead_line_is_a_group(msg):
    title, items = list_group(msg)
    assert not title.endswith(":") and len(items) >= 2 and not items[0].startswith(("-", "*", "1."))


@needs_parser
@pytest.mark.parametrize("msg", [
    "Fix the login page:\n- make the button bigger\n- change the color to blue",
    "Can you check these:\n- the cart total\n- the footer",
    "Todo:\n- fix login\n- add tests",
    "Here is my function:\ndef total(x):\n    return sum(x)",
    "Here are my friends:\n- Sokha",
    "Sokha is a nurse\nDara is a teacher\nVanna is a pilot",
    "Bugs I found today:\n- the cart total is wrong\n- login fails on Safari",
    "I run the proxy with compose like this:\n    image: caddy:2\n    restart: always",
])
def test_requests_code_and_lists_without_a_lead_are_not_groups_by_the_word_rules(msg):
    assert list_group(msg) is None


def test_long_or_pasted_messages_are_judged_whole():
    assert is_block(pasted("a | b\nc | d", "these are my team members"))
    assert is_block("one\ntwo\nthree")
    assert is_block(" ".join(f"Fact number {k} is here." for k in range(25)))
    assert not is_block("I live in Kampot. My dog is Adam.")
    assert not is_block("<task-notification>x\ny\nz</task-notification>")
    b = block_of(1, pasted("x = 1\ny = 2", "this is our config"))
    assert b.pasted and b.lines == ["x = 1", "y = 2"] and b.words == "this is our config"


def test_haiku_sees_a_long_block_by_its_start_and_end_and_each_line_once():
    b = Block(1, [f"entry {k}" for k in range(200)] + ["entry 0"])
    text = block_text([b])
    assert "1.1: entry 0" in text and "(not shown)" in text and "1.200: entry 199" in text
    assert text.count("entry 0\n") + text.endswith("entry 0") == 1
    assert len(text.splitlines()) < 60


def test_block_answers_parse_line_numbers_in_any_form_and_drop_the_rest():
    assert _numbers("1.2-1.11", 20) == list(range(2, 12)) and _numbers("2-4, 7, 99", 10) == [2, 3, 4, 7]
    blocks = [Block(1, ["a"] * 12), Block(2, ["b"] * 3)]
    v = parse_blocks("This block is a list of friends, lasting.\n"
                     "[1] group user: The user's friends | name, city | lines: 1.2-1.11\n"
                     "2 skip\n3 group user: Ghost | x | lines: 1-2\n2 group user: No lines |\n"
                     "2 group user|team: Team | <what each entry gives> | lines: 1-3", blocks)
    assert [x.action for x in v[1]] == ["group"] and v[1][0].lines == list(range(2, 12))
    assert [x.action for x in v[2]] == ["skip", "group"] and 3 not in v
    assert v[2][1].scope == "user" and v[2][1].title == "Team" and v[2][1].lines == [1, 2, 3]


def test_a_group_keeps_every_entry_word_for_word_and_one_entry_is_shown(tmp_path):
    s = store(tmp_path)
    ids = s.add_group("The user's friends", ["Sokha: nurse, Battambang", "Dara: teacher, Kampot",
                                              "Vanna: pilot, Siem Reap"])
    head, items = ids[0], ids[1:]
    assert s.get(head).kind == "group" and s.group_size(head) == 3
    assert [m.content for m in s.group_items(head)] == ["Sokha: nurse, Battambang", "Dara: teacher, Kampot",
                                                        "Vanna: pilot, Siem Reap"]
    assert all(s.get(i).replaced_by is None for i in items)  # entries of one list never replace each other
    out = hooks.recall_text(s, [str(head), "#999"])
    assert "Vanna: pilot, Siem Reap" in out and "#999 is not a list" in out


def test_the_same_list_again_in_another_session_proves_it_once(tmp_path):
    s = store(tmp_path)
    first = s.add_group("My team", ["Rithy, backend lead", "Bopha, designer"], session="a")
    again = s.add_group("My team", ["Rithy, backend lead", "Bopha, designer"], session="a")
    later = s.add_group("My team", ["Rithy, backend lead", "Bopha, designer"], session="b")
    assert first == again == later
    assert s.get(first[1]).times_seen == 2


def test_a_pasted_list_is_the_users_word_only_when_they_say_what_it_is(tmp_path):
    rows = "Rithy | backend lead | rithy@example.com\nBopha | designer | bopha@example.com"
    for typed, trust in (("these are my team members", "verified"), ("", "unverified")):
        s = store(tmp_path / (typed[:5] or "none"))
        msg = pasted(rows, typed)
        stats = consolidate(s, [Said(msg, "shop", "s1", 1.0)],
                            Fake("1 group user: Team members | name, role, email | lines: 1-2"))
        items = s.group_items(stats["lines"][1][0])
        assert [m.content for m in items] == rows.splitlines() and {m.trust for m in items} == {trust}
        assert {m.project for m in items} == {""}


def test_skipped_blocks_and_facts_the_user_never_wrote_store_nothing(tmp_path):
    s = store(tmp_path)
    log = pasted("Traceback (most recent call last):\n  File app.py, line 3\nValueError: bad", "why?")
    stats = consolidate(s, [Said(log, "shop", "s1", 1.0), Said("one\ntwo\nthree", "shop", "s1", 1.0)],
                        Fake("1 skip\n2 fact project: The app runs on port 9999."))
    assert s.db.execute("SELECT count(*) FROM memories").fetchone()[0] == 0
    assert stats["dropped"] == 1 and stats["lines"] == {}


def test_blocks_and_sentences_in_one_batch_keep_their_line_numbers(tmp_path):
    s = store(tmp_path)
    batch = [Said("the staging api runs on port 8443", "shop", "s1", 1.0),
             Said(pasted("a: 1\nb: 2"), "shop", "s1", 1.0)]
    fake = Fake("2 group project: Settings | lines: 1-2\n1 fact project: The staging API runs on port 8443.")
    stats = consolidate(s, batch, fake)
    assert len(fake.asked) == 1 and "[2] pasted" in fake.asked[0][1]  # one call; the block after the sentence
    assert len(stats["lines"][1]) == 1 and len(stats["lines"][2]) == 3


def test_a_question_gets_the_matching_entry_and_how_to_get_the_rest(tmp_path):
    s = store(tmp_path)
    head = s.add_group("The user's friends", ["Sokha: nurse, lives in Battambang", "Dara: teacher, lives in Kampot",
                                              "Vanna: pilot, lives in Siem Reap"])[0]
    text = hooks.prompt_context(s, "where is Sokha: nurse, lives in Battambang?", "shop", hooks._State(tmp_path, "q"))
    assert "The user's friends: Sokha: nurse, lives in Battambang" in text
    assert f"+2 more in #{head}" in text and "recall <#>" in text and "Vanna" not in text


def test_rules_in_a_long_typed_message_are_still_rules(tmp_path):
    s = store(tmp_path)
    msg = "From now on:\n- always use pnpm, never npm\n- never push to main\n- keep answers short"
    stats = consolidate(s, [Said(msg, "shop", "s1", 1.0)],
                        Fake("1 rule user: Always use pnpm, never npm | when: npm, install | not: npm install\n"
                             "1 rule project: Never push to main | when: git push | not: main"))
    assert stats["rules"] == 2 and all(s.is_rule(i) for i in stats["lines"][1])
    assert {s.get(i).trust for i in stats["lines"][1]} == {"verified"}


def test_a_fact_taken_out_of_a_paste_is_not_the_users_word(tmp_path):
    s = store(tmp_path)
    log = pasted("connecting to postgres 14 on db.internal\nERROR: timeout", "this is weird")
    stats = consolidate(s, [Said(log, "shop", "s1", 1.0)], Fake("1 fact project: The app uses postgres 14."))
    assert s.get(stats["lines"][1][0]).trust == "unverified"


def test_a_list_with_no_entries_left_is_not_shown(tmp_path):
    s = store(tmp_path)
    old = s.add_group("My friends", ["Sokha lives in Battambang", "Dara lives in Kampot"])[0]
    s.add_group("Friends list", ["Sokha lives in Battambang", "Dara lives in Kampot"])
    assert s.group_size(old) == 0
    text = hooks.prompt_context(s, "who are My friends?", "shop", hooks._State(tmp_path, "q"))
    assert f"#{old} " not in text


def test_a_lists_title_comes_only_with_a_question(tmp_path):
    s = store(tmp_path)
    head = s.add_group("The user's friends", ["Sokha lives in Battambang", "Dara lives in Kampot"])[0]
    work = hooks.prompt_context(s, "add the user's friends page", "shop", hooks._State(tmp_path, "w"))
    asked = hooks.prompt_context(s, "who are the user's friends?", "shop", hooks._State(tmp_path, "q"))
    assert work == "" and "The user's friends" in asked and head
