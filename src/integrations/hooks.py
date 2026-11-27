"""Claude Code hooks: add only the notes a prompt needs, and learn at zero Claude tokens.

`dore-hook prompt` (UserPromptSubmit) and `dore-hook end` (SessionEnd). Nothing is added when nothing matches.
`dore-hook recall <id>` prints every entry of a list (a group note) for Claude, only when it asks.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from dore.config import Config
from dore.learn.grammar import asks, tells, topic_key
from dore.learn.statements import (ASKS_START, CORRECTION_LEAD, IMPLICIT_FEEDBACK, PERSONAL, QUESTION_START,
                                   REASK_SIMILARITY,
                                   REQ_MAX_CHARS, episode_sentences, list_group, message_facts, promoted, requirement_text,
                                   scope_for, user_facts)
from dore.integrations import update
from dore.integrations.project import display_name, project_of
from dore.memory import SEARCHABLE_SQL, MemoryStore, episodes, on_trial, replaces, same_frame
from dore.memory.activation import strength, THRESHOLD


def _rules_version() -> str:
    """Changes whenever the learning rules change, so raw memory is judged again with the new rules."""
    learn = Path(__file__).resolve().parent.parent / "learn"
    h = hashlib.sha1()
    for name in ("statements.py", "grammar.py"):
        try:
            h.update((learn / name).read_bytes())
        except OSError:
            pass
    return h.hexdigest()[:12]


RULES_VERSION = _rules_version()
# A question may recall a raw sentence from an earlier session that tells something (not a request).
# Off (> 1): on the real replay (1,036 prompts) the bar 0.75 showed one on 11 questions, ~3 useful (an alert
# preference, a feature design) and ~8 noise (old requests); 0.80 showed 1, noise.
# The embedder can't tell a lasting sentence from chatter (memory-learning.md). Raw memory still feeds
# `consolidate`, and the next step (said again in another session) needs no bar on similarity alone.
EPISODE_STRONG = 1.01

STRONG = 0.65          # prompt-to-note similarity needed to add a note
# Only notes close to the best match: on a broad prompt many loosely related notes all score
# 0.65-0.73 ("your name is dore" matched every prompt saying "dore"). Measured on 18 labelled
# prompts (2026-11-25): same useful notes found (7/8), wrong extra notes 9 -> 1.
GAP = 0.05
# Notes addressed to an assistant ("your name is dore") are not about the user's work; shown to
# Claude they matched every prompt saying "dore" and name the wrong assistant.
ABOUT_ASSISTANT = re.compile(r"^\s*(your\b|you are\b|you'?re\b)", re.I)
SAME_THING = 0.72  # note-to-note: same thing (updates 0.73-0.82; but different facts reach 0.82 too, so this only adds, never hides)
MAX_NOTES = 3
MAX_CHARS = 160        # per note shown
MAX_TOTAL_CHARS = 600  # everything one prompt adds (~150 tokens; AGENTS.md / hook-cost skill)
RULES_PER_SESSION = 600  # rules no message asked for, per session (the old block's most: 6 rules, 600 chars)
CONFLICT_SIMILARITY = 0.7  # a correction marks wrong only notes this close (and one detail changed)


def _project(cwd: str | None) -> str:
    """The project key of a session started in `cwd`: its git repo (`integrations.project`)."""
    return project_of(cwd).key


_ADOPTED: set = set()  # places whose older keys were already moved, in this process


def resolve_project(store: MemoryStore, cwd: str | None, start: str | None = None) -> str:
    """Project key for `cwd`; on first use, moves notes stored under older keys for the same place."""
    p = project_of(cwd, start)
    if p not in _ADOPTED:
        _ADOPTED.add(p)
        if p.aliases:
            store.rename_project(list(p.aliases), p.key)
    return p.key


class _State:
    """Per-session memory of what was already shown (so nothing is sent twice)."""

    def __init__(self, data_dir: Path, session_id: str):
        self.session = session_id
        self.path = data_dir / "hook-state" / f"{re.sub(r'[^A-Za-z0-9_-]', '', session_id) or 'none'}.json"
        try:
            self.d = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.d = {"shown": [], "rules_done": False}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.d))
        # Forget sessions older than a week.
        for p in self.path.parent.glob("*.json"):
            if time.time() - p.stat().st_mtime > 7 * 86400:
                p.unlink(missing_ok=True)


def _line(mid: int, content: str, label: str = "", created: float | None = None, limit: int = MAX_CHARS) -> str:
    text = content if len(content) <= limit else content[:limit] + "…"
    date = f" ({time.strftime('%Y-%m-%d', time.localtime(created))})" if created else ""
    return f"- #{mid}{date}{label} {text}"


def _showable(m) -> bool:
    """Notes the hook may add: not wrong, not about dore itself, and a requirement said only once is
    kept but not shown (most are one-off tasks)."""
    return (m.trust != "wrong" and not ABOUT_ASSISTANT.match(m.content)
            and not (m.kind == "requirement" and m.trust != "verified" and m.similarity < REQ_SHOW))


RULE_FORM = "1"  # version of how instructions are recognised (`grammar.instruction`); a change re-marks all notes


def mark_instructions(store: MemoryStore, ids: list[int]):
    """Mark which of these notes are instructions about how to work, by the sentence's form."""
    from dore.learn.grammar import instruction
    if ids:
        store.mark_rules({m.id: instruction(m.content) for m in store.get_many(list(ids)).values()})


def about_work(store: MemoryStore, text: str) -> bool:
    """A personal preference is about the work when most of its words come up in Claude's replies ("I don't want
    long answers": answers, long; "I don't like coffee": never). Evidence from this machine, no word list; with no
    replies counted yet, unsure: not brought up unprompted."""
    from dore.learn.grammar import PREFER, STANDING
    from dore.memory.rules import LIGHT_VERBS, PREPOSITIONS
    # The topic only: not grammar words (prepositions, light verbs, pronouns) nor the instruction's own form
    # ("prefer", "always", "never").
    form = LIGHT_VERBS | PREPOSITIONS | PREFER | STANDING | {"i", "me", "my", "we", "our", "don't", "not", "no"}
    words = reply_words(text) - {w[:6] for w in form}
    n, df = store.reply_counts(words)
    if not words or not n:
        return False
    return sum(df.get(w, 0) > 0 for w in words) * 2 >= len(words)


def rules_in_mind(store: MemoryStore, project: str, shown: set, vec=None) -> list:
    """Proven standing rules strong enough to come to mind without a cue (`memory.activation`: every repeat or use
    adds strength, strength fades with time, often-repeated rules fade slowly), strongest first, those close to the
    session's first prompt before others (context primes memory). Reads only rule notes (`MemoryStore.rule_notes`)."""
    now, out = time.time(), []
    for m in store.rule_notes(project):
        # A request's whole text asks for something done now: only the rule parts taken out of it (`RULE_SOURCE`)
        # and statements may come to mind unprompted; the request itself only when a message matches it.
        if m.kind == "requirement" and m.source != RULE_SOURCE:
            continue
        if m.id in shown or on_trial(m) or not _showable(m) or (not m.rule_when and PERSONAL.search(m.content)
                                                                and not about_work(store, m.content)):
            continue
        b = strength(m.times_seen + m.uses, m.created, max(m.created, m.last_seen or 0, m.last_used or 0), now)
        if b >= THRESHOLD:
            near = float(store._vector(m.id) @ vec) if vec is not None else 0.0
            out.append((b + near, m))
    return [m for _, m in sorted(out, key=lambda x: -x[0])]


def prompt_context(store: MemoryStore, prompt: str, project: str, state: _State) -> str:
    shown = set(state.d["shown"])
    cands: list[tuple[int, str, bool]] = []  # (id, line, is_note): notes that answer the prompt, then rules
    rules_due = not state.d["rules_done"]
    state.d["rules_done"] = True
    hits = store.search(prompt[:2000], k=MAX_NOTES + len(shown), min_similarity=STRONG,
                        project=project or None, touch=False)
    asked = _asks(prompt)
    hits = [m for m in hits if _showable(m) and (asked or not (on_trial(m) or m.kind == "group"))]
    own = [m for m in hits if m.project == project and project]
    hits = [m for m in hits if m.project or not any(replaces(m.content, k.content) or replaces(k.content, m.content)
                                                    for k in own)]
    if hits:  # keep notes near the best match; a note below STRONG got in by an exact ID/keywords
        top = max(m.focus for m in hits)  # hub-corrected (`MemoryStore.search`); STRONG stays on raw similarity
        near = [m for m in hits if m.focus >= top - GAP or m.similarity < STRONG]
        newer = [m for m in hits if m not in near and m.similarity >= STRONG and m.focus >= top - 2 * GAP and any(
            m.created > k.created and float(store._vector(m.id) @ store._vector(k.id)) >= SAME_THING for k in near)]
        hits = sorted(near + newer, key=lambda m: -m.created if m in newer else 0)  # newer first
    notes = [m for m in hits if m.id not in shown][:MAX_NOTES]
    heads = store.get_many(list({m.group_id for m in notes if m.group_id}))
    in_group: dict[int, int] = {}
    for m in notes:
        label = f" (from project {display_name(m.project)})" if m.project not in (project, "") else ""
        if m.kind == "requirement":
            label += " (your earlier request)" if m.trust != "verified" else " (your repeated request)"
        text, limit = m.content, REQ_MAX_CHARS + 1 if m.kind == "requirement" else MAX_CHARS
        if m.kind == "group":
            if any(x.group_id == m.id for x in notes) or not (size := store.group_size(m.id)):
                continue  # its entries below say it, or it has none left
            text = f"{m.content} ({size} entries, #{m.id})"
            in_group.setdefault(m.id, 0)
            limit += len(text)
        elif (head := heads.get(m.group_id)) is not None:
            in_group[head.id] = in_group.get(head.id, 0) + 1
            if in_group[head.id] > 1:  # the title once per list
                cands.append((m.id, "  " + _line(m.id, m.content, label, limit=limit), True))
                continue
            text = f"{head.content}: {m.content}"
            limit += len(head.content)
        cands.append((m.id, _line(m.id, text, label, m.created, limit=limit), True))
    for h, n in in_group.items():  # after the group's last entry shown
        if n and (more := store.group_size(h) - n) > 0:
            at = max(k for k, (mid, _, _) in enumerate(cands) if mid in {x.id for x in notes if x.group_id == h})
            cands.insert(at + 1, (0, f"  +{more} more in #{h}", False))
    if any(store.group_size(h) > n for h, n in in_group.items()):  # how to get them, once
        cands.append((0, f"(all entries of a list: {recall_command(0).rsplit(' ', 1)[0]} <#>)", False))
    vec = getattr(store, "last_query_vector", None)
    # Rules in mind: at the session start every proven rule strong enough (`rules_in_mind`), the ones closest to the
    # first prompt first; those that did not fit come with the next prompts. No fixed number of rules.
    in_notes = {m.id for m in notes}  # a note that is also a rule is shown once, as the note that matched
    pending = [i for i in state.d.get("rules_pending", []) if i not in shown and i not in in_notes]
    if rules_due:
        # One budget per session for rules no message asked for (the old block's maximum, ~150 tokens), so the
        # README's "only the notes that match your message" stays true; no count: short rules, more of them.
        # The strongest and closest to the first prompt win; the rest are still found when a message matches.
        room, pending, family, picked = RULES_PER_SESSION, [], store.rule_family(), set()
        in_mind = rules_in_mind(store, project, shown | in_notes, vec)
        heads = {m.id for m in in_mind}
        for m in in_mind:
            size = len(_line(m.id, m.content, created=m.created, limit=len(m.content))) + 1
            # One line per family: its head (the rule first said) when strong enough, else its strongest repeat with a
            # detail; the others come when a message matches.
            if family.get(m.id, m.id) in heads - {m.id}:
                continue
            if size <= room and family.get(m.id, m.id) not in picked:
                picked.add(family.get(m.id, m.id))
                pending.append(m.id)
                room -= size
    rows = store.get_many(pending) if pending else {}
    for i in pending:  # in rank order
        if (m := rows.get(i)) is not None:
            cands.append((m.id, _line(m.id, m.content, created=m.created, limit=len(m.content)), False))
    rule_ids = set(pending)
    if vec is not None and EPISODE_STRONG <= 1 and _asks(prompt):
        said = set(state.d.get("episodes_shown", []))
        for eid, content, created, _ in episodes.recall(store, vec, project, state.session, said,
                                                        min_similarity=EPISODE_STRONG):
            cands.append((-eid, _line(eid, content, " (you said once, not confirmed)", created).replace(
                f"#{eid} ", f"#e{eid} ", 1), False))
            state.d["episodes_shown"] = sorted(said | {eid})
    # Token cap: add lines while they fit; a line left out may still be shown on a later prompt.
    lines, used, last_shown, later = [], 0, [], []
    for mid, line, is_note in cands:
        if used + len(line) > MAX_TOTAL_CHARS:
            shown.discard(mid)
            if mid in rule_ids:
                later.append(mid)  # a rule never cut: it comes whole with a later prompt
            continue
        lines.append(line)
        used += len(line)
        if mid > 0:  # raw-memory lines (negative ids) are tracked in `episodes_shown`
            shown.add(mid)
        if is_note:
            last_shown.append(mid)
    state.d["shown"] = sorted(shown)
    state.d["rules_pending"] = later
    state.d["last_shown"] = last_shown  # judged by the user's next prompt (react) and Claude's reply (judge_last)
    best = max((m for m in notes if m.id in set(last_shown)), key=lambda m: m.similarity, default=None)
    # Only the best match is on test (a side note beside a better one says nothing); rules too, like any note.
    state.d["last_trial"] = [best.id] if best is not None and (on_trial(best) or best.kind == "requirement") else []
    if not lines:
        return ""
    return "dore memory (use if relevant; trust user code/instructions over it):\n" + "\n".join(lines)


def _log_events(transcript: Path | None, max_bytes: int | None = None) -> list[dict]:
    """Events of a Claude Code session log (JSONL), only its last `max_bytes` when given."""
    if not transcript:
        return []
    try:
        with open(transcript, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes) if max_bytes else 0)
            lines = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []
    if max_bytes and size > max_bytes:
        lines = lines[1:]  # read from the middle of a line
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def typed_text(ev: dict) -> str | None:
    """The text of a message the user typed. None for tool results, meta events, sub-agents and what Claude Code
    itself writes into the log as a user event (command output, task notifications: wrapped in tags)."""
    if ev.get("type") != "user" or ev.get("isMeta") or ev.get("isSidechain"):
        return None
    content = (ev.get("message") or {}).get("content")
    if isinstance(content, list):
        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return content if isinstance(content, str) and content.strip() and not content.lstrip().startswith("<") else None


def _answer_blocks(ev: dict) -> list[dict]:
    if ev.get("type") != "assistant" or ev.get("isSidechain"):
        return []
    return [b for b in (ev.get("message") or {}).get("content") or [] if isinstance(b, dict)]


def _user_messages(transcript: Path) -> list[str]:
    return [t for ev in _log_events(transcript) if (t := typed_text(ev)) is not None]


LOG_BYTES = 2_000_000  # end of the session log read per prompt: most real answers fit (claude-code.md)


def assistant_text(transcript: Path | list[dict] | None, max_bytes: int = LOG_BYTES) -> str:
    """Claude's recent replies in this session, to recognise the user pasting them back. `transcript`: the log, or
    its events already read."""
    events = transcript if isinstance(transcript, list) else _log_events(transcript, max_bytes)
    return "\n".join(b.get("text", "") for ev in events for b in _answer_blocks(ev) if b.get("type") == "text")


MAX_ACTIONS = 100_000  # characters of Claude's actions read per turn (commands, code it wrote)


def _strings(x) -> list[str]:
    if isinstance(x, str):
        return [x]
    if isinstance(x, dict):
        return [s for v in x.values() for s in _strings(v)]
    if isinstance(x, list):
        return [s for v in x for s in _strings(v)]
    return []


def last_turn(transcript: Path | list[dict] | None, max_bytes: int = LOG_BYTES) -> tuple[str, str]:
    """(Claude's text, Claude's actions) in its answer to the user's previous message, from the session log.
    Actions are what it did: the inputs of its tool calls (commands run, code written, files edited). The answer
    runs from one typed message to the next, whatever Claude Code logs in between. If the log already holds the new
    message, the answer before it. ("", "") without a log. `transcript`: the log, or its events already read."""
    turns: list[tuple[list[str], list[str]]] = [([], [])]
    for ev in transcript if isinstance(transcript, list) else _log_events(transcript, max_bytes):
        if typed_text(ev) is not None:
            turns.append(([], []))
        for b in _answer_blocks(ev):
            if b.get("type") == "text":
                turns[-1][0].append(b.get("text", ""))
            elif b.get("type") == "tool_use":
                turns[-1][1].extend(_strings(b.get("input")))
    if not (turns[-1][0] or turns[-1][1]) and len(turns) > 1:
        turns.pop()
    text, acts = turns[-1]
    return "\n".join(text), "\n".join(acts)[:MAX_ACTIONS]


def reply_words(text: str) -> set[str]:
    """Content words of a text, cut to 6 letters (so "deploys"/"deployed" match), without stopwords."""
    from dore.memory.rules import STOPWORDS
    words = (w.rstrip(".+#-") for w in re.findall(r"[a-z0-9][a-z0-9.+#-]*", text.lower()))  # "R2." -> "r2"
    return {w[:6] for w in words if w not in STOPWORDS and len(w) > 1}


CLEAR_USE = 0.6
CHANCE = 0.01  # the usual 1% level: the reply would hold these words by luck at most this often


def use_check(store: MemoryStore, note: str, prompt: str, reply_set: set[str]) -> tuple[bool, bool]:
    """(used, testable) for a shown note and Claude's reply; not testable when a match could be luck."""
    import math
    new = reply_words(note) - reply_words(prompt)
    if not new:
        return False, False
    n, df = store.reply_counts(new)
    luck = {w: (df.get(w, 0) + 1) / (n + 2) for w in new}  # chance that a reply contains w
    if math.prod(luck.values()) > CHANCE:
        return False, False
    got = new & reply_set
    idf = {w: -math.log(luck[w]) for w in new}
    used = bool(got) and sum(idf[w] for w in got) / sum(idf.values()) >= CLEAR_USE \
        and math.prod(luck[w] for w in got) <= CHANCE
    return used, True


def practised(store: MemoryStore, rule: str, text_words: set[str], action_words: set[str],
              words: tuple[list[str], list[str]] | None = None) -> bool:
    """Claude acted on a standing rule: most of what the rule wants (by rarity in Claude's replies) is in its
    text or actions, at least part of it in what it did, and nothing the rule forbids is in what it did
    ("never use print, use the logger": `logger.info` is practice, `print(` is not). A rule that only forbids
    ("never use tabs") can't be seen being followed: doing nothing leaves no trace."""
    import math
    from dore.memory.rules import LIGHT_VERBS
    if words is not None:  # the rule's situation and forbidden words, given when it was learned (`learn.judge`)
        wanted, forbidden = words
    else:
        from dore.learn.grammar import rule_parts
        wanted, forbidden = rule_parts(rule)
    # Light verbs ("use", "run") say nothing about which rule it is: "always use pnpm" wants pnpm.
    want = reply_words(" ".join(wanted)) - {w[:6] for w in LIGHT_VERBS}
    if not want or (reply_words(" ".join(forbidden)) - want) & action_words:
        return False
    got = want & (text_words | action_words)
    if not got & action_words:
        return False
    n, df = store.reply_counts(want)
    idf = {w: math.log((n + 1) / (df.get(w, 0) + 1)) + 1 for w in want}
    return sum(idf[w] for w in got) / sum(idf.values()) >= CLEAR_USE


def practise_rules(store: MemoryStore, state: "_State", project: str, text_words: set[str], action_words: set[str]):
    """Strengthen the standing rules Claude acted on in its last answer (once per rule per session): a habit grows
    by being done, not by being shown (`memory.activation`). Reads only rule notes (indexed)."""
    if not action_words or project is None:
        return
    done = set(state.d.get("rules_practised", []))
    now = time.time()
    for m in store.rule_notes(project):
        # Only rules the user made rules (said in two sessions): doing a task looks like following a habit ("it
        # should count pages" was "practised" by Claude implementing it, real replay), so practice keeps a rule
        # alive but never makes one.
        words = (json.loads(m.rule_when), json.loads(m.rule_not or "[]")) if m.rule_when else None
        # A rule Haiku judged a lasting rule may be proven by practice; an old word-rule note only once proven.
        if m.id not in done and (words or not on_trial(m)) and practised(store, m.content, text_words,
                                                                           action_words, words):
            store.db.execute("UPDATE memories SET uses = uses + 1, last_used = ? WHERE id=?", (now, m.id))
            done.add(m.id)
    store.db.commit()
    state.d["rules_practised"] = sorted(done)


def judge_last(store: MemoryStore, state: "_State", reply: str, actions: str = "", project: str | None = None) -> list[int]:
    """Check last prompt's shown notes against Claude's reply: used notes gain a use, unused trial notes
    count a try (archived after `ARCHIVE_TRIES`). Returns archived ids."""
    shown, prompt = state.d.get("last_shown", []), state.d.get("last_prompt", "")
    if not reply and not actions:
        return []
    key = message_key(reply + "\n" + actions[:2000])
    if state.d.get("judged") == key:  # one prompt handled twice (helper timeout + inline run)
        return []
    state.d["judged"] = key
    rset = reply_words(reply)
    gone: list[int] = []
    if shown:
        checks = {m.id: use_check(store, m.content, prompt, rset) for m in store.get_many(shown).values()}
        used = {i for i, (u, _) in checks.items() if u}
        last_trial = set(state.d.get("last_trial", []))
        trial = [i for i in shown if i in last_trial and checks.get(i, (False, False))[1]]
        for i in used - set(trial):
            store.db.execute("UPDATE memories SET uses = uses + 1, last_used = ? WHERE id=?", (time.time(), i))
        store.db.commit()
        gone = store.mark_tried(trial, used)
    practise_rules(store, state, project, rset, reply_words(actions))
    store.count_reply(rset)
    return gone


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def not_echoed(facts: list[str], echo: str) -> list[str]:
    """Facts the assistant did not already write: a sentence of Claude's pasted back is not a new
    fact from the user (any language; exact words, at least 5)."""
    if not echo:
        return facts
    said = _norm(echo)
    return [f for f in facts if len(_norm(f).split()) < 5 or _norm(f) not in said]


def message_key(text: str) -> str:
    """Short fingerprint of a message, to skip at session end what a prompt already taught."""
    return hashlib.sha1(" ".join(text.split()).encode()).hexdigest()[:16]


REQ_SHOW = 1.01  # a requirement said only once is kept but not shown (0.75 doubled tokens: 8.3 -> 17.6 per prompt)
REQ_SAME = 0.85  # the same requirement said again (0.75 merged different requests about one screen)


RULE_SOURCE = "user-rule"  # the negated verb phrase of a long request ("do not touch old code")
RULE_SAME = 0.85  # real use: true repeats 0.86-0.93, the next pair (a different rule) 0.77


DUPLICATE_WINDOW = 600  # s: the same text again this soon is one message handled twice, not a repeat


def _handled_just_now(store: MemoryStore, gist: str, project: str) -> int | None:
    """The hidden note of this very message if it was saved minutes ago: one message handled twice
    (helper timeout + inline run), not the user saying it again."""
    row = store.db.execute(
        "SELECT id FROM memories WHERE kind='requirement' AND source='user' AND content=? AND project=? "
        "AND coalesce(last_seen, created) > ?", (gist, project, time.time() - DUPLICATE_WINDOW)).fetchone()
    return row[0] if row else None


def _seen_again(store: MemoryStore, m, session_ids: set[int]) -> int:
    """Count a hidden note said again. It becomes verified (shown) only when the repeat comes from
    another session: said again in the same session it is still the task at hand ("please test …"
    twice in one chat was shown as "your repeated request", 2026-11-26)."""
    if m.id in session_ids:
        return m.id
    store.db.execute("UPDATE memories SET times_seen=times_seen+1, last_seen=? WHERE id=?", (time.time(), m.id))
    if m.trust != "verified":
        store.set_trust(m.id, "verified")
    store.db.commit()
    return m.id


def save_rule_cores(store: MemoryStore, text: str, project: str, session_ids: set[int] = frozenset()) -> list[int]:
    """Keep each standing rule inside a long request ("..., and do not touch old code") as a short
    hidden note. Said again in other words in a later session (in this project, or in another one),
    it is verified and shown: the user repeating a rule is the signal that it lasts. The gist is kept
    as well."""
    from dore.learn.grammar import rule_cores
    ids = []
    for core in rule_cores(text):
        same = [m for m in store.search(core, k=3, min_similarity=RULE_SAME, touch=False, keyword=False)
                if m.source == RULE_SOURCE and m.kind == "requirement"]
        here = [m for m in same if m.project == project]
        if here:
            ids.append(_seen_again(store, here[0], session_ids))
        else:  # said before only in another project: lasting for this user, kept in this project
            ids.append(store.add(core, kind="requirement", source=RULE_SOURCE, project=project,
                                 trust="verified" if any(m.id not in session_ids for m in same) else "unverified"))
    mark_instructions(store, ids)
    return ids


def save_requirement(store: MemoryStore, text: str, project: str, session_ids: set[int] = frozenset()) -> int | None:
    """Keep the gist of a long instruction as a low-trust project requirement. Said again (close in
    meaning) in a later session, the existing note is strengthened (seen again, verified: the user
    repeated it) instead of stored twice. Returns the note id."""
    if not text:
        return None
    same = [m for m in store.search(text, k=3, min_similarity=REQ_SAME, project=project or None, touch=False,
                                    keyword=False) if m.kind == "requirement" and m.project == project
            and m.source != RULE_SOURCE]
    if same:
        return _seen_again(store, same[0], session_ids)
    rid = store.add(text, kind="requirement", source="user", trust="unverified", project=project)
    mark_instructions(store, [rid])
    return rid


def similar_fn(store: MemoryStore):
    """Meaning similarity of two short texts (store's embedder)."""
    def similar(a: str, b: str) -> float:
        v = store.embedder.embed([a, b])
        return float(v[0] @ v[1])
    return similar


def save_facts(store: MemoryStore, facts: list[str], project: str, created: float | None = None) -> list[int]:
    """Store user statements (verified); each replaces older notes it updates. `created`: when it was
    said, for a fact learned later from raw memory."""
    ids = []
    scopes = {f: ("" if promoted(store, f, f, project) else scope_for(f, project)) for f in facts}
    for scope in dict.fromkeys(scopes.values()):
        group = [f for f in facts if scopes[f] == scope]
        ids += store.add_many(group, kind="statement", source="user", trust="verified", project=scope,
                              supersede=True, keys=[topic_key(f) for f in group], created=created)
    store.mark_said_in(ids, project)
    mark_instructions(store, ids)
    return ids


def learn_message(store: MemoryStore, msg: str, project: str, echo: str = "",
                  session_ids: set[int] | None = None, session: str = "", raw: bool = True) -> list[int]:
    """Everything one user message teaches, in one place (prompt hook, SessionEnd, opencode bridge):
    short facts (not ones Claude wrote and the user pasted back); else the gist of a long instruction
    as a hidden requirement. Every other sentence the user typed is kept as raw memory (`episodes`).
    `session_ids`: hidden notes this session already saved (a repeat inside one session doesn't make
    them lasting); it grows with this message's. `raw=False` (the Haiku learner): short facts and lists only."""
    seen = session_ids if session_ids is not None else set()
    if (group := list_group(msg)) and len(items := not_echoed(group[1], echo)) >= 2:
        ids = store.add_group(group[0], items, project=scope_for(group[0], project), session=session)
        store.mark_said_in(ids, project)
        seen |= set(ids)
        return ids
    facts = not_echoed(message_facts(msg, similar_fn(store)), echo)
    ids = save_facts(store, facts, project)
    # Said again in the same session is the same moment, not lasting evidence: the repeat doesn't count
    # (a note is proven only when said again in another session, `memory.on_trial`).
    again = [i for i in ids if i in seen]
    if again:
        store.db.execute(f"UPDATE memories SET times_seen = MAX(1, times_seen - 1) WHERE id IN "
                         f"({','.join('?' * len(again))})", again)
        store.db.commit()
    seen |= set(ids)
    if not raw:  # Haiku judges the whole message and makes its rules: hidden word-rule copies would only be junk
        return ids
    episodes.add(store, not_echoed(episode_sentences(msg, facts), echo), project, session, judged=RULES_VERSION)
    req = not_echoed([requirement_text(msg)], echo)
    if req and req[0] and not ids and (dup := _handled_just_now(store, req[0], project)):
        seen.add(dup)
        return [dup]
    if req and req[0]:
        seen |= set(save_rule_cores(store, req[0], project, seen))  # rules inside any long message
        if not ids:
            rid = save_requirement(store, req[0], project, seen)
            ids = [rid] if rid else []
            seen |= set(ids)
    return ids


def mark_provisional(store: MemoryStore, note_ids: list[int], episode_ids: list[int], session: str = ""):
    """Notes the word rules just made from a message whose sentences wait for Haiku. With no sentence queued (all
    filtered out), there is nothing for Haiku to judge: the note stays as the word rules made it."""
    if note_ids and episode_ids:
        store.db.executemany("INSERT OR REPLACE INTO provisional (note_id, episodes) VALUES (?, ?)",
                             [(i, json.dumps(episode_ids)) for i in note_ids])
        # Haiku judging the same sentence later is not the user saying it again.
        store.db.executemany("INSERT OR IGNORE INTO note_sessions (note_id, session) VALUES (?, ?)",
                             [(i, session) for i in note_ids])
        store.db.commit()


def queue_message(store: MemoryStore, msg: str, project: str, echo: str = "", session: str = "",
                  count_repeats: bool = True) -> list[int]:
    """Haiku learner: keep the message's sentences (a long message whole) in raw memory, where they wait for the
    next batch (`integrations.learner`). Nothing is judged here: no model, ~0.1 ms. The same sentence again, once it
    became a note, counts as said again at once."""
    from dore.learn.consolidate import RAW_CHARS, is_block, sentences
    said = [msg[:RAW_CHARS].strip()] if is_block(msg) else sentences(msg)  # a long message is judged whole
    ids = episodes.add(store, not_echoed(said, echo), project, session)
    for eid in ids if count_repeats else ():  # the word rules count exact repeats when they run too
        row = store.db.execute("SELECT note_id FROM episodes WHERE id=?", (eid,)).fetchone()
        if row and row[0]:
            store.said_again(row[0], time.time(), session)
    store.db.commit()
    return ids


def save_session(store: MemoryStore, transcript: Path, project: str,
                 learned: set[str] | None = None, session_ids: set[int] | None = None, session: str = "",
                 learn: str = "rules") -> list[int]:
    """Session end: store statements from messages the prompt hook didn't already handle
    (`learned` = their message_key), e.g. when the hook timed out."""
    learned = learned or set()
    session_ids = set(session_ids or ())
    echo = assistant_text(transcript, max_bytes=4_000_000)
    if learn == "haiku":
        for msg in _user_messages(transcript):
            if message_key(msg) not in learned:
                queue_message(store, msg, project, echo, session)
        store.save(force=True)
        return []
    ids = [i for msg in _user_messages(transcript) if message_key(msg) not in learned
           for i in learn_message(store, msg, project, echo, session_ids, session)]
    store.save(force=True)
    return ids


def _is_question(text: str) -> bool:
    t = text.strip()
    return t.endswith("?") or bool(QUESTION_START.match(t))


def _asks(text: str) -> bool:
    """A real question (question mark, question word or auxiliary first, or an auxiliary before its
    subject), not a "please ..." request, which `_is_question` also counts."""
    t = text.strip()
    return t.endswith("?") or bool(ASKS_START.match(t)) or asks(t[:300])


def react(store: MemoryStore, prompt: str, state: _State) -> str:
    """Learn from how the user's new prompt reacts to the notes shown with the previous one:
    - "No, X" / "Actually X": notes shown last time that X changes by one detail are marked
      wrong (kept). Facts in X are saved by learn_prompt and replace what they update;
    - the same question again: the notes shown didn't help (-1);
    - anything else after a question: they were fine (+1)."""
    last, shown = state.d.get("last_prompt", ""), state.d.get("last_shown", [])
    if not last:
        return ""
    if CORRECTION_LEAD.match(prompt.strip()):
        fixes = user_facts(prompt)
        if fixes:
            # Every note Claude saw this session, not only the last ones: the rules shown at the
            # session start ("max discount is 50%") were never corrected (2026-11-25).
            seen = list(dict.fromkeys([*shown, *state.d.get("shown", [])]))
            wrong = [m.id for fix in fixes for m in store.similar(fix, seen)
                     if m.similarity >= CONFLICT_SIMILARITY and same_frame(m.content, fix)]
            store.demote(list(dict.fromkeys(wrong)), by_user=True)
            return "correction"
    if not shown or not _is_question(last):
        return ""
    v = store.embedder.embed([prompt[:2000], last[:2000]])
    reask = (_is_question(prompt) and float(v[0] @ v[1]) >= REASK_SIMILARITY
             and not same_frame(last, prompt))
    for mid in shown:
        store.feedback(mid, -IMPLICIT_FEEDBACK if reask else IMPLICIT_FEEDBACK)
    return "reask" if reask else "moved_on"


def on_prompt(store: MemoryStore, prompt: str, project: str, state: _State, echo: str = "", reply: str = "",
              actions: str = "", learn: str = "rules") -> str:
    """Everything the prompt hook does, in order: judge the last notes, learn the user's new
    statements right away (so a correction counts in this session, not only at its end), then
    pick notes for this prompt. Returns the text to add ("" = nothing, 0 tokens)."""
    state.d["archived"] = state.d.get("archived", []) + judge_last(store, state, reply, actions, project)
    queued = queue_message(store, prompt, project, echo, state.session, count_repeats=False) \
        if learn == "haiku" else []
    state.d["last_signal"] = react(store, prompt, state)
    session_ids = set(state.d.get("saved", []))
    first_new = (store.db.execute("SELECT MAX(id) FROM memories").fetchone()[0] or 0) + 1
    new_ids = learn_message(store, prompt, project, echo, session_ids, state.session, raw=learn != "haiku")
    if learn == "haiku":  # known at once, provisional: Haiku's batch keeps or archives them (`learner.settle`)
        mark_provisional(store, [i for i in new_ids if i >= first_new], queued, state.session)
    state.d["saved"] = sorted(session_ids)
    # Handled, whatever it taught (also only hidden rules): SessionEnd must not count it a second time.
    state.d.setdefault("handled", []).append(message_key(prompt))
    if new_ids:
        state.d.setdefault("learned", []).append(message_key(prompt))  # stored a note (checks read this)
        # Never echo back what the user just said.
        state.d["shown"] = sorted(set(state.d["shown"]) | set(new_ids))
    text = prompt_context(store, prompt, project, state)
    state.d["last_prompt"] = prompt[:2000]
    store.save()
    return text


def recall_command(head: int) -> str:
    exe = Path(sys.executable).with_name("dore-hook.exe" if os.name == "nt" else "dore-hook")
    return f'"{exe}" recall {head}' if " " in str(exe) else f"{exe} recall {head}"


def recall_text(store: MemoryStore, args: list) -> str:
    """Every entry of the groups named (`dore-hook recall 41`): what Claude asks for when the lines shown were not
    enough."""
    out = []
    for a in args:
        a = str(a).lstrip("#")
        g = int(a) if a.isdigit() else None
        head = store.get_many([g]).get(g) if g is not None else None
        if head is None or head.kind != "group":
            out.append(f"dore: #{a} is not a list")
            continue
        items = store.group_items(g)
        out.append(f"#{g} {head.content} ({len(items)} entries):")
        out += [f"- {m.content}" for m in items]
    return "\n".join(out) or "usage: dore-hook recall <id>"


def open_store(cfg: Config) -> MemoryStore:
    from dore.memory.embed import FastEmbedder
    store = MemoryStore(cfg.db_path, cfg.index_path,
                        FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed")))
    # Notes saved before topic keys existed get one, a batch per start (once each; ~2 ms a note).
    if old := store.missing_keys():
        store.set_keys([(i, topic_key(c)) for i, c in old])
    return store


def remark_instructions(store: MemoryStore, limit: int | None = None) -> int:
    """Once per `RULE_FORM` version, notes saved before are re-marked by their form, `limit` at a time, oldest first
    (while idle: `consolidate`; never on the prompt path, 3,000 notes took 4.2 s). Until then an old note is simply
    not a session-start rule. Returns how many were marked (0 = done)."""
    if store.meta("rule_form") == RULE_FORM:
        return 0
    upto = int(store.meta("rule_form_upto") or 0)
    ids = [r[0] for r in store.db.execute(
        "SELECT id FROM memories WHERE archived=0 AND replaced_by IS NULL AND id > ? ORDER BY id" +
        (" LIMIT ?" if limit else ""), (upto, limit) if limit else (upto,))]
    if not ids:
        store.meta("rule_form", RULE_FORM)
        store.meta("rule_form_upto", "0")
        return 0
    mark_instructions(store, ids)
    store.meta("rule_form_upto", str(ids[-1]))
    return len(ids)


def run_event(store: MemoryStore, cfg: Config, event: str, data: dict) -> str:
    """Handle one hook event; returns the text to print ("" = add nothing)."""
    if event == "recall":
        return recall_text(store, data.get("ids") or [])
    project = resolve_project(store, data.get("cwd"), data.get("project_dir"))
    if event == "prompt":
        state = _State(cfg.data_dir, str(data.get("session_id", "")))
        tp = data.get("transcript_path")
        log = Path(tp) if tp else None
        events = _log_events(log, LOG_BYTES)  # read once for both
        reply, actions = last_turn(events)
        text = on_prompt(store, str(data.get("prompt", "")), project, state, echo=assistant_text(events),
                         reply=reply, actions=actions, learn=getattr(cfg, "learner", "rules"))
        state.save()
        return text
    if event == "end" and data.get("transcript_path"):
        state = _State(cfg.data_dir, str(data.get("session_id", "")))
        save_session(store, Path(data["transcript_path"]), project,
                     set(state.d.get("learned", [])) | set(state.d.get("handled", [])), set(state.d.get("saved", [])),
                     str(data.get("session_id", "")), learn=getattr(cfg, "learner", "rules"))
        consolidate(store, learn=getattr(cfg, "learner", "rules"), wait=True)
        update.check(cfg.data_dir)  # at most once a day, 3 s timeout, update runs detached; SessionEnd allows 60 s
    return ""


def _known(store: MemoryStore, fact: str) -> bool:
    """The same words are already a note, in any state: a note the user archived, marked wrong or saw
    replaced is never brought back from raw memory."""
    return store.db.execute("SELECT 1 FROM memories WHERE lower(trim(content, ' .!')) = lower(trim(?, ' .!')) "
                            "LIMIT 1", (fact,)).fetchone() is not None


def consolidate(store: MemoryStore, limit: int = 64, learn: str = "rules", wait: bool = False) -> dict:
    """Work on raw memory while the user is away (warm helper idle, SessionEnd), like sleep: give new
    episodes a vector so a later question can recall them, and judge again those not judged with
    today's learning rules, so a fixed rule also learns what was said before. A fact learned this way
    keeps the date it was said (an older date never replaces a newer note). Small batches: call again
    until it returns zeros. No Claude tokens. With the Haiku learner: at SessionEnd (`wait`) the batches due
    (`integrations.learner`), never while idle; the word rules don't run."""
    if learn == "haiku":
        from dore.integrations import learner
        for _ in range(learner.END_BATCHES if wait else 0):
            if learner.run_once(store, ended=True) is None:
                break
        return {}
    embedded = episodes.embed_pending(store, limit)
    remarked = remark_instructions(store, limit)
    learned = 0
    todo = episodes.to_judge(store, RULES_VERSION, limit)
    for eid, content, project, created in todo:
        facts = [f for f in message_facts(content, similar_fn(store)) if not _known(store, f)]
        ids = save_facts(store, facts, project, created=created) if facts else []
        episodes.mark_judged(store, eid, RULES_VERSION, scope_for(content, project), tells(content),
                             ids[0] if ids else None)
        learned += bool(ids)
    store.save()
    return {"embedded": embedded, "judged": len(todo), "learned": learned, "remarked": remarked}


def main(argv: list[str] | None = None):
    """Run one event in this process (slow: loads the embedder). `dore-hook` normally goes
    through `hookclient`, which uses the warm background helper instead."""
    argv = sys.argv[1:] if argv is None else argv
    event = argv[0] if argv else ""
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        data = {}
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        data.setdefault("project_dir", os.environ["CLAUDE_PROJECT_DIR"])
    run_inline(event, data)


def run_inline(event: str, data: dict):
    cfg = Config()
    store = open_store(cfg)
    try:
        text = run_event(store, cfg, event, data)
        if text:
            print(text)
    finally:
        store.close()


if __name__ == "__main__":
    main()
