from dore.eval.stream import PROJECTS, WEEKS, run, scenario
from dore.memory.embed import HashEmbedder


def test_stream_scenario_is_fixed_by_seed_and_has_long_session():
    a, b = scenario(), scenario()
    assert [m.text for m in a.messages] == [m.text for m in b.messages]
    assert sum(m.session == a.long_session for m in a.messages) == 220
    assert set(a.checkpoints) == set(range(1, WEEKS + 1))
    assert {m.project for m in a.messages} == set(PROJECTS)


def test_stream_questions_track_changes_and_other_projects():
    sc = scenario()
    q = {(x.project, x.kind): x for x in sc.checkpoints[WEEKS]}
    assert q[("shop", "deploy")].expect == "Render" and q[("shop", "deploy")].old == ["Heroku"]
    assert q[("api", "css")].expect is None and "Tailwind" in q[("api", "css")].others
    assert "Render" not in q[("blog", "deploy")].others or q[("blog", "deploy")].expect != "Render"


def test_stream_run_counts():
    r = run(scenario(long_prompts=30), HashEmbedder())
    assert len(r["weekly"]) == WEEKS and r["facts"] > 20
    assert all(0 <= w["correct"] <= w["questions"] for w in r["weekly"])
