"""The README example, run for real: four Claude Code sessions in two projects, through the prompt hook.

    python -m dore.eval.demo        # ~5 s, real embedder and parser, no LLM, throw-away store

Messages go through `hooks.on_prompt` exactly as in Claude Code. For each message it prints what was saved
(note ids, scope, which note it replaced) and what the hook adds to the prompt ("" = nothing, 0 tokens).
The facts are made up.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

SESSIONS = [
    ("shop", "Monday", [
        "My name is Dara. My editor is Neovim.",
        "We deploy the shop API to Render. The database is Postgres 16.",
        "Please don't reformat existing code.",
        "fix the login bug please",
        "can you check why the test fails?",
        "hmm that's not right, the test still fails",
    ]),
    ("shop", "Thursday", [
        "I switched my editor to Helix.",
        "We moved off Render, the shop API deploys to Fly.io now.",
    ]),
    ("blog", "next week", [
        "Which editor do I use?",
        "Where does the shop API deploy?",
        "What is my name?",
        "add a dark mode toggle to the header",
    ]),
    ("shop", "next week", [
        "Where do we deploy the API?",
        "Which database version do we run?",
    ]),
]


def main() -> None:
    from dore.config import Config
    from dore.integrations.hooks import _State, on_prompt
    from dore.memory import MemoryStore
    from dore.memory.embed import FastEmbedder

    cfg = Config()
    d = Path(tempfile.mkdtemp(prefix="dore-demo-"))
    try:
        store = MemoryStore(d / "m.db", d / "m.faiss",
                            FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed")))
        times, added, prompts = [], 0, 0
        for n, (project, day, messages) in enumerate(SESSIONS, 1):
            print(f"\n── Session {n} · {day} · project \"{project}\" " + "─" * 30)
            state = _State(d, f"s{n}")
            for msg in messages:
                before = store.db.execute("SELECT COALESCE(MAX(id), 0) FROM memories").fetchone()[0]
                t = time.perf_counter()
                out = on_prompt(store, msg, project, state)
                times.append(time.perf_counter() - t)
                prompts += 1
                added += len(out)
                print(f"you>  {msg}")
                for mid, content, proj in store.db.execute(
                        "SELECT id, content, project FROM memories WHERE id > ? ORDER BY id", (before,)):
                    old = store.db.execute("SELECT id, content FROM memories WHERE replaced_by = ?", (mid,)).fetchone()
                    scope = "every project" if not proj else f"project {proj} only"
                    print(f"      saved #{mid} ({scope}){f', replaces #{old[0]} {old[1]!r}' if old else ''}")
                body = out.split("\n", 1)[1] if out else ""
                print("      dore adds nothing (0 tokens)" if not out else
                      "      dore adds:\n" + "\n".join("        " + line for line in body.splitlines()))
        times.sort()
        rows = store.db.execute("SELECT COUNT(*), SUM(replaced_by IS NOT NULL) FROM memories").fetchone()
        print(f"\nNotes: {rows[0]} saved, {rows[1]} replaced (kept in SQLite, out of search). "
              f"Added ~{added / 4 / prompts:.0f} tokens per prompt (characters / 4). "
              f"Hook median {times[len(times) // 2] * 1000:.0f} ms (one process, no warm helper).")
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    main()
