"""Claude Code hooks: give Claude only what it needs, and learn at zero Claude tokens.

    dore-hook prompt   # UserPromptSubmit: add relevant notes to the prompt (or nothing)
    dore-hook end      # SessionEnd: save the user's own statements from the session log

Why hooks instead of tool calls: every tool call is one more round trip that resends the
whole conversation (~15-25k tokens). The prompt hook runs locally before Claude sees the
prompt, and prints nothing when nothing is worth adding.

What the prompt hook adds (measured thresholds, bge-small; see reports/token-design.md):
- rules of this project and general rules ("keep code Python 3.9 compatible", "max discount
  50%"): once per session, at the first prompt, because they apply to all work;
- other notes only on a strong match (similarity >= 0.65 and within 0.05 of the best match, or an exact
  ID such as SRV-4471),
  each note at most once per session. Unrelated prompts scored up to 0.62.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

from dore.config import Config
from dore.learn.statements import (CORRECTION_LEAD, IMPLICIT_FEEDBACK, PERSONAL, QUESTION_START, REASK_SIMILARITY,
                                   REQ_MAX_CHARS, message_facts, requirement_text, scope_for, user_facts)
from dore.memory import SEARCHABLE_SQL, MemoryStore, same_frame

STRONG = 0.65          # prompt-to-note similarity needed to add a note
# Only notes close to the best match: on a broad prompt many loosely related notes all score
# 0.65-0.73 ("your name is dore" matched every prompt saying "dore"). Measured on 18 labelled
# prompts (2026-11-25): same useful notes found (7/8), wrong extra notes 9 -> 1.
GAP = 0.05
# Notes about the local dore assistant itself ("your name is dore") are for dore's own chat; shown to
# Claude they matched every prompt saying "dore" and name the wrong assistant.
ABOUT_ASSISTANT = re.compile(r"^\s*(your\b|you are\b|you'?re\b)", re.I)
SAME_THING = 0.72  # note-to-note: same thing (updates 0.73-0.82; but different facts reach 0.82 too, so this only adds, never hides)
MAX_RULES = 6
MAX_NOTES = 3
MAX_CHARS = 160        # per note shown
MAX_TOTAL_CHARS = 600  # everything one prompt adds (~150 tokens; AGENTS.md / hook-cost skill)
CONFLICT_SIMILARITY = 0.7  # same rule as Agent.conflict_similarity
# Constraints / decisions that apply to all work in a project.
RULE = re.compile(r"\b(must|always|never|don'?t|do not|should|shouldn'?t|keep\b.*\bcompatible|compatible with|"
                  r"only use|required?|max(imum)?|min(imum)?|at most|at least|cap(ped)?|limit|policy|"
                  r"decided|rule|prefer|convention|standard)\b", re.I)
# A personal note ("I don't want to install apps...") is not a rule for the work just because it
# says "don't": it was shown as a project rule at every session start (2026-11-25). Personal
# notes count as rules only with these stronger words.
PERSONAL_RULE = re.compile(r"\b(always|never|prefer|must|convention|standard|policy)\b", re.I)
def _project(cwd: str | None) -> str:
    d = Path(cwd or ".").resolve()
    return "" if d in (Path.home().resolve(), Path("/")) else d.name


class _State:
    """Per-session memory of what was already shown (so nothing is sent twice)."""

    def __init__(self, data_dir: Path, session_id: str):
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


def prompt_context(store: MemoryStore, prompt: str, project: str, state: _State) -> str:
    shown = set(state.d["shown"])
    cands: list[tuple[int, str, bool]] = []  # (id, line, is_note): rules first, then notes
    if not state.d["rules_done"]:
        state.d["rules_done"] = True
        rows = store.db.execute(
            f"SELECT id, content, project, created FROM memories WHERE {SEARCHABLE_SQL} AND trust='verified' "
            "AND project IN (?, '') ORDER BY created DESC LIMIT 200", (project,)).fetchall()
        # Not the rule the user just typed (already in `shown`): Claude has their message.
        rules = [(i, c, p, t) for i, c, p, t in rows if i not in shown
                 and RULE.search(c) and (not PERSONAL.search(c) or PERSONAL_RULE.search(c))][:MAX_RULES]
        for i, c, p, t in rules:
            cands.append((i, _line(i, c, created=t), False))
            shown.add(i)
    hits = store.search(prompt[:2000], k=MAX_NOTES + len(shown), min_similarity=STRONG,
                        project=project or None, touch=False)
    hits = [m for m in hits if _showable(m)]
    if hits:  # keep notes near the best match; a note below STRONG got in by an exact ID/keywords
        top = max(m.focus for m in hits)  # hub-corrected (`MemoryStore.search`); STRONG stays on raw similarity
        near = [m for m in hits if m.focus >= top - GAP or m.similarity < STRONG]
        # Newer wins: a newer note about the same thing as a kept one stays, even below the gap
        # ("My editor is Helix" after "i use neovim as my editor" scored lower than the old note).
        newer = [m for m in hits if m not in near and m.similarity >= STRONG and m.focus >= top - 2 * GAP and any(
            m.created > k.created and float(store._vector(m.id) @ store._vector(k.id)) >= SAME_THING for k in near)]
        hits = sorted(near + newer, key=lambda m: -m.created if m in newer else 0)  # newer first
    notes = [m for m in hits if m.id not in shown][:MAX_NOTES]
    if not notes and project:  # nothing here: a very strong match from another project may help
        notes = [m for m in store.search(prompt[:2000], k=2, min_similarity=0.75, touch=False)
                 if m.id not in shown and m.project not in (project, "") and _showable(m)][:1]
    for m in notes:
        label = f" (from project {m.project})" if m.project not in (project, "") else ""
        if m.kind == "requirement":
            label += " (your earlier request)" if m.trust != "verified" else " (your repeated request)"
        cands.append((m.id, _line(m.id, m.content, label, m.created,
                                  limit=REQ_MAX_CHARS + 1 if m.kind == "requirement" else MAX_CHARS), True))
    # Token cap: add lines while they fit; a line left out may still be shown on a later prompt.
    lines, used, last_shown = [], 0, []
    for mid, line, is_note in cands:
        if used + len(line) > MAX_TOTAL_CHARS:
            shown.discard(mid)
            continue
        lines.append(line)
        used += len(line)
        shown.add(mid)
        if is_note:
            last_shown.append(mid)
    state.d["shown"] = sorted(shown)
    state.d["last_shown"] = last_shown  # judged by the user's next prompt (react)
    if not lines:
        return ""
    return "dore memory (use if relevant; trust user code/instructions over it):\n" + "\n".join(lines)


def _user_messages(transcript: Path) -> list[str]:
    """The user's own typed messages from a Claude Code session log (JSONL)."""
    out = []
    try:
        lines = transcript.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") != "user" or ev.get("isMeta") or ev.get("isSidechain"):
            continue
        content = (ev.get("message") or {}).get("content")
        if isinstance(content, list):  # tool results are lists of blocks; typed text may be too
            content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        if isinstance(content, str) and content.strip() and not content.lstrip().startswith("<"):
            out.append(content)
    return out


def assistant_text(transcript: Path | None, max_bytes: int = 400_000) -> str:
    """Claude's recent replies in this session (the end of the session log), to recognise the
    user pasting them back. "" when there is no log."""
    if not transcript:
        return ""
    try:
        with open(transcript, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - max_bytes))
            lines = f.read().decode("utf-8", errors="replace").splitlines()[1:]
    except OSError:
        return ""
    out = []
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") != "assistant":
            continue
        for b in (ev.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "text":
                out.append(b.get("text", ""))
    return "\n".join(out)


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


PROMOTE_SIMILARITY = 0.85  # the same habit said in another project


def _promoted(store: MemoryStore, fact: str, project: str) -> bool:
    """A habit or preference with no concrete value ("Don't reformat existing code") said again in a
    second project becomes general: it is about the user, not one project. Facts with a name or
    number ("The database is PostgreSQL") never move: they differ per project."""
    from dore.learn.grammar import nlp, _detail
    parser = nlp()
    if not project or parser is None or _detail(parser(fact)):  # any name, incl. "vitest"
        return False
    # Same content words, not only close in meaning: "We merge into develop" vs "... into trunk" are
    # close (0.9) but differ in the value, which may be an ordinary word (stream test, 2026-11-25).
    words = _content_words(fact)
    return any(m.project not in ("", project) and m.source == "user" and m.trust == "verified"
               and _content_words(m.content) == words
               for m in store.search(fact, k=3, min_similarity=PROMOTE_SIMILARITY, touch=False, keyword=False))


def _content_words(text: str) -> frozenset:
    from dore.memory.rules import FRAME_FILLER, STOPWORDS
    return frozenset(w for w in re.findall(r"[a-z0-9]+", text.lower())
                     if w not in STOPWORDS and w not in FRAME_FILLER and w not in ("please", "pls", "plz", "t", "don"))


REQ_SHOW = 1.01  # a requirement said only once is kept but not shown (0.75 doubled tokens: 8.3 -> 17.6 per prompt)
REQ_SAME = 0.85  # the same requirement said again (0.75 merged different requests about one screen)


RULE_SOURCE = "user-rule"  # the negated verb phrase of a long request ("do not touch old code")
RULE_SAME = 0.85  # real use: true repeats 0.86-0.93, the next pair (a different rule) 0.77


def save_rule_cores(store: MemoryStore, text: str, project: str) -> list[int]:
    """Keep each standing rule inside a long request ("..., and do not touch old code") as a short
    hidden note. Said again in other words (in this project, or in another one), it is verified and
    shown: the user repeating a rule is the signal that it lasts. The gist is kept as well."""
    from dore.learn.grammar import rule_cores
    ids = []
    for core in rule_cores(text):
        same = [m for m in store.search(core, k=3, min_similarity=RULE_SAME, touch=False, keyword=False)
                if m.source == RULE_SOURCE and m.kind == "requirement"]
        here = [m for m in same if m.project == project]
        if here:
            m = here[0]
            store.db.execute("UPDATE memories SET times_seen=times_seen+1, last_seen=? WHERE id=?",
                             (time.time(), m.id))
            if m.trust != "verified":
                store.set_trust(m.id, "verified")
            store.db.commit()
            ids.append(m.id)
        else:  # said before only in another project: lasting for this user, kept in this project
            ids.append(store.add(core, kind="requirement", source=RULE_SOURCE, project=project,
                                 trust="verified" if same else "unverified"))
    return ids


def save_requirement(store: MemoryStore, text: str, project: str) -> int | None:
    """Keep the gist of a long instruction as a low-trust project requirement. Said again (close in
    meaning) in a later message, the existing note is strengthened (seen again, verified: the user
    repeated it) instead of stored twice. Returns the note id."""
    if not text:
        return None
    same = [m for m in store.search(text, k=3, min_similarity=REQ_SAME, project=project or None, touch=False,
                                    keyword=False) if m.kind == "requirement" and m.project == project
            and m.source != RULE_SOURCE]
    if same:
        m = same[0]
        store.db.execute("UPDATE memories SET times_seen=times_seen+1, last_seen=? WHERE id=?", (time.time(), m.id))
        if m.trust != "verified":
            store.set_trust(m.id, "verified")
        store.db.commit()
        return m.id
    return store.add(text, kind="requirement", source="user", trust="unverified", project=project)


def save_facts(store: MemoryStore, facts: list[str], project: str) -> list[int]:
    """Store user statements (verified); each replaces older notes it updates."""
    ids = []
    scopes = {f: ("" if _promoted(store, f, project) else scope_for(f, project)) for f in facts}
    for scope in dict.fromkeys(scopes.values()):
        group = [f for f in facts if scopes[f] == scope]
        ids += store.add_many(group, kind="statement", source="user", trust="verified", project=scope,
                              supersede=True)
    return ids


def learn_message(store: MemoryStore, msg: str, project: str, echo: str = "") -> list[int]:
    """Everything one user message teaches, in one place (prompt hook, SessionEnd, opencode bridge):
    short facts (not ones Claude wrote and the user pasted back); else the gist of a long instruction
    as a hidden requirement."""
    ids = save_facts(store, not_echoed(message_facts(msg), echo), project)
    req = not_echoed([requirement_text(msg)], echo)
    if req and req[0]:
        save_rule_cores(store, req[0], project)  # rules inside any long message, facts or not
        if not ids:
            rid = save_requirement(store, req[0], project)
            ids = [rid] if rid else []
    return ids


def save_session(store: MemoryStore, transcript: Path, project: str,
                 learned: set[str] | None = None) -> list[int]:
    """Session end: store statements from messages the prompt hook didn't already learn
    (`learned` = their message_key), e.g. when the hook timed out."""
    learned = learned or set()
    echo = assistant_text(transcript, max_bytes=4_000_000)
    ids = [i for msg in _user_messages(transcript) if message_key(msg) not in learned
           for i in learn_message(store, msg, project, echo)]
    store.save(force=True)
    return ids


def _is_question(text: str) -> bool:
    t = text.strip()
    return t.endswith("?") or bool(QUESTION_START.match(t))


def react(store: MemoryStore, prompt: str, state: _State) -> str:
    """Learn from how the user's new prompt reacts to the notes shown with the previous one
    (same rules as dore's own chat, Agent._react):
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


def on_prompt(store: MemoryStore, prompt: str, project: str, state: _State, echo: str = "") -> str:
    """Everything the prompt hook does, in order: judge the last notes, learn the user's new
    statements right away (so a correction counts in this session, not only at its end), then
    pick notes for this prompt. Returns the text to add ("" = nothing, 0 tokens)."""
    state.d["last_signal"] = react(store, prompt, state)
    new_ids = learn_message(store, prompt, project, echo)
    if new_ids:
        state.d.setdefault("learned", []).append(message_key(prompt))
        # Never echo back what the user just said.
        state.d["shown"] = sorted(set(state.d["shown"]) | set(new_ids))
    text = prompt_context(store, prompt, project, state)
    state.d["last_prompt"] = prompt[:2000]
    store.save()
    return text


def open_store(cfg: Config) -> MemoryStore:
    from dore.memory.embed import FastEmbedder
    return MemoryStore(cfg.db_path, cfg.index_path,
                       FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed")))


def run_event(store: MemoryStore, cfg: Config, event: str, data: dict) -> str:
    """Handle one hook event; returns the text to print ("" = add nothing)."""
    project = _project(data.get("cwd"))
    if event == "prompt":
        state = _State(cfg.data_dir, str(data.get("session_id", "")))
        tp = data.get("transcript_path")
        text = on_prompt(store, str(data.get("prompt", "")), project, state, echo=assistant_text(Path(tp) if tp else None))
        state.save()
        return text
    if event == "end" and data.get("transcript_path"):
        state = _State(cfg.data_dir, str(data.get("session_id", "")))
        save_session(store, Path(data["transcript_path"]), project, set(state.d.get("learned", [])))
    return ""


def main(argv: list[str] | None = None):
    """Run one event in this process (slow: loads the embedder). `dore-hook` normally goes
    through `hookclient`, which uses the warm background helper instead."""
    argv = sys.argv[1:] if argv is None else argv
    event = argv[0] if argv else ""
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        data = {}
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
