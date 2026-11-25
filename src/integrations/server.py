"""dore memory for Claude Code and other MCP clients.

Two ways to run it; both share the same memory.db, so every session sees every other
session's memories:

    dore-server --stdio     # started by Claude Code itself (plugin or `claude mcp add`),
                            # one small process per session, nothing to keep running
    dore-server             # one shared HTTP server: http://127.0.0.1:8765/mcp

Tools are few and their descriptions short, because every client pays for them in
tokens on every request. Trust rules (CLAUDE.md) apply to every client: what an agent
writes in its own words is `unverified`; only facts the user stated are `verified`.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import anyio
from mcp.server.mcpserver import MCPServer

from dore.config import Config
from dore.learn.statements import ORG, PERSONAL
from dore.memory.ingest import ingest_text
from dore.memory import SEARCHABLE_SQL, Memory, MemoryStore

# Sent to every client when it connects (Claude Code puts it in its system prompt), so users
# don't need their own rules. Kept short: it is paid for on every request.
INSTRUCTIONS = (
    "Long-term memory. Relevant notes are added to prompts automatically and the user's own statements are "
    "saved automatically. Call recall only for older context you still need. At the end of a task, save your "
    "own durable findings (bug causes, decisions, settings) in ONE remember call; never code or routine edits.")

MAX_SHOWN = 300      # characters of a memory shown by recall (full text: recall("#<id>"))
LONG_TEXT = 1000     # longer texts given to remember are stored as document chunks


def format_hit(m: Memory) -> str:
    date = datetime.fromtimestamp(m.created).strftime("%Y-%m-%d")
    text = m.content if len(m.content) <= MAX_SHOWN else m.content[:MAX_SHOWN] + f"… (full: #{m.id})"
    scope = f", {m.project}" if m.project else ""
    return f"#{m.id} [{m.trust}, {m.source}{scope}, {date}] {text}"


def correct_reply(done: list[int], refused: list[int], mid: int) -> str:
    out = f"marked wrong: {done or 'none'}; saved correction #{mid}"
    if refused:
        out += f"; kept {refused} (protected or stated by the user: ask the user)"
    return out


class LocalModels:
    """Loads one local GGUF model at a time (RAM), on first use."""

    def __init__(self, paths: dict[str, Path], factory=None, n_ctx: int = 4096, n_threads: int = 4):
        self.paths = paths
        self.factory = factory or (lambda p: __import__("dore.assistant.core", fromlist=["Core"]).Core(
            p, n_ctx=n_ctx, n_threads=n_threads))
        self.name, self.core = None, None
        self.lock = threading.Lock()

    def ask(self, prompt: str, model: str, max_tokens: int) -> str:
        if model not in self.paths:
            raise ValueError(f"unknown model {model!r}; available: {', '.join(self.paths)}")
        with self.lock:
            if self.name != model:
                self.core = None  # free the old model first
                self.core = self.factory(self.paths[model])
                self.name = model
            return self.core.chat([{"role": "user", "content": prompt}], max_tokens=max_tokens)


def find_models(models_dir: Path) -> dict[str, Path]:
    """GGUF files in data/models, named by size: '1b', '3b' (or the file stem)."""
    out = {}
    for p in sorted(models_dir.glob("*.gguf")):
        size = next((part.lower() for part in p.stem.replace("_", "-").split("-")
                     if part[:-1].isdigit() and part[-1:].lower() == "b"), p.stem)
        out.setdefault(size, p)
    return out


def current_project() -> str:
    """Name of the folder the client was started in ("" for the home folder)."""
    d = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    return "" if d == Path.home().resolve() or d == Path("/") else d.name


def session_brief(db_path: Path, project: str) -> str:
    """A few lines for the start of a session: how much is remembered and the newest notes.
    Reads SQLite only (no embedder), so it is fast enough for a session-start hook."""
    if not Path(db_path).exists():
        return "dore memory: empty so far. Save durable facts with the dore remember tool."
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        q = f"FROM memories WHERE {SEARCHABLE_SQL} AND project IN (?, '')"
        n_proj = db.execute(f"SELECT COUNT(*) FROM memories WHERE {SEARCHABLE_SQL} AND project=?",
                            (project,)).fetchone()[0] if project else 0
        n_all = db.execute(f"SELECT COUNT(*) {q}", (project,)).fetchone()[0]
        newest = db.execute(f"SELECT id, content {q} ORDER BY created DESC LIMIT 3", (project,)).fetchall()
    except sqlite3.Error:
        return "dore memory: not readable right now."
    finally:
        db.close()
    where = f"project '{project}': {n_proj} notes, plus {n_all - n_proj} general" if project else f"{n_all} notes"
    lines = [f"dore memory ({where}). Use the dore recall tool before saying you don't know about past "
             "decisions, settings, locations or preferences."]
    lines += [f"newest #{i}: {c[:100]}" for i, c in newest]
    return "\n".join(lines)


def build_server(store: MemoryStore, models: LocalModels | None = None, default_project: str = "") -> MCPServer:
    server = MCPServer("dore", instructions=INSTRUCTIONS)
    run = anyio.to_thread.run_sync  # embedding and model calls must not block other clients

    def scope(project: str, text: str = "") -> str:
        """Explicit project wins; otherwise the current folder, except facts about the user
        ("my editor is…"), which are general so every project sees them."""
        if project:
            return project
        return "" if text and (PERSONAL.search(text) or ORG.search(text)) else default_project

    @server.tool(description="Search memory for past decisions, settings, locations, preferences. '#<id>' "
                             "returns one full note.")
    async def recall(query: str, project: str = "", k: int = 3) -> str:
        q = query.strip()
        if q.startswith("#") and q[1:].isdigit():
            try:
                m = await run(store.get, int(q[1:]))
            except KeyError:
                return "no such memory"
            return format_hit(m).split("] ", 1)[0] + "] " + m.content
        hits = await run(lambda: store.search(q, k=max(1, min(k, 10)), min_similarity=0.5,
                                              project=scope(project) or None))
        return "\n".join(format_hit(m) for m in hits) if hits else "nothing relevant in memory"

    @server.tool(description="Save short durable facts, all in one call. user_said=true only for facts the user "
                             "stated; your own conclusions stay unverified.")
    async def remember(facts: list[str], project: str = "", user_said: bool = False) -> str:
        trust, source = ("verified", "user") if user_said else ("unverified", "agent")

        def save():
            ids = []
            for fact in (f.strip() for f in facts):
                if not fact:
                    continue
                where = scope(project, fact)
                if len(fact) > LONG_TEXT:
                    ids += ingest_text(store, fact, source=f"{source}-text", trust="unverified", project=where)
                else:
                    ids.append(store.add(fact, kind="fact", source=source, trust=trust, project=where,
                                         supersede=True))
            store.save()
            return ids
        ids = await run(save)
        return "saved " + " ".join(f"#{i}" for i in ids) if ids else "nothing to save"

    @server.tool(description="Mark wrong note ids as wrong (kept) and save the correction. user_said=true if "
                             "the user gave it.")
    async def correct(correction: str, wrong_ids: list[int], project: str = "", user_said: bool = False) -> str:
        project = scope(project, correction)

        def fix():
            done, refused = store.demote(wrong_ids, by_user=user_said)
            mid = store.add(correction, kind="correction", source="user" if user_said else "agent",
                            trust="verified" if user_said else "unverified", project=project)
            store.save()
            return done, refused, mid
        done, refused, mid = await run(fix)
        return correct_reply(done, refused, mid)

    if models and models.paths:
        names = ", ".join(models.paths)

        @server.tool(description=f"Run a small local model (free, private, slow). Small tasks only. model: {names}.")
        async def ask_local(prompt: str, model: str = next(iter(models.paths)), max_tokens: int = 300) -> str:
            t = time.perf_counter()
            out = await run(models.ask, prompt, model, max(1, min(max_tokens, 2000)))
            return f"{out.strip()}\n({model}, {time.perf_counter() - t:.0f}s)"

    return server


def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser(prog="dore-server")
    p.add_argument("--host", default="127.0.0.1", help="keep 127.0.0.1 unless you know why (no auth)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--local-models", action="store_true", help="offer the ask_local tool (off by default: every "
                                                               "tool costs tokens on each request)")
    p.add_argument("--stdio", action="store_true", help="talk MCP over stdin/stdout (started by the client)")
    p.add_argument("--brief", action="store_true", help="print a short memory summary for this folder and exit "
                                                        "(for a session-start hook)")
    args = p.parse_args(argv)
    if args.brief:
        print(session_brief(Config().db_path, current_project()))
        return

    from dore.memory.embed import FastEmbedder

    cfg = Config()
    embedder = FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed"))
    store = MemoryStore(cfg.db_path, cfg.index_path, embedder, cfg.duplicate_threshold, cfg.index_save_interval)
    models = None if not args.local_models else LocalModels(find_models(cfg.data_dir / "models"),
                                                            n_ctx=cfg.n_ctx, n_threads=cfg.n_threads)
    server = build_server(store, models, default_project=current_project() if args.stdio else "")
    where = "stdio" if args.stdio else f"http://{args.host}:{args.port}/mcp"
    # stderr only: in stdio mode stdout carries the MCP protocol.
    print(f"dore memory server on {where} (models: {', '.join(models.paths) if models and models.paths else 'off'})",
          file=sys.stderr, flush=True)
    try:
        if args.stdio:
            server.run("stdio")
        else:
            server.run("streamable-http", host=args.host, port=args.port)
    finally:
        store.close()


if __name__ == "__main__":
    main()
