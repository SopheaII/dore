"""Give past sessions the same second chance: keep what the user typed in old Claude Code sessions as raw
memory, then let today's rules judge it (`hooks.consolidate`).

    python -m dore.integrations.backfill            # dry run: counts only, writes nothing
    python -m dore.integrations.backfill --apply    # keep the sentences, then consolidate

Reads the user's own typed messages from `~/.claude/projects/*/*.jsonl` (not tool output, not pastes; a
sentence Claude wrote and the user pasted back is skipped). Every sentence becomes an episode dated when it
was said; consolidation learns the ones today's rules call facts, dated then too (an older date never
replaces a newer note). A fact whose words are already a note in any state (kept, archived, marked wrong,
replaced) is not learned again, so nothing the user archived comes back. Sentences already in raw memory
for that session (the prompt hook keeps new ones itself) are skipped, so running it twice changes nothing,
and a session the hook joined halfway still gets its earlier sentences. Nothing is deleted. Claude Code
removes session logs after 30 days by default, so older sessions are not there to read.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from dore.integrations.hooks import _known, _project, consolidate, not_echoed
from dore.learn.statements import episode_sentences, message_facts
from dore.memory import episodes

LOGS = Path.home() / ".claude" / "projects"
# Test runs (`claude -p` in a scratch folder, with a throw-away dore data folder) are not the user's life.
TEMP_ROOTS = {Path(p).resolve() for p in (tempfile.gettempdir(), "/tmp", "/private/tmp", "/var/folders",
                                          "/private/var/folders")}


def _real_folder(cwd: str) -> bool:
    d = Path(cwd).resolve()
    return d.is_dir() and not any(d == t or t in d.parents for t in TEMP_ROOTS)


def _when(ts: str) -> float | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def sessions(root: Path = LOGS):
    """(project, session id, [(time, typed message, Claude's text before it)]) per session log. Only what
    Claude wrote *before* a message is an echo: Claude quoting the user later is not."""
    for f in sorted(root.glob("*/*.jsonl")):
        typed, said, cwd = [], [], None
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("isSidechain") or ev.get("isMeta"):
                continue
            cwd = cwd or ev.get("cwd")
            content = (ev.get("message") or {}).get("content")
            if ev.get("type") == "assistant":
                said += [b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"]
            elif ev.get("type") == "user":
                if isinstance(content, list):
                    content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
                if isinstance(content, str) and content.strip() and not content.lstrip().startswith("<"):
                    typed.append((_when(ev.get("timestamp", "")), content, "\n".join(said)))
        if typed and cwd and _real_folder(cwd):
            yield _project(cwd), f.stem, typed


def backfill(store, apply: bool = False, root: Path = LOGS) -> dict:
    found = {"sessions": 0, "sentences": 0, "new_facts": 0, "facts": []}
    for project, sid, typed in sessions(root):
        # Per sentence, not per session: a session the prompt hook joined halfway still has its first half.
        kept = {c for (c,) in store.db.execute("SELECT content FROM episodes WHERE session=?", (sid,))}
        new_here = False
        for when, msg, echo in typed:
            facts = not_echoed(message_facts(msg), echo)
            # Facts go in as raw memory too: consolidation learns them with today's rules (or skips known ones).
            sents = [x for x in facts + not_echoed(episode_sentences(msg, facts), echo) if x.strip() not in kept]
            facts = [f for f in facts if f.strip() not in kept]
            new_here = new_here or bool(sents)
            found["sentences"] += len(sents)
            new = [f for f in facts if not _known(store, f) and f not in found["facts"]]
            found["new_facts"] += len(new)
            found["facts"] += new
            if apply and sents:
                episodes.add(store, sents, project, sid, judged="", created=when)
        found["sessions"] += new_here
    if apply:
        store.save(force=True)
        while any(consolidate(store, 256).values()):
            pass
        store.save(force=True)
    return found


def main(argv: list[str] | None = None):
    argv = sys.argv[1:] if argv is None else argv
    from dore.config import Config
    from dore.integrations.hooks import open_store
    store = open_store(Config())
    apply = "--apply" in argv
    try:
        r = backfill(store, apply)
        print(f"{r['sessions']} session logs, {r['sentences']} typed sentences, "
              f"{r['new_facts']} facts today's rules learn that are not notes yet"
              + ("" if apply else " (dry run: read them, then run with --apply to keep them):"))
        if not apply:
            for f in r["facts"]:
                print("  -", f[:160])
        if apply:
            print(episodes.stats(store))
    finally:
        store.close()


if __name__ == "__main__":
    main()
