def test_ask_uses_memory_and_saves_unverified(make):
    a = make(["Phnom Penh."])
    a.teach("The capital of Cambodia is Phnom Penh")
    assert a.ask("What is the capital of Cambodia?") == "Phnom Penh."
    assert "[verified, told by the user] The capital of Cambodia is Phnom Penh" in a.core.prompts[0][-1]["content"]
    assert a.memory.get(a.last_answer_id).trust == "unverified"


def test_correct_marks_last_answer_wrong(make):
    a = make(["Siem Reap.", "Phnom Penh."])
    a.ask("What is the capital of Cambodia?")
    wrong_id = a.last_answer_id
    a.correct("The capital of Cambodia is Phnom Penh")
    assert a.memory.get(wrong_id).trust == "wrong"
    a.ask("Capital of Cambodia?")
    notes = a.core.prompts[1][-1]["content"]
    assert "Siem Reap" not in notes and "[verified, told by the user] The capital of Cambodia is Phnom Penh" in notes


def test_code_loop_fixes_and_saves_verified_lesson(make):
    wrong = "```python\ndef square(x):\n    return x * 2\n```"
    right = "```python\ndef square(x):\n    return x * x\n```"
    a = make([wrong, right])
    r = a.solve_code("Write square(x).", tests="assert square(3) == 9")
    assert r.check.passed and r.attempts == 2
    lesson = a.memory.get(r.memory_id)
    assert lesson.trust == "verified" and "AssertionError" in lesson.content


def test_code_without_tests_stays_unverified(make):
    a = make(["```python\nprint('hello')\n```"])
    r = a.solve_code("Print hello.")
    assert r.check.passed and a.memory.get(r.memory_id).trust == "unverified"


def test_code_gives_up_after_max_rounds(make):
    bad = "```python\ndef f():\n    return 0\n```"
    a = make([bad] * 3)
    r = a.solve_code("Write f returning 1.", tests="assert f() == 1")
    assert not r.check.passed and r.attempts == 3 and r.memory_id is None


def test_plain_chat_statements_are_learned_but_questions_are_not(make):
    a = make(["Nice!"])
    a.ask("My cat is called Mochi. I live in Phnom Penh. What should I cook tonight?")
    stored = [r[0] for r in a.memory.db.execute("SELECT content FROM memories WHERE kind='statement'")]
    assert stored == ["My cat is called Mochi.", "I live in Phnom Penh."]


def test_own_answers_are_not_reused_until_approved(make):
    a = make(["You live on Elm Street.", "ok", "ok"])
    a.ask("Where do I live?")
    made_up = a.last_answer_id
    a.ask("Where do I live?")
    assert "Elm Street" not in a.core.prompts[1][-1]["content"]  # unapproved answer not reused
    a.last_answer_id = made_up
    a.good()  # user approves it -> verified -> reusable
    a.ask("Where do I live?")
    assert "Elm Street" in a.core.prompts[2][-1]["content"]


def test_answer_never_merges_into_a_user_fact(make):
    # If the model repeats the user's fact word for word, /correct must not mark the fact wrong.
    a = make(["x"])
    fact = a.teach("Q: where do I live\nA: Phnom Penh")
    a.ask("where do I live")
    a.core.replies.append("unused")
    a.correct("I live in Phnom Penh")
    assert a.memory.get(fact).trust == "verified"


def test_long_paste_is_stored_as_unverified_document(make):
    a = make(["ok"], max_auto_statements=5)
    text = " ".join(f"Sentence number {i} says something." for i in range(30)) + " Summarise this."
    a.ask(text)
    kinds = dict(a.memory.db.execute("SELECT kind, COUNT(*) FROM memories GROUP BY kind").fetchall())
    assert "statement" not in kinds and kinds["document"] >= 1
    trusts = {r[0] for r in a.memory.db.execute("SELECT trust FROM memories WHERE kind='document'")}
    assert trusts == {"unverified"}


def test_huge_question_is_cut_to_fit_context(make):
    a = make(["short answer"], n_ctx=1200)
    huge = "word " * 5000 + "What is the last word?"
    assert a.ask(huge) == "short answer"  # FakeCore asserts no overflow
    sent = a.core.prompts[0][-1]["content"]
    assert "characters cut to fit" in sent and sent.endswith("What is the last word?")


def test_old_history_dropped_when_context_is_full(make):
    a = make(["a1", "a2", "a3"], n_ctx=1100)
    a.ask("first? " * 150)  # questions: not stored as statements
    a.ask("second? " * 150)
    a.ask("third? " * 150)  # FakeCore asserts no overflow
    assert len(a.core.prompts[2]) < 1 + 4 + 1


def test_code_fix_prompt_does_not_grow(make):
    bad = "```python\ndef f():\n    return 0\n```"
    a = make([bad] * 3)
    a.solve_code("Write f returning 1.", tests="assert f() == 1")
    assert [len(p) for p in a.core.prompts] == [2, 2, 2]
    assert "This attempt failed" in a.core.prompts[2][-1]["content"]


def test_no_guess_rule_only_on_questions_about_the_user(make):
    a = make(["a", "b"])
    a.ask("What is my dog called?")
    a.ask("What is the capital of France?")
    assert a.core.prompts[0][-1]["content"].endswith("say you don't know.)")
    assert a.core.prompts[1][-1]["content"].endswith("Question: What is the capital of France?")


def test_statement_filter(make):
    from dore.agent import split_statements
    assert split_statements("Please remember that my wife's name is Dara.") == ["My wife's name is Dara."]
    assert split_statements("Can you remember that my birthday is May 3?") == ["My birthday is May 3"]
    assert split_statements("FYI: the office opens at 8.") == ["The office opens at 8."]
    for noise in ("Thanks a lot!", "Hello, how are you", "Summarize the following text.",
                  "Help me with this code.", "Can you help me with my homework"):
        assert split_statements(noise) == [], noise
    assert split_statements("Help desk number is 555-1234.") == ["Help desk number is 555-1234."]


def test_correct_demotes_the_conflicting_fact(make):
    a = make(["You have a Toyota.", "ok"])
    a.ask("My car is a Toyota.")
    toyota = a.memory.search("My car is a Toyota", k=1)[0].id
    a.ask("What car do I have?")
    a.correct("My car is a Toyota no wait it is a Honda")  # HashEmbedder: word overlap -> high similarity
    assert toyota in a.last_demoted_ids and a.memory.get(toyota).trust == "wrong"
