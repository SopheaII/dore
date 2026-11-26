"""Background helper for the Claude Code hooks: keeps the embedder and memory index loaded.

    python -m dore.hookd      # started automatically by `dore-hook`; you never need to run it

One instance per data folder (a lock file); listens on data/hook.sock (owner-only; on Windows that file
holds a 127.0.0.1 port and a token instead, see `hookclient`). Quits after
30 idle minutes, or after answering a request once dore's own code has changed, so an update
never leaves an old helper running. While no prompt comes for `IDLE_WORK` seconds it consolidates raw
memory in small batches (`hooks.consolidate`), so that work never delays a prompt for long. Other processes' writes are picked up before each search
(`PRAGMA data_version`), exactly as in a fresh process.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import sys
from pathlib import Path

from dore.config import Config
from dore.integrations.hookclient import SOCKET_NAME, use_tcp

IDLE_EXIT = 30 * 60
IDLE_WORK = 20.0  # s without a prompt before consolidating; each batch takes ~0.1-0.3 s
PKG = Path(__file__).resolve().parents[1]  # the whole dore package, all layers


def code_version() -> float:
    return max(p.stat().st_mtime for p in PKG.rglob("*.py"))


def _lock(f) -> bool:
    """Take the one-helper-per-folder lock without waiting; False if another helper holds it."""
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _listen(sock_path: Path) -> tuple[socket.socket, str | None]:
    """A listening socket and, for the 127.0.0.1 fallback, the token requests must carry."""
    sock_path.unlink(missing_ok=True)
    old_umask = os.umask(0o177)  # socket (or port file) readable/writable by this user only
    try:
        if not use_tcp():
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(str(sock_path))
            return srv, None
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        token = secrets.token_hex(16)
        tmp = sock_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"port": srv.getsockname()[1], "token": token}))
        os.replace(tmp, sock_path)  # clients never read a half-written file
        return srv, token
    finally:
        os.umask(old_umask)


def serve(cfg: Config, idle_exit: float = IDLE_EXIT, store_factory=None, idle_work: float = IDLE_WORK):
    import time

    from dore.integrations.hooks import consolidate, open_store, run_event

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    lock = open(cfg.data_dir / "hook.lock", "w")
    if not _lock(lock):
        lock.close()
        return  # another helper is already running
    sock_path = cfg.data_dir / SOCKET_NAME
    srv, token = _listen(sock_path)
    srv.listen(8)
    srv.settimeout(min(idle_exit, idle_work))
    started = code_version()
    store = (store_factory or open_store)(cfg)
    if store_factory is None:  # load the sentence parser now, not on the user's next prompt (~0.6 s)
        from dore.learn.grammar import nlp
        nlp()
    last_request, work_left, quit_now = time.monotonic(), True, False
    try:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                if time.monotonic() - last_request >= idle_exit:
                    break  # idle: free the RAM
                if work_left:  # the user is away: consolidate one small batch, then listen again
                    try:
                        done = consolidate(store)
                        work_left = any(done.values())
                        srv.settimeout(0.05 if work_left else min(idle_exit, idle_work))
                    except Exception:  # never let background work stop the helper
                        work_left = False
                continue
            last_request, work_left = time.monotonic(), True
            srv.settimeout(min(idle_exit, idle_work))
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
                    if token is not None and not hmac.compare_digest(str(req.get("token", "")), token):
                        raise PermissionError("bad token")
                    if req.get("event") == "quit":  # `dore-hook quit`: Windows can't delete files in use
                        quit_now, reply = True, {"ok": True, "text": ""}
                    else:
                        text = run_event(store, cfg, str(req.get("event", "")), req.get("data") or {})
                        store.save()
                        reply = {"ok": True, "text": text}
                except Exception as exc:  # one bad request must not stop the helper
                    reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                try:
                    conn.sendall(json.dumps(reply).encode() + b"\n")
                except OSError:
                    pass
            if quit_now:
                break
    finally:
        srv.close()
        sock_path.unlink(missing_ok=True)
        store.close()
        lock.close()


def main():
    try:
        os.nice(5)  # background work runs at lower priority (CLAUDE.md); Windows: set at start
    except (OSError, AttributeError):
        pass
    serve(Config())


if __name__ == "__main__":
    main()
