"""Local web chat: pick a GGUF model in the browser and talk to the same memory.

    .venv/bin/dore-web                  # http://127.0.0.1:8000
    .venv/bin/dore-web --port 8080 --model 3b

One GGUF model is kept in RAM at a time, so switching models frees the old one first.
Chat, /teach, /correct and the rest share data/memory.db with the CLI and the MCP server.
Bound to 127.0.0.1 by default: there is no login, so do not expose it to a network.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .agent import Agent
from .config import Config
from .server import find_models

MAX_BODY = 1_000_000  # bytes of JSON accepted for one request
PAGE = Path(__file__).with_name("web_page.html").read_text(encoding="utf-8")

HELP = """Commands:
/teach <fact>       save a verified fact
/correct <text>     correct the last answer
/good  /bad         rate the last answer
/mem <query>        show matching memories
/stats              memory statistics
/project [name]     switch project (no name: general)
/projects           list projects
/load <file>        load a text or markdown file
/code <task>        solve a Python task with the checker
/new                clear this chat's history"""


class ModelHub:
    """One GGUF model loaded at a time (RAM); switching unloads the old one first."""

    def __init__(self, paths: dict[str, Path], factory=None, n_ctx: int = 4096, n_threads: int = 4):
        self.paths = dict(paths)
        self.factory = factory or self._load_core
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.name: str | None = None
        self.core = None
        self.lock = threading.Lock()

    def _load_core(self, path: Path):
        from .core import Core

        return Core(path, n_ctx=self.n_ctx, n_threads=self.n_threads)

    def load(self, name: str):
        if name not in self.paths:
            raise KeyError(f"unknown model {name!r}; available: {', '.join(self.paths) or 'none'}")
        with self.lock:
            if self.name != name:
                self.core, self.name = None, None  # free the old model before the new one loads
                self.core = self.factory(self.paths[name])
                self.name = name
            return self.core


class WebApp:
    """Request handling with no HTTP in it, so tests can call it directly."""

    def __init__(self, cfg: Config, store, hub: ModelHub):
        self.cfg = cfg
        self.store = store
        self.hub = hub
        self.agent: Agent | None = None
        self.lock = threading.Lock()  # one model, one agent: run one request at a time
        self.default_model = next(iter(hub.paths), None)

    def models(self) -> dict:
        out = []
        for name, path in self.hub.paths.items():
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            out.append({"name": name, "file": path.name, "size_gb": round(size / 1e9, 2),
                        "loaded": self.hub.name == name})
        return {"models": out, "default": self.hub.name or self.default_model}

    def projects(self) -> dict:
        return {"projects": self.store.projects(),
                "current": self.agent.project if self.agent else ""}

    def stats(self) -> dict:
        return self.store.stats()

    def reset(self) -> dict:
        with self.lock:
            self._reset_agent()
        return {"answer": "new chat"}

    def _reset_agent(self):
        if self.agent is not None:
            self.agent.history.clear()
            self.agent.last_answer_id = None
            self.agent.last_used_ids = []

    def _agent_for(self, model: str) -> Agent:
        core = self.hub.load(model)
        if self.agent is None:
            cfg = self.cfg
            self.agent = Agent(core=core, memory=self.store, top_k=cfg.top_k,
                               min_similarity=cfg.min_similarity, max_fix_rounds=cfg.max_fix_rounds,
                               code_timeout_s=cfg.code_timeout_s, n_ctx=cfg.n_ctx,
                               max_auto_statements=cfg.max_auto_statements)
        else:
            self.agent.core = core
        return self.agent

    def chat(self, message: str, model: str | None = None, project: str | None = None) -> dict:
        message = (message or "").strip()
        if not message:
            raise ValueError("empty message")
        model = model or self.hub.name or self.default_model
        if not model:
            raise ValueError("no .gguf models in data/models")
        with self.lock:
            agent = self._agent_for(model)
            if project is not None and project.strip() != agent.project:
                agent.project = project.strip()
                agent.history.clear()
            if message.startswith("/"):
                reply = self._command(agent, message)
            else:
                t = time.perf_counter()
                answer = agent.ask(message)
                reply = {"answer": answer, "elapsed": round(time.perf_counter() - t, 1),
                         "used": agent.last_used_ids}
            reply.update({"model": self.hub.name, "project": agent.project})
            return reply

    def _command(self, agent: Agent, line: str) -> dict:
        cmd, _, rest = line.partition(" ")
        rest = rest.strip()

        if cmd == "/teach" and rest:
            return {"answer": f"saved verified memory #{agent.teach(rest)}"}
        if cmd == "/correct" and rest:
            mid = agent.correct(rest)
            text = f"saved correction #{mid}; last answer marked wrong"
            if agent.last_demoted_ids:
                text += f"; also marked wrong (kept): {agent.last_demoted_ids}"
            return {"answer": text}
        if cmd == "/good":
            agent.good()
            return {"answer": "thanks, noted"}
        if cmd == "/bad":
            agent.bad()
            return {"answer": "noted; use /correct <text> to teach the right answer"}
        if cmd == "/mem" and rest:
            hits = self.store.search(rest, k=10, touch=False, project=agent.project or None)
            lines = [f"#{m.id} [{m.trust}] sim={m.similarity:.2f} {m.content[:160]}" for m in hits]
            return {"answer": "\n".join(lines) or "nothing found",
                    "hits": [{"id": m.id, "trust": m.trust, "similarity": round(m.similarity, 3),
                              "content": m.content} for m in hits]}
        if cmd == "/stats":
            stats = self.store.stats()
            return {"answer": "\n".join(f"{k}: {v}" for k, v in stats.items()), "stats": stats}
        if cmd == "/project":
            agent.project = rest
            agent.history.clear()
            return {"answer": f"project: {rest or '(general)'}"}
        if cmd == "/projects":
            lines = [f"{name or '(general)'}: {n}{'  <- current' if name == agent.project else ''}"
                     for name, n in sorted(self.store.projects().items())]
            return {"answer": "\n".join(lines) or "no memories yet"}
        if cmd == "/load" and rest:
            from .ingest import ingest_file

            t = time.perf_counter()
            ids = ingest_file(self.store, rest, project=agent.project)
            return {"answer": f"loaded {len(ids)} chunks in {time.perf_counter() - t:.1f}s (unverified)"}
        if cmd == "/code" and rest:
            result = agent.solve_code(rest)
            status = "PASSED" if result.check.passed else "FAILED"
            return {"answer": f"{status} after {result.attempts} attempt(s)"
                               + (f", saved lesson #{result.memory_id}" if result.memory_id else ""),
                    "code": result.code}
        if cmd == "/new":
            self._reset_agent()
            return {"answer": "new chat"}
        if cmd in ("/help", "/?"):
            return {"answer": HELP}
        return {"answer": f"unknown command {cmd}\n\n{HELP}"}


def discover_models(data_dir: Path) -> dict[str, Path]:
    """Every GGUF in data/models, named by size ('1b', '3b'), or by file stem if that clashes."""
    models_dir = data_dir / "models"
    paths = find_models(models_dir)
    known = set(paths.values())
    for path in sorted(models_dir.glob("*.gguf")):
        if path not in known:
            paths[path.stem] = path
    return paths


class Handler(BaseHTTPRequestHandler):
    app: WebApp  # set by serve()

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200):
        self._send(code, json.dumps(data).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/models":
            self._json(self.app.models())
        elif path == "/api/projects":
            self._json(self.app.projects())
        elif path == "/api/stats":
            self._json(self.app.stats())
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/reset":
            return self._json(self.app.reset())
        if path != "/api/chat":
            return self._json({"error": "not found"}, 404)
        try:
            size = int(self.headers.get("Content-Length") or 0)
            if size <= 0 or size > MAX_BODY:
                raise ValueError("bad request size")
            data = json.loads(self.rfile.read(size))
            self._json(self.app.chat(data.get("message"), data.get("model"), data.get("project")))
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:  # model load errors, sandbox errors: show them in the browser
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def log_message(self, fmt, *args):
        pass  # keep the terminal for startup and errors only


def serve(cfg: Config, host: str, port: int, model: str | None = None, n_threads: int | None = None):
    from .embed import FastEmbedder
    from .memory import MemoryStore

    print("Loading embedder and memory...", file=sys.stderr, flush=True)
    embedder = FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed"))
    store = MemoryStore(cfg.db_path, cfg.index_path, embedder, cfg.duplicate_threshold,
                        cfg.index_save_interval)

    paths = discover_models(cfg.data_dir)
    if model:
        if model in paths:
            pass
        elif Path(model).is_file():
            paths[Path(model).stem] = Path(model)
        else:
            store.close()
            raise SystemExit(f"unknown model {model!r}; available: {', '.join(paths) or 'none'}")
    if not paths:
        store.close()
        raise SystemExit(f"no .gguf models in {cfg.data_dir / 'models'}")

    hub = ModelHub(paths, n_ctx=cfg.n_ctx, n_threads=n_threads or cfg.n_threads)
    Handler.app = WebApp(cfg, store, hub)
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    print(f"dore web chat: http://{host}:{port}  (models: {', '.join(paths)}; Ctrl+C to stop)",
          file=sys.stderr, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        store.close()


def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser(prog="dore-web")
    p.add_argument("--host", default="127.0.0.1", help="keep 127.0.0.1 unless you know why (no login)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--model", help="default model name (e.g. 3b) or path to a .gguf")
    p.add_argument("--threads", type=int, help="CPU threads per model (default: config, 4)")
    args = p.parse_args(argv)
    serve(Config(), args.host, args.port, args.model, args.threads)


if __name__ == "__main__":
    main()
