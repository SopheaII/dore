import json

from dore.embed import HashEmbedder
from dore.hooks import _State, prompt_context, save_session, scope_for, user_facts
from dore.memory import MemoryStore

S1 = ("hey, can you add discount codes to the cart? add apply_discount(cart, code) that returns the discounted "
      "total in cents. codes should be case-insensitive. start with WELCOME10 = 10% off. finance decided the max "
      "discount is 50% because anything higher loses money on shipping. also fyi our production server is still "
      "on python 3.9 so keep the code compatible. add tests and make sure they pass")


def test_user_facts_keeps_decisions_drops_requests():
    assert user_facts(S1) == [
        "Codes should be case-insensitive.",
        "Finance decided the max discount is 50% because anything higher loses money on shipping.",
        "Our production server is still on python 3.9 so keep the code compatible.",
    ]
    assert user_facts("add a SUMMER code for 60% off please") == []
    assert user_facts("quick question, why do we cap discounts at 50%?") == []
    assert user_facts("rename x to total in calc.py") == []
    assert user_facts("I need a parse_price(text) helper that turns '12.50' into cents. add tests") == []
    assert user_facts("add format_total with tests. it will run on our production server") == []
    assert user_facts("I work as a nurse at Calmette Hospital.") == ["I work as a nurse at Calmette Hospital."]
    assert user_facts("fyi our staging server runs on port 8443. reply with just: noted") == [
        "Our staging server runs on port 8443."]


def test_scope_org_and_personal_facts_are_general():
    assert scope_for("Our production server is still on python 3.9", "shop") == ""
    assert scope_for("My editor is neovim", "shop") == ""
    assert scope_for("Codes should be case-insensitive.", "shop") == "shop"


def make(tmp_path):
    return MemoryStore(tmp_path / "m.db", None, HashEmbedder())


def test_rules_once_then_only_strong_matches_never_repeated(tmp_path):
    s = make(tmp_path)
    s.add("keep the code python 3.9 compatible", trust="verified", project="shop")
    s.add("images live in bucket shop-assets on cloudflare r2", trust="verified", project="shop")
    s.add("the blog uses hugo", trust="verified", project="blog")
    st = _State(tmp_path, "sess1")
    first = prompt_context(s, "rename a variable", "shop", st)
    assert "python 3.9" in first and "shop-assets" not in first and "hugo" not in first
    assert prompt_context(s, "fix a typo", "shop", st) == ""                      # nothing relevant: 0 tokens
    hit = prompt_context(s, "where do images live in bucket shop-assets", "shop", st)
    assert "shop-assets" in hit and "python 3.9" not in hit                       # rule not repeated
    assert prompt_context(s, "where do images live in bucket shop-assets", "shop", st) == ""  # note not repeated


def test_session_end_saves_user_statements_from_transcript(tmp_path):
    s = make(tmp_path)
    log = tmp_path / "t.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": S1}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Our API is fast."}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "Our CI is red."}]}},
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "The cache is wrong."}},
        {"type": "user", "message": {"role": "user", "content": "<command-name>/model</command-name>"}},
    ]
    log.write_text("\n".join(json.dumps(x) for x in lines))
    save_session(s, log, "shop")
    rows = dict(s.db.execute("SELECT content, project FROM memories").fetchall())
    assert rows == {
        "Codes should be case-insensitive.": "shop",
        "Finance decided the max discount is 50% because anything higher loses money on shipping.": "shop",
        "Our production server is still on python 3.9 so keep the code compatible.": "",
    }
    assert {r[0] for r in s.db.execute("SELECT trust FROM memories")} == {"verified"}


def test_session_end_skips_pastes_and_system_text(tmp_path):
    s = make(tmp_path)
    log = tmp_path / "t.jsonl"
    paste = " ".join(f"The brain has about {i} billion neurons in region {i}." for i in range(80))
    lines = [
        {"type": "user", "message": {"role": "user", "content": paste}},
        {"type": "user", "message": {"role": "user", "content": "[Request interrupted by user]"}},
        {"type": "user", "message": {"role": "user", "content": "Our staging server runs on port 8443."}},
    ]
    log.write_text("\n".join(json.dumps(x) for x in lines))
    save_session(s, log, "shop")
    assert [r[0] for r in s.db.execute("SELECT content FROM memories")] == ["Our staging server runs on port 8443."]


def test_personal_wish_is_not_a_rule_but_personal_preference_is(tmp_path):
    s = make(tmp_path)
    s.add("I don't want to install any app on my phone", trust="verified")
    s.add("I always prefer short answers", trust="verified")
    s.add("keep the code python 3.9 compatible", trust="verified", project="shop")
    first = prompt_context(s, "rename a variable", "shop", _State(tmp_path, "s2"))
    assert "install any app" not in first and "short answers" in first and "python 3.9" in first


def test_warm_helper_answers_and_client_falls_back(tmp_path):
    import threading
    import time
    from dore.config import Config
    from dore.hookclient import SOCKET_NAME, ask_helper
    from dore.hookd import serve

    cfg = Config(data_dir=tmp_path)
    sock = str(tmp_path / SOCKET_NAME)
    assert ask_helper(sock, "prompt", {}) is None                      # no helper: caller runs inline

    def factory(c):
        st = MemoryStore(tmp_path / "m.db", None, HashEmbedder())
        st.add("keep the code python 3.9 compatible", trust="verified", project="shop")
        return st
    t = threading.Thread(target=serve, args=(cfg, 1.0, factory), daemon=True)
    t.start()
    for _ in range(100):
        if (tmp_path / SOCKET_NAME).exists():
            break
        time.sleep(0.02)
    out = ask_helper(sock, "prompt", {"prompt": "rename x", "session_id": "a", "cwd": str(tmp_path / "shop")})
    assert "python 3.9" in out
    assert oct((tmp_path / SOCKET_NAME).stat().st_mode & 0o777) == "0o600"
    t.join(timeout=5)                                                    # quits when idle
    assert not t.is_alive() and not (tmp_path / SOCKET_NAME).exists()


def test_prompt_hook_learns_right_away_and_never_echoes_it(tmp_path):
    from dore.hooks import on_prompt
    s = make(tmp_path)
    st = _State(tmp_path, "live")
    out = on_prompt(s, "fyi our staging server runs on port 8443. add a health check", "shop", st)
    assert "8443" not in out                                             # not sent back to Claude
    assert s.search("staging server port", k=1)[0].content == "Our staging server runs on port 8443."


def test_plain_correction_in_claude_code_replaces_and_demotes(tmp_path):
    from dore.hooks import on_prompt
    s = make(tmp_path)
    s.duplicate_threshold = 1.01
    old = s.add("The api server uses port 8080 in production", trust="verified", project="shop")
    st = _State(tmp_path, "fix")
    assert "8080" in on_prompt(s, "what port does the api server use in production?", "shop", st)
    on_prompt(s, "No, the api server uses port 9090 in production", "shop", st)
    assert st.d["last_signal"] == "correction"
    assert s.get(old).trust == "wrong" or s.get(old).replaced_by is not None
    hits = [h.content for h in s.search("api server port production", k=3)]
    assert hits[0] == "The api server uses port 9090 in production" and not any("8080" in h for h in hits)


def test_reask_in_claude_code_lowers_the_notes_shown(tmp_path):
    from dore.hooks import on_prompt
    s = make(tmp_path)
    note = s.add("the images live in bucket shop-assets", trust="verified", project="shop")
    st = _State(tmp_path, "re")
    on_prompt(s, "where do the images live?", "shop", st)
    assert st.d["last_shown"] == [note]
    on_prompt(s, "where do the images live", "shop", st)
    assert st.d["last_signal"] == "reask" and s.get(note).feedback == -1


def test_prompt_output_is_capped(tmp_path):
    from dore.hooks import MAX_TOTAL_CHARS
    s = make(tmp_path)
    for i in range(6):
        s.add(f"rule {i}: always keep the code python 3.9 compatible " + "and tidy " * 15, trust="verified")
    out = prompt_context(s, "rename a variable", "shop", _State(tmp_path, "cap"))
    body = out.split("\n", 1)[1]
    assert 0 < len(body) <= MAX_TOTAL_CHARS + 10


def test_session_end_skips_what_the_prompt_hook_learned(tmp_path):
    from dore.hooks import message_key
    s = make(tmp_path)
    msg = "Our staging server runs on port 8443."
    s.add(msg, source="user", trust="verified")
    log = tmp_path / "t.jsonl"
    log.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": msg}}))
    save_session(s, log, "shop", learned={message_key(msg)})
    assert s.get(1).times_seen == 1
