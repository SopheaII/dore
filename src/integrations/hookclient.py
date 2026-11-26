"""`dore-hook`: fast front end for the Claude Code hooks.

Starting Python and loading the embedding model took ~0.9 s on every prompt (0.68 s of it the
embedder; measured 2026-11-25). This client imports only the standard library and asks a warm
background helper (`dore.hookd`) over a Unix socket in data/. Windows has no Unix sockets in Python:
there the helper listens on 127.0.0.1 and data/hook.sock is a small owner-only file with its port and a
random token that every request must carry. If the helper isn't running, the client starts one for next
time and handles this event itself, so a hook never fails because of it.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys

from pathlib import Path

from dore.config import Config

SOCKET_NAME = "hook.sock"
REPLY_TIMEOUT = 15.0  # below the hook's own timeout (20 s)


def use_tcp() -> bool:
    """True where Python has no Unix sockets (Windows); DORE_HOOK_TCP=1 forces it for tests."""
    return not hasattr(socket, "AF_UNIX") or os.environ.get("DORE_HOOK_TCP") == "1"


def ask_helper(sock_path: str, event: str, data: dict, timeout: float = REPLY_TIMEOUT) -> str | None:
    """The helper's reply text, or None if no helper answered."""
    try:
        msg = {"event": event, "data": data}
        if use_tcp():
            info = json.loads(Path(sock_path).read_text())
            family, addr = socket.AF_INET, ("127.0.0.1", int(info["port"]))
            msg["token"] = info["token"]
        else:
            family, addr = socket.AF_UNIX, sock_path
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(addr)
            s.sendall(json.dumps(msg).encode() + b"\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        reply = json.loads(buf)
        return reply.get("text", "") if reply.get("ok") else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def start_helper():
    """Start the background helper, detached, at low priority; errors are ignored."""
    if sys.platform == "win32":  # no console window, own process group, lower priority (CLAUDE.md)
        detach = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                  | subprocess.BELOW_NORMAL_PRIORITY_CLASS}
    else:
        detach = {"start_new_session": True}
    try:
        subprocess.Popen([sys.executable, "-m", "dore.integrations.hookd"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **detach)
    except OSError:
        pass


def main(argv: list[str] | None = None):
    argv = sys.argv[1:] if argv is None else argv
    event = argv[0] if argv else ""
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        data = {}
    cfg = Config()
    if event == "quit":  # stop the helper (before uninstall); nothing to do if none is running
        ask_helper(str(cfg.data_dir / SOCKET_NAME), "quit", {}, timeout=5.0)
        return
    if os.environ.get("DORE_NO_HELPER") != "1":
        text = ask_helper(str(cfg.data_dir / SOCKET_NAME), event, data,
                          timeout=50.0 if event == "end" else REPLY_TIMEOUT)  # SessionEnd hook allows 60 s
        if text is not None:
            if text:
                print(text)
            return
        start_helper()
    from dore.integrations.hooks import run_inline
    run_inline(event, data)


if __name__ == "__main__":
    main()
