"""Consolidation: turn queued sentences the user typed into notes, with one Haiku call per batch (`learn.judge`)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from dore.learn.judge import Item, Verdict, grounded, judge

MIN_WORDS, MAX_WORDS = 3, 60   # shorter: "yes", "ok do"; longer: a task or a paste, kept in raw memory only
MAX_MESSAGE_CHARS = 3000       # a longer message is a paste (log, document): 86% of real sentences came from these
MAX_PER_MESSAGE = 20
QUESTION_WORDS = 12            # a shorter question has no room for a fact beside it ("..., since I use X?"); +24%
BATCH = 30                     # sentences per call (~1.5k tokens in), far below Haiku's context
BATCH_CHARS = 6000
NEAR = 0.6                     # an existing note this close is offered to Haiku as "maybe the same thing"
NEIGHBOURS = 3

_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def sentences(message: str) -> list[str]:
    """The sentences of a typed message worth judging, by shape only: not a question, not code or a log, not too
    short or too long; nothing from a paste."""
    out = []
    if len(message) > MAX_MESSAGE_CHARS:
        return out
    for s in _SPLIT.split(message):
        if len(out) == MAX_PER_MESSAGE:
            break
        s = s.strip(" \t-*>•")
        words = s.split()
        if not (MIN_WORDS <= len(words) <= MAX_WORDS) or (s.endswith("?") and len(words) < QUESTION_WORDS):
            continue
        symbols = sum(not (c.isalnum() or c.isspace() or c in ".,'!?-") for c in s)
        if symbols > 0.15 * len(s):  # code, a log line, a table row
            continue
        out.append(s)
    return out


@dataclass
class Said:
    """One queued sentence: what the user typed, where and when."""
    text: str
    project: str
    session: str
    created: float
    id: int | None = None  # its raw-memory row, if any


def batches(queue: list[Said]) -> list[list[Said]]:
    out, cur, size = [], [], 0
    for s in queue:
        if cur and (len(cur) >= BATCH or size + len(s.text) > BATCH_CHARS):
            out.append(cur)
            cur, size = [], 0
        cur.append(s)
        size += len(s.text)
    return out + ([cur] if cur else [])


def _neighbours(store, s: Said) -> list[tuple[int, str]]:
    hits = store.search(s.text, k=NEIGHBOURS, min_similarity=NEAR, project=s.project or None, touch=False,
                        keyword=False)
    return [(m.id, m.content) for m in hits if m.kind in ("statement", "fact", "correction")]


def items_for(store, batch: list[Said]) -> list[Item]:
    return [Item(n, s.text, _neighbours(store, s)) for n, s in enumerate(batch, 1)]


def apply(store_of, items: list[Item], batch: list[Said], verdicts: dict[int, list[Verdict]]) -> dict:
    """Apply a batch's verdicts; `store_of(n)` is the store of line n (one store in use; one per case in checks).
    Returns counts and, per line, the notes it made or matched."""
    made: dict[int, int] = {}  # line -> first note it made or matched (for "same @line")
    stats = {"notes": 0, "rules": 0, "same": 0, "updates": 0, "skipped": 0, "dropped": 0, "lines": {}}
    for it, s in zip(items, batch):
        for v in verdicts.get(it.n) or [Verdict(it.n, "skip")]:
            nid = _apply(store_of(it.n), v, s, batch, made, stats)
            if nid is not None:
                made.setdefault(it.n, nid)
                stats["lines"].setdefault(it.n, []).append(nid)
    return stats


def consolidate(store, batch: list[Said], ask) -> dict:
    """Judge one batch and apply the verdicts. Returns what changed and the call's usage. Raises `JudgeError` on a
    failed call (nothing applied: the batch stays queued)."""
    items = items_for(store, batch)
    verdicts, usage = judge(items, ask)
    stats = apply(lambda n: store, items, batch, verdicts)
    stats["usage"] = usage
    store.save()
    return stats


def _apply(store, v: Verdict, s: Said, batch: list[Said], made: dict[int, int], stats: dict) -> int | None:
    if v.action == "skip":
        stats["skipped"] += 1
        return None
    if v.action == "same":
        nid = v.ref if v.ref is not None else made.get(v.line or 0)
        if nid is None:
            return None
        same_session = v.line is not None and batch[v.line - 1].session == s.session
        if not same_session:  # a repeat in the same session is the same moment, not lasting evidence
            store.said_again(nid, s.created, s.session)
        stats["same"] += 1
        return nid
    if not grounded(v.text, s.text):  # a name or number the user never said
        stats["dropped"] += 1
        return None
    project = s.project if v.scope == "project" else ""
    if v.action != "update" and (old := store.same_words(v.text, project)) is not None:
        store.said_again(old, s.created, s.session)
        if v.action == "rule":  # the note made at once by the word rules: Haiku's judgement and words win
            store.mark_rules({old: True})
            store.set_rule_words(old, v.when, v.forbid)
        stats["same"] += 1
        return old
    nid = store.add(v.text, kind="statement", source="user", trust="verified", project=project, created=s.created)
    store.said_again(nid, s.created, s.session, first=True)
    store.mark_said_in([nid], s.project)
    store.mark_rules({nid: v.action == "rule"} if v.action != "update" else {nid: _was_rule(store, v.ref)})
    if v.action == "rule":
        store.set_rule_words(nid, v.when, v.forbid)
        stats["rules"] += 1
    if v.action == "update" and v.ref is not None:
        store.replace(v.ref, nid, project_only=s.project if project else None)
        stats["updates"] += 1
    else:
        stats["notes"] += 1
    return nid


def _was_rule(store, old: int | None) -> bool:
    return old is not None and store.is_rule(old)
