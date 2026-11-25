from dore.assistant.checkers import check_math, extract_code, run_python, safe_eval


def test_extract_code_takes_last_block():
    text = "first\n```python\nx = 1\n```\nthen\n```python\ndef f():\n    return 2\n```"
    assert extract_code(text).startswith("def f")


def test_run_python_pass_fail_and_tested_flag():
    ok = run_python("def add(a, b):\n    return a + b", "assert add(2, 3) == 5")
    assert ok.passed and ok.tested
    bad = run_python("def add(a, b):\n    return a - b", "assert add(2, 3) == 5")
    assert not bad.passed and "AssertionError" in bad.output
    untested = run_python("print('hi')")
    assert untested.passed and not untested.tested


def test_run_python_timeout():
    r = run_python("while True: pass", timeout=1)
    assert not r.passed


def test_run_python_memory_limit():
    r = run_python("x = bytearray(2 * 1024**3)", mem_mb=256)
    assert not r.passed


def test_math_checker():
    assert safe_eval("2^10 + 3*4") == 1036
    assert check_math("12*12", 144).passed
    assert not check_math("12*12", 145).passed
    assert not check_math("__import__('os')", 0).passed

