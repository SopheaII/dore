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

# Where a note lives: what it is about, not whether it says "I".
SCOPE = """user: true of the person in every project: their name, family, pets, home, job, languages, health, their \
own computer and its system, how they want the assistant to work or answer from now on, or the whole team or \
company across all its projects. project: everything \
this codebase uses or needs (packages, package manager, frameworks, tools, versions, deployment, servers, data, \
clients), also when said with "I" ("I use pnpm" here belongs to this project), and a wish about the reply to the \
current task only. If unsure: project."""

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
rule: the sentence tells the assistant how to work or how to answer: an instruction, or a wish or dislike about \
its work or its replies (their length, wording, format, who reads them), also when said inside a request for the \
current task: whether it lasts is shown later, when the user says it again. What to build or change in the product \
itself (a feature, a screen, a title, an image, a file) is not a rule: skip it. Write the instruction in the user's \
own words, as an instruction to the assistant, at most 60 characters; never add advice the user did not give. A task \
may also state a lasting fact: keep that fact.
update: only when the sentence and note #id cannot both be true now: the same subject and the same property with \
a new value. Another thing of the same kind (another item, person, service, job, place or time) is a new fact, \
and note #id stays.
""" + SCOPE + """
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
            v.text = parts[0].strip(" .<>") + "."
            if len(v.text.split()) < 2:  # an empty slot or the form's placeholder ("<note>") echoed back
                continue
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


REFINE = ("Each new line is an instruction a user gave a coding assistant. Saved instructions are listed as 'G<k>: "
          "text'. For each new line, answer one line, nothing else:\n"
          "<letter> G<k>   (it asks for what G<k> asks and nothing more: following G<k> already follows it)\n"
          "<letter> G<k> adds: <what it asks that G<k> does not say>   (the same topic plus a new detail, condition, "
          "person or exception)\n"
          "<letter> same <letter>   (the same as an earlier new line, nothing more)\n"
          "<letter> new   (none of these)\n"
          "Before answering G<k>, check what the new line asks that G<k> does not say; if anything, answer adds.")
_REFINE_LINE = re.compile(r"^\s*([a-z]{1,2})\s*[:.)-]?\s*(?:G(\d+)(?:\s+adds\s*:\s*(.*\S))?|same\s+([a-z]{1,2})|(new))"
                          r"\s*\.?\s*$", re.I)


def letter(k: int) -> str:
    return chr(97 + k) if k < 26 else chr(97 + k // 26 - 1) + chr(97 + k % 26)


def parse_refine(answer: str, n_new: int, n_saved: int) -> dict[str, tuple[str, object]]:
    """Per new line's letter: ("saved", k) or ("adds", k) with k counted from 0, or ("same", letter) of an earlier
    line. Only a line that is the answer alone counts, the last one per letter (Haiku sometimes reasons first)."""
    letters = [letter(k) for k in range(n_new)]
    out: dict[str, tuple[str, object]] = {}
    for raw in answer.splitlines():
        m = _REFINE_LINE.match(raw)
        if not m or (a := m.group(1).lower()) not in letters:
            continue
        out.pop(a, None)
        if m.group(2) and 1 <= int(m.group(2)) <= n_saved:
            out[a] = ("adds" if m.group(3) else "saved", int(m.group(2)) - 1)
        elif m.group(4) and m.group(4).lower() in letters[:letters.index(a)]:
            out[a] = ("same", m.group(4).lower())
    return out


BLOCK_SYSTEM = """You decide what long messages a developer sent to a coding assistant should leave in long-term \
memory. Each block is one message: a list, a table, a document, a config, a log, code or a long request, typed by \
the user or pasted. Most are for the task at hand: skip them. Keep only what will still be true and useful in a \
later session.

Input: "[B] typed" or "[B] pasted, the user's words: ...", then its lines "B.N: line". "B.N-M: (not shown)" marks \
lines of a long block left out.
Answer with these lines only, no explanations, each starting with the block's own number (block 1 here):
1 skip
1 group user|project: <title> | lines: <line numbers and ranges, e.g. 2-11, 14>
1 fact user|project: <note>
1 rule user|project: <note> | when: <words> | not: <words>

group: a list of lasting entries of one kind (people, servers, accounts, settings, endpoints). Title: what the \
entries are and whose ("The user's friends"). lines: the entry lines only, not headings; a range may cover lines \
not shown.
fact: a lasting fact in a block that is not such a list (a setting in a config the user says is theirs): one short \
plain sentence with names and numbers exactly as written. rule: an instruction for all future work ("always", \
"never", "from now on") or a lasting wish about how the assistant should work; when: 1-3 words seen in commands or \
code when it applies; not: words that would break it. A block may give a group, facts and rules.
Never keep passwords, API keys, tokens or private keys: leave those lines out.
user: about the person (their life, people they know) or the whole team or company across projects. project: this \
codebase, its servers, data and clients. If unsure: project.
Skip errors, stack traces, build and test output, bugs or problems to fix, code to write or change, one-time tasks, \
events and plans, and text given only to read, summarize, explain or translate. A list of those is not a group. If \
unsure, skip."""

SHOW_HEAD, SHOW_TAIL, SHOW_CHARS = 20, 5, 160  # lines of a block shown to Haiku: its start and end
SHOW_ALL = 30  # a block this short is shown whole
MIXED = "Some of the input is whole long messages (blocks), each starting with [number]. For those:\n\n"


@dataclass
class Block:
    n: int
    lines: list[str]
    pasted: bool = False
    words: str = ""  # the user's own words beside a paste


@dataclass
class BlockVerdict:
    n: int
    action: str  # skip | group | fact | rule
    scope: str = ""
    title: str = ""
    lines: list[int] = field(default_factory=list)
    text: str = ""
    when: list[str] = field(default_factory=list)
    forbid: list[str] = field(default_factory=list)


def block_text(blocks: list[Block]) -> str:
    """Blocks as Haiku reads them: a long block by its start and end, a line said again only once."""
    out = []
    for b in blocks:
        out.append(f"[{b.n}] " + (f"pasted, the user's words: {_one_line(b.words)[:300] or 'none'}" if b.pasted
                                  else "typed"))
        n, seen = len(b.lines), set()
        shown = range(n) if n <= SHOW_ALL else [*range(SHOW_HEAD), *range(n - SHOW_TAIL, n)]
        for k in shown:
            if n > SHOW_ALL and k == n - SHOW_TAIL:
                out.append(f"{b.n}.{SHOW_HEAD + 1}-{n - SHOW_TAIL}: (not shown)")
            line = _one_line(b.lines[k])[:SHOW_CHARS]
            if line in seen:
                continue
            seen.add(line)
            out.append(f"{b.n}.{k + 1}: {line}")
    return "\n".join(out)


_BLOCK_LINE = re.compile(r"^\s*\[?(\d+)\]?\s*[:.)-]?\s*(skip|group|fact|rule)\b\s*(.*)$", re.I)


def _numbers(spec: str, n: int) -> list[int]:
    out = []
    spec = re.sub(r"\b\d+\.(\d+)", r"\1", spec)  # "1.2-1.11": block 1, lines 2 to 11
    for a, b in re.findall(r"(\d+)(?:\s*-\s*(\d+))?", spec):
        lo, hi = int(a), int(b or a)
        out += [k for k in range(lo, hi + 1) if 1 <= k <= n]
    return list(dict.fromkeys(out))


def parse_blocks(answer: str, blocks: list[Block]) -> dict[int, list[BlockVerdict]]:
    sizes = {b.n: len(b.lines) for b in blocks}
    out: dict[int, list[BlockVerdict]] = {}
    for raw in answer.splitlines():
        m = _BLOCK_LINE.match(raw)
        if not m or int(m.group(1)) not in sizes:
            continue
        n, action, rest = int(m.group(1)), m.group(2).lower(), m.group(3).strip()
        v = BlockVerdict(n, action)
        rest = re.sub(r"^(user|project)\s*\|\s*\w+\s*:", r"\1:", rest, flags=re.I)  # "user|team:" -> "user:"
        if action != "skip":
            s = _SCOPED.match(rest)
            if not s or s.group(1):
                continue
            v.scope = s.group(2).lower()
            parts = [p.strip() for p in s.group(3).split("|")]
            if action == "group":
                spec = next((p for p in parts if p.lower().startswith("lines")), "")
                v.title = parts[0].strip(" .")
                v.lines = _numbers(spec.partition(":")[2], sizes[n])
                if not v.title or not v.lines:
                    continue
            else:
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


def judge_all(items: list[Item], blocks: list[Block], ask) -> tuple[dict, dict, dict]:
    """Sentences and blocks in one call (each call costs ~1k tokens before its content), plus the confirming call when
    a sentence proposed an update: (sentence verdicts, block verdicts, usage). Blocks are numbered after the
    sentences."""
    if not blocks:
        verdicts, usage = judge(items, ask)
        if items and not verdicts:  # an apology or an error worded as a reply: not an answer
            raise JudgeError("failed", "no verdict in the answer")
        return verdicts, {}, usage
    t = time.time()
    system = BLOCK_SYSTEM if not items else SYSTEM + "\n\n" + MIXED + BLOCK_SYSTEM
    answer, usage = ask("\n".join(x for x in (batch_text(items), block_text(blocks)) if x), system)
    blocks_said = parse_blocks(answer, blocks)
    if not blocks_said and not parse(answer, items):
        raise JudgeError("failed", "no verdict in the answer")
    verdicts, more = confirm_updates(parse(answer, items), items, ask) if items else ({}, None)
    usage = dict(usage)
    if more:
        for k in ("input", "output", "usd"):
            usage[k] = usage.get(k, 0) + more.get(k, 0)
        usage["calls"] = 2
    usage.setdefault("ms", int((time.time() - t) * 1000))
    return verdicts, blocks_said, usage


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
