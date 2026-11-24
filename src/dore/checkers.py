"""Checkers: the only things allowed to mark a result `verified`.

Sandbox limits: unprivileged user namespaces are often blocked, so network
access is not cut off. The runner uses a timeout, CPU/memory limits, a temporary
working directory, isolated Python (-I) and an empty environment.
"""

from __future__ import annotations

import ast
import operator
import re
import resource
import subprocess
import sys
import tempfile
from dataclasses import dataclass


@dataclass
class CheckResult:
    passed: bool       # ran without error (and tests passed, if any)
    tested: bool       # real tests were run; only tested+passed may become `verified`
    output: str


def extract_code(text: str) -> str:
    """Return the last ```python block (or any ``` block); fall back to the raw text."""
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, flags=re.S)
    return blocks[-1].strip() if blocks else text.strip()


def _limits(mem_mb: int, cpu_s: int):
    def apply():
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 2**20, mem_mb * 2**20))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 2**20, 10 * 2**20))
    return apply


def run_python(code: str, tests: str | None = None, timeout: float = 10.0, mem_mb: int = 512) -> CheckResult:
    program = code if not tests else f"{code}\n\n# ---- tests ----\n{tests}\n"
    with tempfile.TemporaryDirectory(prefix="dore-run-") as tmp:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", program],
                cwd=tmp, env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True,
                timeout=timeout, preexec_fn=_limits(mem_mb, int(timeout) + 1),
            )
        except subprocess.TimeoutExpired:
            return CheckResult(False, bool(tests), f"Timed out after {timeout}s")
    out = (proc.stdout + proc.stderr)[-4000:]
    return CheckResult(proc.returncode == 0, bool(tests), out)


_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def safe_eval(expr: str) -> float:
    """Evaluate a pure arithmetic expression (numbers and + - * / // % ** only)."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            if isinstance(node.op, ast.Pow) and abs(ev(node.right)) > 1000:
                raise ValueError("exponent too large")
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError(f"unsupported expression: {ast.dump(node)[:60]}")
    return ev(ast.parse(expr.replace("^", "**").replace("×", "*").replace("÷", "/"), mode="eval"))


def check_math(expr: str, claimed: float, tol: float = 1e-9) -> CheckResult:
    try:
        actual = safe_eval(expr)
    except Exception as e:  # noqa: BLE001
        return CheckResult(False, False, f"cannot evaluate: {e}")
    ok = abs(actual - claimed) <= tol * max(1.0, abs(actual))
    return CheckResult(ok, True, f"{expr} = {actual}")
