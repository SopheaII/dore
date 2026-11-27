"""Consolidation: turn queued sentences the user typed into notes, with one Haiku call per batch (`learn.judge`).
A long message (a list, a paste, a log) is queued whole and judged as one block: skipped, or kept as a group of
entries word for word, or as the few lasting facts in it."""

from __future__ import annotations

import re
from dataclasses import dataclass

from dore.learn.judge import (REFINE, Block, BlockVerdict, Item, JudgeError, Verdict, block_text, grounded, judge_all,
                              letter, parse_refine)
from dore.learn.statements import COMPACT_SUMMARY, ECHO, entry, message_parts

MIN_WORDS, MAX_WORDS = 3, 200  # shorter: "yes"; real run-ons over 60 words held rules (43 in all history, ~5k tokens)
MAX_MESSAGE_CHARS = 3000       # a longer message is a paste (log, document): 86% of real sentences came from these
MAX_PER_MESSAGE = 20
QUESTION_WORDS = 12            # a shorter question has no room for a fact beside it ("..., since I use X?"); +24%
BATCH = 30                     # sentences per call (~1.5k tokens in), far below Haiku's context
BATCH_CHARS = 6000
BLOCK_CHARS = 8000             # block text per call
RAW_CHARS = 200_000            # a longer message is kept cut to this in raw memory
NEAR = 0.6                     # an existing note this close is offered to Haiku as "maybe the same thing"
NEIGHBOURS = 3
SAME_RULE = 0.95  # near-identical wording only: a real rule and the same rule plus a new detail scored 0.86
ASK_RULE, ASK_RULES = 0.70, 5  # real pairs: repeats in other words 0.74-0.84, different rules Haiku joined 0.57-0.58

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


def is_block(message: str) -> bool:
    """A message judged whole: something pasted, three or more lines, or longer than a typed message."""
    typed, pasted = message_parts(message)
    if not pasted and (not typed or typed.startswith("<") or COMPACT_SUMMARY.match(typed) or ECHO.search(typed)):
        return False
    return bool(pasted) or len([ln for ln in typed.splitlines() if ln.strip()]) >= 3 \
        or len(message) > MAX_MESSAGE_CHARS or len(_SPLIT.split(typed)) > MAX_PER_MESSAGE


def block_of(n: int, message: str) -> Block:
    typed, pasted = message_parts(message)
    if pasted:
        return Block(n, [ln for p in pasted for ln in p.splitlines() if ln.strip()], True, typed)
    lines = [ln for ln in typed.splitlines() if ln.strip()]
    return Block(n, lines if len(lines) >= 3 else [x for x in _SPLIT.split(typed) if x.strip()])


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
    # Saved rules are matched after the call (`refine`), by a stricter test: shown here, Haiku joined different rules.
    return [(m.id, m.content) for m in hits if m.kind in ("statement", "fact", "correction") and not store.is_rule(m.id)]


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
    """Judge one batch and apply the verdicts. Returns what changed and the call's usage; `unanswered`: lines of
    `batch` Haiku gave no verdict for (they stay queued). Raises `JudgeError` on a failed call (nothing applied: the
    batch stays queued). Lines are numbered as in `batch`."""
    whole = {n for n, s in enumerate(batch, 1) if "\n" in s.text or is_block(s.text)}
    lines = [s for n, s in enumerate(batch, 1) if n not in whole]
    items = items_for(store, lines)
    # One call for the sentences and the blocks that fit beside them (~BLOCK_CHARS of block text); more calls only
    # for the blocks that don't. A block is numbered after the call's sentences.
    calls, part, size, first = [], [], 0, len(items)
    for n in sorted(whole):
        b = block_of(first + len(part) + 1, batch[n - 1].text)
        cost = len(block_text([b]))
        if part and size + cost > BLOCK_CHARS:
            calls.append(part)
            part, size, first = [], 0, 0
            b.n = 1
        part.append((n, b))
        size += cost
    calls += [part] if part or (items and not calls) else []
    results, sentence_verdicts = [], {}  # every call first: a failure leaves the whole batch queued
    for k, c in enumerate(calls):
        verdicts, block_verdicts, u = judge_all(items if k == 0 else [], [b for _, b in c], ask)
        sentence_verdicts = verdicts if k == 0 else sentence_verdicts
        at = {b.n: n for n, b in c}
        results.append(({at[j]: vs for j, vs in block_verdicts.items()}, u))
    number = [n for n in range(1, len(batch) + 1) if n not in whole]
    answered = {number[k - 1] for k in sentence_verdicts} | {n for verdicts, _ in results for n in verdicts}
    usage: dict = {}
    stats = {"notes": 0, "rules": 0, "same": 0, "updates": 0, "skipped": 0, "dropped": 0, "lines": {}, "groups": 0,
             "unanswered": [n for n in range(1, len(batch) + 1) if n not in answered]}
    if lines:  # an unanswered line makes nothing here (no verdict = skip) and stays queued (`unanswered`)
        part_stats = apply(lambda n: store, items, lines, sentence_verdicts)
        for k in ("notes", "rules", "same", "updates", "skipped", "dropped"):
            stats[k] += part_stats[k]
        stats["new_rules"] = part_stats.get("new_rules", [])
        stats["lines"].update({number[k - 1]: ids for k, ids in part_stats["lines"].items()})
    for verdicts, _ in results:
        for n, vs in verdicts.items():
            ids = [i for v in vs for i in _apply_block(store, v, batch[n - 1], stats)]
            if ids:
                stats["lines"][n] = ids
            else:
                stats["skipped"] += 1
    joined, u_refine = refine(store, stats.pop("new_rules", []), ask)
    stats["joined"] = len(joined)
    stats["lines"] = {n: [joined.get(i, i) for i in ids] for n, ids in stats["lines"].items()}
    for _, u in results + ([(None, u_refine)] if u_refine else []):
        for k in ("input", "output", "usd", "ms"):
            usage[k] = usage.get(k, 0) + u.get(k, 0)
        usage["calls"] = usage.get("calls", 0) + u.get("calls", 1)
    usage["recorded"] = all(u.get("recorded") for _, u in results)
    stats["usage"] = usage
    store.save()
    return stats


def refine(store, new: list[tuple[int, Said]], ask) -> tuple[dict[int, int], dict]:
    """A new rule note that repeats a saved rule joins it: the saved rule counts as said again and the new note is
    replaced by it (kept). Very close meaning joins by code; a close one gets one Haiku question that shows each
    close saved rule once (`judge.REFINE`), never the lines said before; a far one stays its own rule. A repeat that
    adds a detail stays its own rule and counts as the saved one said again (merging would lose the detail). Returns
    {new id: saved id} and the call's usage."""
    joined: dict[int, int] = {}
    pending: list[tuple[int, Said, list]] = []
    new_ids = {i for i, _ in new}
    for nid, s in new:
        m = store.get(nid)
        saved = [r for r in store.rule_notes(s.project) if r.id not in new_ids and r.project in (m.project, "")]
        if not saved:
            continue
        sims = [float(store._vector(r.id) @ store._vector(nid)) for r in saved]
        ranked = sorted(range(len(saved)), key=lambda k: -sims[k])
        if sims[ranked[0]] >= SAME_RULE:
            _join(store, nid, saved[ranked[0]].id, s, joined)
        elif near := [saved[k] for k in ranked[:ASK_RULES] if sims[k] >= ASK_RULE]:
            pending.append((nid, s, near))
    if not pending:
        return joined, {}
    heads = list({r.id: r for _, _, saved in pending for r in saved}.values())
    text = ("\n".join(f"G{k + 1}: {' '.join(r.content.split())}" for k, r in enumerate(heads)) + "\n\nNew lines:\n"
            + "\n".join(f"{letter(k)}: {' '.join(store.get(nid).content.split())}"
                        for k, (nid, _, _) in enumerate(pending)))
    try:
        answer, usage = ask(text, REFINE)
    except JudgeError:
        return joined, {}  # nothing joined: each stays its own rule until a later batch
    said = parse_refine(answer, len(pending), len(heads))
    at = {letter(k): nid for k, (nid, _, _) in enumerate(pending)}
    for k, (nid, s, saved) in enumerate(pending):
        kind, ref = said.get(letter(k), ("new", None))
        if kind == "adds" and heads[ref].id in {r.id for r in saved}:
            store.said_again(heads[ref].id, s.created, s.session)  # the topic said again; its new detail stays its own
            store.link_rule(nid, heads[ref].id)
            continue
        target = heads[ref].id if kind == "saved" else joined.get(at[ref], at[ref]) if kind == "same" else None
        allowed = {r.id for r in saved} | set(at.values())
        if target is not None and target in allowed and target != nid:
            _join(store, nid, target, s, joined)
    return joined, usage


def _join(store, nid: int, old: int, s: Said, joined: dict[int, int]):
    store.said_again(old, s.created, s.session)
    store.replace(nid, old)
    joined[nid] = old


def _apply_block(store, v: BlockVerdict, s: Said, stats: dict) -> list[int]:
    """A block's verdict: a group of its entry lines, word for word, or a lasting fact or rule from it. A fact or rule
    taken out of pasted text is not the user's word; a pasted list is, when they said what it is (their words beside
    it tell something)."""
    from dore.learn.grammar import tells
    if v.action == "skip":
        return []
    b = block_of(0, s.text)
    if v.action in ("fact", "rule"):
        one = Verdict(v.n, v.action, v.scope, v.text, when=v.when, forbid=v.forbid)
        nid = _apply(store, one, s, [s], {}, stats, trust="unverified" if b.pasted else "verified")
        return [nid] if nid is not None else []
    trust = "verified" if not b.pasted or any(tells(x) for x in _SPLIT.split(b.words) if x.strip()) else "unverified"
    project = s.project if v.scope == "project" else ""
    items = [t for t in (entry(b.lines[k - 1]) for k in v.lines) if len(t.split()) >= 1]
    if not items:
        return []
    ids = store.add_group(v.title, items, trust=trust, project=project, created=s.created, session=s.session)
    store.mark_said_in(ids, s.project)
    stats["groups"] += 1
    stats["notes"] += len(ids) - 1
    return ids


def _apply(store, v: Verdict, s: Said, batch: list[Said], made: dict[int, int], stats: dict,
           trust: str = "verified") -> int | None:
    if v.action == "skip":
        stats["skipped"] += 1
        return None
    if v.action == "same":
        nid = v.ref if v.ref is not None else made.get(v.line or 0)
        if nid is None:
            return None
        if v.ref is None and len(ids := stats["lines"].get(v.line, [])) > 1:  # that line gave several notes: the closest
            vec = store.embedder.embed([s.text])[0]
            nid = max(ids, key=lambda i: float(store._vector(i) @ vec))
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
    nid = store.add(v.text, kind="statement", source="user", trust=trust, project=project, created=s.created)
    store.said_again(nid, s.created, s.session, first=True)
    store.mark_said_in([nid], s.project)
    store.mark_rules({nid: v.action == "rule"} if v.action != "update" else {nid: _was_rule(store, v.ref)})
    if v.action == "rule":
        store.set_rule_words(nid, v.when, v.forbid)
        stats["rules"] += 1
        stats.setdefault("new_rules", []).append((nid, s))
    if v.action == "update" and v.ref is not None:
        store.replace(v.ref, nid, project_only=s.project if project else None)
        stats["updates"] += 1
    else:
        stats["notes"] += 1
    return nid


def _was_rule(store, old: int | None) -> bool:
    return old is not None and store.is_rule(old)
