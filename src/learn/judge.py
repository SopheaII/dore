"""Ask Claude Haiku, in one small batch, what the user's sentences should leave in memory (`learn.consolidate`)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

SYSTEM = """You decide what a developer's messages to a coding assistant should leave in long-term memory. Most \
lines are tasks or chat about right now: skip them. Keep only what will still be true and useful in a later session.

Input: one line per sentence, "N: sentence", maybe followed by "~ #id note" = existing notes that may be about the \
same thing.
Answer one line per note, in this form, nothing else:
N skip
N fact user|project: <note>
N rule user|project: <note> | when: <words> | not: <words>
N same #id   (says what existing note #id says, in any words)
N same @M   (says what line M of this input says)
N update #id user|project: <note>   (note #id is now out of date)

fact: lasts beyond this task: a name, tool, version, path, server, setting, decision or taste. A past action that \
leaves a lasting state is a fact about that state ("I set X to Y": X is Y); a one-time event is skip.
rule: an instruction for all future work ("always", "never", "from now on", "in this repo"), or a lasting wish \
or dislike about how the assistant should work or answer. An instruction for the current task, or a feature to \
build, is skip, even with "don't", "I want" or "please". A task may also state a lasting fact: keep that fact.
update: only when the sentence and note #id cannot both be true now: the same subject and the same property with \
a new value. Another thing of the same kind (another item, person, service, job, place or time) is a new fact, \
and note #id stays.
user: about the person (name, home, habits, taste, own setup) or the whole team or company across all its \
projects. project: everything about this codebase, its deployment, servers, data and clients. If unsure: project.
note: one short plain sentence with only what the user said; keep names, numbers and paths exactly; one fact per \
note (one line may give several).
when: 1-3 words seen in commands or code when the rule applies; not: words that would break it (may be empty).
Skip questions, guesses, complaints about the current result, thanks, jokes, plans for now, and anything about the \
assistant itself. If unsure, skip."""

MODEL = "haiku"
# Thinking off and low effort: same answers on sorting lines, ~8x fewer output tokens (claude-code.md).
CLI_FLAGS = ["--effort", "low", "--settings", '{"alwaysThinkingEnabled": false, "disableAllHooks": true}', "--tools", "",
             "--strict-mcp-config", "--no-session-persistence", "--output-format", "json"]
SKIP_ENV = "DORE_SKIP"  # dore's own hooks ignore the session it starts (`integrations.hookclient`)


@dataclass
class Item:
    n: int
    text: str
    neighbours: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class Verdict:
    n: int
    action: str  # skip | fact | rule | same | update
    scope: str = ""  # user | project
    text: str = ""
    ref: int | None = None  # same/update: an existing note id
    line: int | None = None  # same @M: a line of this batch
    when: list[str] = field(default_factory=list)
    forbid: list[str] = field(default_factory=list)


class JudgeError(Exception):
    """The call failed; `retry_at` is when to try again (epoch seconds) if the error said."""

    def __init__(self, kind: str, detail: str = "", retry_at: float | None = None):
        super().__init__(f"{kind}: {detail[:200]}")
        self.kind, self.retry_at = kind, retry_at


def batch_text(items: list[Item]) -> str:
    return "\n".join(f"{it.n}: {_one_line(it.text)}" + "".join(f" ~ #{i} {_one_line(t)}" for i, t in it.neighbours)
                     for it in items)


def _one_line(text: str) -> str:
    return " ".join(text.split())


_LINE = re.compile(r"^\s*(\d+)\s*[:.)-]?\s*(skip|fact|rule|same|update)\b\s*:?\s*(.*)$", re.I)
_SCOPED = re.compile(r"^(?:#(\d+)\s+)?(user|project)\s*:\s*(.+)$", re.I)


def parse(answer: str, items: list[Item]) -> dict[int, list[Verdict]]:
    """Verdicts per line number; lines that don't parse, and ids not offered for that line, are dropped."""
    offered = {it.n: {i for i, _ in it.neighbours} for it in items}
    out: dict[int, list[Verdict]] = {}
    for raw in answer.splitlines():
        m = _LINE.match(raw)
        if not m or int(m.group(1)) not in offered:
            continue
        n, action, rest = int(m.group(1)), m.group(2).lower(), m.group(3).strip()
        v = Verdict(n, action)
        if action == "same":
            ref = re.match(r"([#@])(\d+)", rest)
            if not ref:
                continue
            if ref.group(1) == "#":
                v.ref = int(ref.group(2))
                if v.ref not in offered[n]:
                    continue
            else:
                v.line = int(ref.group(2))
                if v.line not in offered or v.line >= n:
                    continue
        elif action in ("fact", "rule", "update"):
            s = _SCOPED.match(rest)
            if not s or (action == "update") != bool(s.group(1)):
                continue
            v.ref = int(s.group(1)) if s.group(1) else None
            if v.ref is not None and v.ref not in offered[n]:
                continue
            v.scope = s.group(2).lower()
            parts = [p.strip() for p in s.group(3).split("|")]
            v.text = parts[0].strip(" .") + "."
            v.text = v.text[:1].upper() + v.text[1:]
            for p in parts[1:]:
                key, _, words = p.partition(":")
                ws = [w.strip() for w in words.split(",") if w.strip()]
                if key.strip().lower() == "when":
                    v.when = ws
                elif key.strip().lower() == "not":
                    v.forbid = ws
        out.setdefault(n, []).append(v)
    return out


_NAME = re.compile(r"[A-Za-z0-9][\w.+#/:-]*")


def grounded(note: str, said: str) -> bool:
    """Every name, number and path in the note is in what the user said (no invented facts); case is free."""
    said_l = said.lower()
    words = _NAME.findall(note)
    for k, w in enumerate(words):
        named = any(c.isdigit() for c in w) or any(c in "./:_#" for c in w.strip(".")) or (k > 0 and w[0].isupper())
        if named and w.strip(".").lower() not in said_l:
            return False
    return True


CONFIRM = ("For each numbered pair 'old || new' (two notes about someone's work or life), answer one line: 'N yes' "
           "if both can be true at the same time (they are about different things, or add to each other), 'N no' if "
           "the new one makes the old one out of date (the same thing now has a different value). Nothing else.")


def confirm_updates(verdicts: dict[int, list[Verdict]], items: list[Item], ask) -> tuple[dict, dict | None]:
    """Hiding a note is the one risky step, so each proposed update gets a second, focused question: can both be
    true? Only a "no" keeps the update; otherwise it becomes a new note and the old one stays. Asked only when the
    batch proposed an update."""
    old = {it.n: dict(it.neighbours) for it in items}
    ups = [(n, v) for n, vs in verdicts.items() for v in vs if v.action == "update"]
    if not ups:
        return verdicts, None
    pairs = [f"{k}: {_one_line(old[n][v.ref])} || {_one_line(v.text)}" for k, (n, v) in enumerate(ups, 1)]
    answer, usage = ask("\n".join(pairs), CONFIRM)
    said = {int(m.group(1)): m.group(2).lower() for m in re.finditer(r"^\s*(\d+)\s*[:.)-]?\s*(yes|no)\b", answer,
                                                                    re.I | re.M)}
    for k, (n, v) in enumerate(ups, 1):
        if said.get(k) != "no":
            v.action, v.ref = "fact", None
    return verdicts, usage


def _limit_reset(text: str) -> float | None:
    m = re.search(r"\|(\d{9,11})\b", text)  # "...usage limit reached|1700000000"
    return float(m.group(1)) if m else None


class ClaudeCLI:
    """Haiku through the user's own, unmodified `claude` command (their login; no token is read or copied). It runs
    in an empty folder outside every project: inside one, Claude Code also loads that project's CLAUDE.md and
    memory (~4.7k tokens a call in dore's own folder)."""

    def __init__(self, cwd: Path | None = None, model: str = MODEL, timeout: float = 180.0, exe: str | None = None):
        import tempfile
        self.cwd = Path(cwd) if cwd else Path(tempfile.gettempdir()) / "dore-judge"
        self.model, self.timeout = model, timeout
        self.exe = exe or shutil.which("claude")

    def __call__(self, prompt: str, system: str = SYSTEM) -> tuple[str, dict]:
        if not self.exe:
            raise JudgeError("missing", "no claude command")
        self.cwd.mkdir(parents=True, exist_ok=True)
        try:
            r = subprocess.run([self.exe, "-p", "--model", self.model, "--system-prompt", system, *CLI_FLAGS],
                               input=prompt, capture_output=True, text=True, timeout=self.timeout, cwd=self.cwd,
                               env=dict(os.environ, **{SKIP_ENV: "1"}))
        except (OSError, subprocess.TimeoutExpired) as e:
            raise JudgeError("failed", str(e)) from e
        try:
            d = json.loads(r.stdout)
        except ValueError:
            raise JudgeError("failed", (r.stderr or r.stdout)[:300]) from None
        text = str(d.get("result") or "")
        if d.get("is_error") or r.returncode:
            kind = "limit" if re.search(r"limit|429|rate|overloaded|529", text, re.I) else \
                "login" if re.search(r"login|auth|api key|401|403", text, re.I) else "failed"
            raise JudgeError(kind, text, _limit_reset(text))
        u = d.get("usage") or {}
        return text, {"input": int(u.get("input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0))
                      + int(u.get("cache_read_input_tokens", 0)),
                      "output": int(u.get("output_tokens", 0)), "ms": int(d.get("duration_ms", 0)),
                      "usd": float(d.get("total_cost_usd") or 0.0)}


class Recorded:
    """Answers kept in a JSON file by prompt, so a check runs again at 0 tokens; asks `inner` only for new ones."""

    def __init__(self, path: Path, inner=None):
        self.path, self.inner = Path(path), inner
        self.d = json.loads(self.path.read_text()) if self.path.exists() else {}

    def __call__(self, prompt: str, system: str = SYSTEM) -> tuple[str, dict]:
        key = hashlib.sha1((system + "\n" + prompt).encode()).hexdigest()[:16]
        if key in self.d:
            return self.d[key], {"input": 0, "output": 0, "ms": 0, "usd": 0.0, "recorded": True}
        if self.inner is None:
            raise JudgeError("missing", "no recorded answer")
        text, usage = self.inner(prompt, system)
        self.d[key] = text
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.d, indent=0, ensure_ascii=False))
        return text, usage


def judge(items: list[Item], ask) -> tuple[dict[int, list[Verdict]], dict]:
    """One call for a batch, plus the confirming one when it proposed an update: (verdicts per line, usage)."""
    t = time.time()
    answer, usage = ask(batch_text(items))
    verdicts, more = confirm_updates(parse(answer, items), items, ask)
    usage = dict(usage)
    if more:
        for k in ("input", "output", "usd"):
            usage[k] = usage.get(k, 0) + more.get(k, 0)
        usage["calls"] = 2
        usage["recorded"] = bool(usage.get("recorded")) and bool(more.get("recorded"))
    usage.setdefault("ms", int((time.time() - t) * 1000))
    return verdicts, usage
