"""`dore-hook`: fast front end for the Claude Code hooks.

Starting Python and loading the embedding model took ~0.9 s on every prompt (0.68 s of it the
embedder; measured 2026-11-25). This client imports only the standard library and asks a warm
background helper (`dore.hookd`) over a Unix socket in data/. If the helper isn't running, it
starts one for next time and handles this event itself, so a hook never fails because of it.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys

from dore.config import Config

SOCKET_NAME = "hook.sock"
REPLY_TIMEOUT = 15.0  # below the hook's own timeout (20 s)


def ask_helper(sock_path: str, event: str, data: dict, timeout: float = REPLY_TIMEOUT) -> str | None:
    """The helper's reply text, or None if no helper answered."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(sock_path)
            s.sendall(json.dumps({"event": event, "data": data}).encode() + b"\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        reply = json.loads(buf)
        return reply.get("text", "") if reply.get("ok") else None
    except (OSError, ValueError):
        return None


def start_helper():
    """Start the background helper, detached, at low priority; errors are ignored."""
    try:
        subprocess.Popen([sys.executable, "-m", "dore.integrations.hookd"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
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
