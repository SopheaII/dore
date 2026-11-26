"""Real interactive Claude Code sessions side by side (left: without dore, right: with dore), screenshotted.

    .venv/bin/python docs/claude_code_screenshot.py     # macOS; opens a Terminal window for ~2 min

Each side runs the real `claude` in its own throw-away "shop" folder, in a tmux pane. Session 1 tells a fact,
session 2 (a new `claude`) asks for it. Claude Code's own auto-memory is off on both sides, so only dore can
carry the fact. The right side uses a throw-away dore memory (DORE_DATA); the real memory is never touched.
Screenshots: docs/images/claude-code-1-tell.png, docs/images/claude-code-2-ask.png.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "images"
TMUX = "dore-demo"
T = "tmux -L dore-demo"  # its own tmux server, never the user's
TELL = "Our staging server runs on port 8443. Reply with OK only."
ASK = "Which port is our staging server on? One short line."
# Auto-memory off (only dore remembers); status line and tips off (they show account details).
CLAUDE = ("claude --strict-mcp-config --settings '{\"autoMemoryEnabled\": false, \"spinnerTipsEnabled\": false, "
          "\"statusLine\": {\"type\": \"command\", \"command\": \"true\"}}'")


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def pane_text(p: str) -> str:
    return sh(f"{T} capture-pane -p -t {TMUX}:0.{p}")


def keys(p: str, text: str, enter: bool = True) -> None:
    subprocess.run([*T.split(), "send-keys", "-t", f"{TMUX}:0.{p}", "-l", text])
    if enter:
        time.sleep(0.3)
        subprocess.run([*T.split(), "send-keys", "-t", f"{TMUX}:0.{p}", "Enter"])


def wait_ready(p: str, timeout: float = 60) -> None:
    """Claude's input box is up; answer "Yes, I trust this folder" if asked (the default is "No")."""
    end = time.time() + timeout
    while time.time() < end:
        t = pane_text(p).lower()
        if "trust this folder" in t:
            subprocess.run([*T.split(), "send-keys", "-t", f"{TMUX}:0.{p}", "Down"])
            time.sleep(0.5)
            subprocess.run([*T.split(), "send-keys", "-t", f"{TMUX}:0.{p}", "Enter"])
            time.sleep(3)
            continue
        if "enter to confirm" in t:  # another start-up question (e.g. browser tools): Enter keeps the default
            subprocess.run([*T.split(), "send-keys", "-t", f"{TMUX}:0.{p}", "Enter"])
            time.sleep(2)
            continue
        if "shift+tab" in t or "for shortcuts" in t:
            time.sleep(1)
            return
        time.sleep(0.5)
    raise RuntimeError(f"Claude Code did not start in pane {p}:\n{pane_text(p)}")


def wait_answer(p: str, timeout: float = 120) -> None:
    """Claude has finished answering: the 'esc to interrupt' line is gone for a few seconds."""
    time.sleep(3)
    end, quiet = time.time() + timeout, 0
    while time.time() < end and quiet < 4:
        quiet = 0 if "esc to interrupt" in pane_text(p).lower() else quiet + 1
        time.sleep(1)


def screenshot(window: str, name: str) -> None:
    """Capture the Terminal window, then crop off its title bar (it shows the user's name)."""
    from PIL import Image
    path = OUT / name
    sh(f"screencapture -x -o -l {window} {path}")
    img = Image.open(path)
    scale = img.width / 1440
    img.crop((0, int(30 * scale), img.width, img.height)).save(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="dore-cc-", dir="/tmp"))
    data = root / "dore-data"
    data.mkdir()
    (data / "cache").symlink_to(REPO / "data" / "cache")  # embedding model already downloaded
    sides = {
        "0": (root / "without" / "shop", f"export DORE_HOME={root}/no-dore", "WITHOUT dore"),
        "1": (root / "with" / "shop", f"export DORE_HOME={REPO} DORE_DATA={data}", "WITH dore"),
    }
    sh(f"{T} kill-server 2>/dev/null")
    # Start clean: without this session's CLAUDE* variables, each side is an ordinary new Claude Code.
    clean = " ".join(f"-u {k}" for k in os.environ if k.startswith(("CLAUDE", "CC_")))
    sh(f"env {clean} {T} new-session -d -s {TMUX} -x 200 -y 48 && {T} split-window -h -t {TMUX}")
    sh(f"{T} set -t {TMUX} pane-border-status top && {T} set -t {TMUX} pane-border-format ' #{{@label}} '")
    sh(f"{T} set -t {TMUX} status off")
    window = sh(f"""osascript -e 'tell application "Terminal"
        do script "{T} attach -t {TMUX}"
        delay 1
        set bounds of front window to {{0, 25, 1440, 894}}
        return id of front window
    end tell'""")
    try:
        for p, (folder, env, title) in sides.items():
            folder.mkdir(parents=True)
            sh(f"{T} set -p -t {TMUX}:0.{p} @label '{title}'")
            keys(p, f"cd {folder} && {env} CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 && clear && {CLAUDE}")
        for n, (prompt, shot) in enumerate([(TELL, "claude-code-1-tell.png"), (ASK, "claude-code-2-ask.png")]):
            if n:  # a new Claude Code session on both sides
                for p in sides:
                    keys(p, "/exit")
                time.sleep(3)
                for p in sides:
                    keys(p, f"clear && {CLAUDE}")
            for p in sides:
                wait_ready(p)
            for p in sides:
                keys(p, prompt)
            for p in sides:
                wait_answer(p)
            time.sleep(1)
            screenshot(window, shot)
        for p in sides:
            keys(p, "/exit")
        time.sleep(2)
    finally:
        sh(f"{T} kill-server")
        sh(f"""osascript -e 'tell application "Terminal" to close (every window whose id is {window})' 2>/dev/null""")
        sh(f"lsof -t {data / 'hook.sock'} | xargs kill 2>/dev/null")  # the throw-away warm helper
        shutil.rmtree(root, ignore_errors=True)
        for d in (Path.home() / ".claude" / "projects").glob("*dore-cc-*"):
            shutil.rmtree(d, ignore_errors=True)
    print("saved:", *sorted(p.name for p in OUT.glob("claude-code-*.png")))


if __name__ == "__main__":
    main()
