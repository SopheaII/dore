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
                                   message_facts, scope_for, user_facts)
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


def _line(mid: int, content: str, label: str = "", created: float | None = None) -> str:
    text = content if len(content) <= MAX_CHARS else content[:MAX_CHARS] + "…"
    date = f" ({time.strftime('%Y-%m-%d', time.localtime(created))})" if created else ""
    return f"- #{mid}{date}{label} {text}"


def prompt_context(store: MemoryStore, prompt: str, project: str, state: _State) -> str:
    shown = set(state.d["shown"])
    cands: list[tuple[int, str, bool]] = []  # (id, line, is_note): rules first, then notes
    if not state.d["rules_done"]:
        state.d["rules_done"] = True
        rows = store.db.execute(
            f"SELECT id, content, project, created FROM memories WHERE {SEARCHABLE_SQL} AND trust='verified' "
            "AND project IN (?, '') ORDER BY created DESC LIMIT 200", (project,)).fetchall()
        rules = [(i, c, p, t) for i, c, p, t in rows
                 if RULE.search(c) and (not PERSONAL.search(c) or PERSONAL_RULE.search(c))][:MAX_RULES]
        for i, c, p, t in rules:
            cands.append((i, _line(i, c, created=t), False))
            shown.add(i)
    hits = store.search(prompt[:2000], k=MAX_NOTES + len(shown), min_similarity=STRONG,
                        project=project or None, touch=False)
    hits = [m for m in hits if m.trust != "wrong" and not ABOUT_ASSISTANT.match(m.content)]
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
                 if m.id not in shown and m.project not in (project, "")][:1]
    for m in notes:
        label = f" (from project {m.project})" if m.project not in (project, "") else ""
        cands.append((m.id, _line(m.id, m.content, label, m.created), True))
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


def save_facts(store: MemoryStore, facts: list[str], project: str) -> list[int]:
    """Store user statements (verified); each replaces older notes it updates."""
    ids = []
    for scope in dict.fromkeys(scope_for(f, project) for f in facts):
        group = [f for f in facts if scope_for(f, project) == scope]
        ids += store.add_many(group, kind="statement", source="user", trust="verified", project=scope,
                              supersede=True)
    return ids


def save_session(store: MemoryStore, transcript: Path, project: str,
                 learned: set[str] | None = None) -> list[int]:
    """Session end: store statements from messages the prompt hook didn't already learn
    (`learned` = their message_key), e.g. when the hook timed out."""
    learned = learned or set()
    echo = assistant_text(transcript, max_bytes=4_000_000)
    facts = [f for msg in _user_messages(transcript) if message_key(msg) not in learned
             for f in not_echoed(message_facts(msg), echo)]
    ids = save_facts(store, facts, project)
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
    new_ids = save_facts(store, not_echoed(message_facts(prompt), echo), project)
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
