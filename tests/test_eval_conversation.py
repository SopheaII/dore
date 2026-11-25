from dore.eval.conversation import SHORT_QUESTIONS, SHORT_SESSIONS, long_scenario, run
from dore.memory.embed import HashEmbedder


def test_conversation_check_runs_and_counts():
    r = run(SHORT_SESSIONS, SHORT_QUESTIONS, HashEmbedder())
    assert r["questions"] == 7 and r["changed"] == 3 and 0 <= r["correct"] <= 7


def test_long_scenario_is_fixed_by_seed():
    a, b = long_scenario(), long_scenario()
    assert a == b and len(a[1]) == 80 and sum(len(s) for s in a[0]) > 400
