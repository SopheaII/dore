"""Claude Code hooks: give Claude only what it needs, and learn at zero Claude tokens.

    dore-hook prompt   # UserPromptSubmit: add relevant notes to the prompt (or nothing)
    dore-hook end      # SessionEnd: save the user's own statements from the session log

Why hooks instead of tool calls: every tool call is one more round trip that resends the
whole conversation (~15-25k tokens). The prompt hook runs locally before Claude sees the
prompt, and prints nothing when nothing is worth adding.

What the prompt hook adds (measured thresholds, bge-small; see reports/token-design.md):
- rules of this project and general rules ("keep code Python 3.9 compatible", "max discount
  50%"): once per session, at the first prompt, because they apply to all work;
- other notes only on a strong match (similarity >= 0.65, or an exact ID such as SRV-4471),
  each note at most once per session. Unrelated prompts scored up to 0.62.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

from .agent import (CORRECTION_LEAD, IMPLICIT_FEEDBACK, MEMORY_LEAD_IN, NOT_A_FACT, PERSONAL, QUESTION_START,
                    REASK_SIMILARITY, SENTENCE_SPLIT, SMALL_TALK)
from .config import Config
from .memory import SEARCHABLE_SQL, MemoryStore, same_frame

STRONG = 0.65          # prompt-to-note similarity needed to add a note
MAX_RULES = 6
MAX_NOTES = 3
MAX_CHARS = 160        # per note shown
MAX_TOTAL_CHARS = 600  # everything one prompt adds (~150 tokens; PLAN.md token rules)
CONFLICT_SIMILARITY = 0.7  # same rule as Agent.conflict_similarity
# A longer message is a paste (an article, a log), not statements about the user's work:
# 11 sentences of a pasted report were stored as verified user facts (real DB, 2026-11-25).
MAX_MSG_CHARS = 3000
MAX_MSG_FACTS = 20

# Constraints / decisions that apply to all work in a project.
RULE = re.compile(r"\b(must|always|never|don'?t|do not|should|shouldn'?t|keep\b.*\bcompatible|compatible with|"
                  r"only use|required?|max(imum)?|min(imum)?|at most|at least|cap(ped)?|limit|policy|"
                  r"decided|rule|prefer|convention|standard)\b", re.I)
# A personal note ("I don't want to install apps...") is not a rule for the work just because it
# says "don't": it was shown as a project rule at every session start (2026-11-25). Personal
# notes count as rules only with these stronger words.
PERSONAL_RULE = re.compile(r"\b(always|never|prefer|must|convention|standard|policy)\b", re.I)
# Facts about the organisation rather than one project ("our production server ...").
ORG = re.compile(r"\b(our|the) (production|prod|staging|server|servers|team|company|infra|infrastructure|"
                 r"ci|cluster|database server)\b|\ball (our )?projects\b|\bevery project\b|\bwe (always|never)\b",
                 re.I)
# Coding instructions are requests, not facts ("add tests", "fix the bug ...").
IMPERATIVE = re.compile(
    r"^(add|create|make|fix|write|implement|update|remove|delete|rename|refactor|change|move|run|test|check|"
    r"build|install|deploy|start|stop|set|put|show|explain|give|list|try|help|let'?s|please|can|could|would|"
    r"look|find|search|open|read|replace|convert|generate|split|merge|clean|format|debug|print|return|call|"
    r"push|commit|review|summari[sz]e|translate|describe|compare|continue|go|do|see|tell|reply|answer|respond|say|output|answer)\b", re.I)
# "I need a helper that ..." is a request; "It will run on ..." only makes sense in its conversation.
WANT = re.compile(r"^(i|we)\s*('d| would| will)?\s*(need|want|like|wanna|have to|must have)\b", re.I)
VAGUE = re.compile(r"^(it|this|that|these|those|they|he|she|which)\b", re.I)
FILLER = re.compile(r"^(also|and|so|but|then|ok(ay)?|hey|hi|well|btw)\b[,:]?\s*", re.I)


def user_facts(text: str) -> list[str]:
    """Durable statements in a coding prompt: no requests, questions, small talk or code."""
    out = []
    for sent in SENTENCE_SPLIT.split(text.strip()):
        sent = sent.strip()
        while FILLER.match(sent):
            sent = FILLER.sub("", sent, count=1).strip()
        fix = CORRECTION_LEAD.match(sent)  # "No, the API uses port 9090" -> "The API uses port 9090"
        if fix and sent[fix.end():].strip():
            sent = sent[fix.end():].strip()
        lead = MEMORY_LEAD_IN.match(sent)
        if lead:
            sent = sent[lead.end():].rstrip("?").strip()
        elif (sent.endswith("?") or QUESTION_START.match(sent) or SMALL_TALK.match(sent)
              or IMPERATIVE.match(sent) or WANT.match(sent) or VAGUE.match(sent)):
            continue
        if NOT_A_FACT.match(sent):
            continue
        if not 4 <= len(sent.split()) <= 60 or "```" in sent or sent.count("(") > 2:
            continue
        out.append(sent[:1].upper() + sent[1:])
    return out


def scope_for(text: str, project: str) -> str:
    return "" if PERSONAL.search(text) or ORG.search(text) else project


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
    notes = [m for m in hits if m.id not in shown and m.trust != "wrong"][:MAX_NOTES]
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


def message_key(text: str) -> str:
    """Short fingerprint of a message, to skip at session end what a prompt already taught."""
    return hashlib.sha1(" ".join(text.split()).encode()).hexdigest()[:16]


def message_facts(msg: str) -> list[str]:
    """Facts in one user message; none for a paste (an article, a log)."""
    found = user_facts(msg)
    return found if len(msg) <= MAX_MSG_CHARS and len(found) <= MAX_MSG_FACTS else []


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
    facts = [f for msg in _user_messages(transcript) if message_key(msg) not in learned
             for f in message_facts(msg)]
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
            wrong = [m.id for fix in fixes for m in store.similar(fix, shown)
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


def on_prompt(store: MemoryStore, prompt: str, project: str, state: _State) -> str:
    """Everything the prompt hook does, in order: judge the last notes, learn the user's new
    statements right away (so a correction counts in this session, not only at its end), then
    pick notes for this prompt. Returns the text to add ("" = nothing, 0 tokens)."""
    state.d["last_signal"] = react(store, prompt, state)
    new_ids = save_facts(store, message_facts(prompt), project)
    if new_ids:
        state.d.setdefault("learned", []).append(message_key(prompt))
        # Never echo back what the user just said.
        state.d["shown"] = sorted(set(state.d["shown"]) | set(new_ids))
    text = prompt_context(store, prompt, project, state)
    state.d["last_prompt"] = prompt[:2000]
    store.save()
    return text


def open_store(cfg: Config) -> MemoryStore:
    from .embed import FastEmbedder
    return MemoryStore(cfg.db_path, cfg.index_path,
                       FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed")))


def run_event(store: MemoryStore, cfg: Config, event: str, data: dict) -> str:
    """Handle one hook event; returns the text to print ("" = add nothing)."""
    project = _project(data.get("cwd"))
    if event == "prompt":
        state = _State(cfg.data_dir, str(data.get("session_id", "")))
        text = on_prompt(store, str(data.get("prompt", "")), project, state)
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
    if event == "prompt" and not cfg.db_path.exists():
        return  # nothing remembered yet: add nothing, don't even load the embedder
    store = open_store(cfg)
    try:
        text = run_event(store, cfg, event, data)
        if text:
            print(text)
    finally:
        store.close()


if __name__ == "__main__":
    main()
