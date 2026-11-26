"""Silent once-a-day auto-update for npm installs."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

URL = "https://registry.npmjs.org/dore-memory/latest"
EVERY = 86400.0  # seconds between two checks
TIMEOUT = 3.0
OFF_VARS = ("DORE_NO_AUTO_UPDATE", "NO_UPDATE_NOTIFIER", "DO_NOT_TRACK", "DISABLE_UPDATES",
            "DISABLE_AUTOUPDATER", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")
INSTALL_FILE = "install.json"  # written by the npm installer: {"version": "0.1.4"}
CACHE_FILE = "update-check.json"  # {"checked": ts, "latest": "0.1.5", "started": "0.1.5"}
LOG_FILE = "update.log"

_running = threading.Lock()


def disabled() -> bool:
    return any(os.environ.get(v, "").strip().lower() not in ("", "0", "false", "no") for v in OFF_VARS)


def _read(path: Path) -> dict:
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, d: dict):
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d))
        os.replace(tmp, path)
    except OSError:
        pass


def installed(data_dir: Path) -> str | None:
    v = _read(data_dir / INSTALL_FILE).get("version")
    return v if isinstance(v, str) and v else None


def parse(v: str) -> tuple[int, ...] | None:
    """'0.1.10' -> (0, 1, 10); pre-releases ('0.2.0-beta') and junk -> None (never announced)."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", v.strip())
    return tuple(int(x) for x in m.groups()) if m else None


def newer(latest: str | None, current: str | None) -> bool:
    a, b = parse(latest or ""), parse(current or "")
    return a is not None and b is not None and a > b


def fetch_latest(url: str = URL, timeout: float = TIMEOUT) -> str | None:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "dore-memory"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            v = json.loads(r.read(65536)).get("version")
        return v if isinstance(v, str) else None
    except Exception:  # offline, firewall, bad reply: try again tomorrow
        return None


def due(data_dir: Path, now: float | None = None) -> bool:
    if disabled() or installed(data_dir) is None:
        return False
    checked = _read(data_dir / CACHE_FILE).get("checked", 0)
    return (now or time.time()) - float(checked or 0) >= EVERY


def check(data_dir: Path, fetch=fetch_latest, now: float | None = None, run=None) -> bool:
    """Ask npm for the latest version if a day has passed, and update to it if it is newer."""
    if not due(data_dir, now) or not _running.acquire(blocking=False):
        return False
    try:
        cache = _read(data_dir / CACHE_FILE)
        latest = fetch()
        cache["checked"] = now or time.time()  # also after a failure: once a day, never a retry loop
        if latest:
            cache["latest"] = latest
            if newer(latest, installed(data_dir)) and (run or start_update)(data_dir, latest):
                cache["started"] = latest
        _write(data_dir / CACHE_FILE, cache)
        return True
    finally:
        _running.release()


def start_update(data_dir: Path, version: str) -> bool:
    """Run `npx dore-memory@<version> update` detached, at low priority, output to data/update.log."""
    npx = shutil.which("npx")
    if not npx or parse(version) is None:
        return False
    if sys.platform == "win32":
        opts = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.BELOW_NORMAL_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW}
    else:
        opts = {"start_new_session": True, "preexec_fn": lambda: os.nice(10)}
    try:
        with open(data_dir / LOG_FILE, "a") as log:
            log.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M')}: updating to {version}\n")
            log.flush()
            subprocess.Popen([npx, "--yes", f"dore-memory@{version}", "update"], stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT, **opts)
        return True
    except (OSError, ValueError):
        return False


def check_in_background(data_dir: Path):
    """For the warm helper's idle time: never blocks it."""
    if due(data_dir):
        threading.Thread(target=check, args=(data_dir,), daemon=True).start()
