"""Background helper for the Claude Code hooks: keeps the embedder and memory index loaded.

    python -m dore.hookd      # started automatically by `dore-hook`; you never need to run it

One instance per data folder (a lock file); listens on data/hook.sock (owner-only). Quits after
30 idle minutes, or after answering a request once dore's own code has changed, so an update
never leaves an old helper running. Other processes' writes are picked up before each search
(`PRAGMA data_version`), exactly as in a fresh process.
"""

from __future__ import annotations

import fcntl
import json
import os
import socket
from pathlib import Path

from dore.config import Config
from dore.integrations.hookclient import SOCKET_NAME

IDLE_EXIT = 30 * 60
PKG = Path(__file__).resolve().parents[1]  # the whole dore package, all layers


def code_version() -> float:
    return max(p.stat().st_mtime for p in PKG.rglob("*.py"))


def serve(cfg: Config, idle_exit: float = IDLE_EXIT, store_factory=None):
    from dore.integrations.hooks import open_store, run_event

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    lock = open(cfg.data_dir / "hook.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # another helper is already running
    sock_path = cfg.data_dir / SOCKET_NAME
    sock_path.unlink(missing_ok=True)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old_umask = os.umask(0o177)  # socket readable/writable by this user only
    try:
        srv.bind(str(sock_path))
    finally:
        os.umask(old_umask)
    srv.listen(8)
    srv.settimeout(idle_exit)
    started = code_version()
    store = (store_factory or open_store)(cfg)
    if store_factory is None:  # load the sentence parser now, not on the user's next prompt (~0.6 s)
        from dore.learn.grammar import nlp
        nlp()
    try:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                break  # idle: free the RAM
            if code_version() != started:
                conn.close()  # dore was updated: no reply, so the client runs the new code itself
                break
            with conn:
                conn.settimeout(10)
                try:
                    buf = b""
                    while not buf.endswith(b"\n"):
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        buf += chunk
                    req = json.loads(buf)
                    text = run_event(store, cfg, str(req.get("event", "")), req.get("data") or {})
                    store.save()
                    reply = {"ok": True, "text": text}
                except Exception as exc:  # one bad request must not stop the helper
                    reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                try:
                    conn.sendall(json.dumps(reply).encode() + b"\n")
                except OSError:
                    pass
    finally:
        srv.close()
        sock_path.unlink(missing_ok=True)
        store.close()
        lock.close()


def main():
    try:
        os.nice(5)  # background work runs at lower priority (CLAUDE.md)
    except OSError:
        pass
    serve(Config())


if __name__ == "__main__":
    main()
