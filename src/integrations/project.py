"""Which project a session belongs to: its git repo, not its folder name."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

HOME_KEY = "~"


@dataclass(frozen=True)
class Project:
    key: str                     # stored in `memories.project`
    root: Path | None            # repo root (main worktree), None for the home place
    aliases: tuple[str, ...] = ()  # keys older versions stored for this place (folder names, the path key)
    git: bool = False            # found by git (else the key is a folder path)


def _read(p: Path) -> str:
    try:
        return p.read_text(errors="ignore")
    except OSError:
        return ""


def _git(d: Path, stop: Path | None) -> tuple[Path, Path] | None:
    """(folder holding `.git`, git common dir) for the nearest repo at or above `d`, not above `stop`."""
    for p in (d, *d.parents):
        if stop is not None and p == stop and d != stop:
            return None  # a repo in the home folder (dotfiles) does not own every folder under it
        g = p / ".git"
        if g.is_dir():
            return p, g
        if g.is_file():  # worktree or submodule: "gitdir: <path>"
            m = re.match(r"gitdir:\s*(.+)", _read(g).strip())
            if not m:
                return None
            gd = Path(m.group(1).strip())
            gd = (gd if gd.is_absolute() else p / gd).resolve()
            common = _read(gd / "commondir").strip()
            if common:
                c = Path(common)
                gd = (c if c.is_absolute() else gd / c).resolve()
            return p, gd
    return None


def _remote(git_dir: Path) -> str:
    """Normalised URL of `origin` (else the first remote): "host/owner/repo"; "" for none or a local path."""
    urls, current = {}, None
    for line in _read(git_dir / "config").splitlines():
        line = line.strip()
        if line.startswith("["):
            m = re.match(r'\[remote\s+"([^"]+)"\]', line)
            current = m.group(1) if m else None
        elif current and (m := re.match(r"url\s*=\s*(\S+)", line)):
            urls.setdefault(current, m.group(1))
    url = urls.get("origin") or next(iter(urls.values()), "")
    if not url or url.startswith(("/", ".", "file:")):
        return ""
    url = re.sub(r"^[a-z+]+://", "", url)   # scheme
    url = re.sub(r"^[^@/]+@", "", url)      # user or token
    url = re.sub(r"^([^/:]+):(?!\d+/)", r"\1/", url)  # scp form host:owner/repo
    url = re.sub(r":\d+/", "/", url)        # port
    url = re.sub(r"\.git/?$", "", url).rstrip("/")
    host, _, rest = url.partition("/")
    return f"{host.lower()}/{rest}" if rest else ""


@lru_cache(maxsize=256)
def _resolve(folder: str, start: str | None = None) -> Project:
    d = Path(folder)
    home = Path.home().resolve()
    if d in (home, Path("/")):
        return Project(HOME_KEY, None)
    found = _git(d, home if d.is_relative_to(home) else None)
    if found is None:
        s = Path(start) if start else None
        if s is not None and s != d and d.is_relative_to(s) and s not in (home, Path("/")):
            d = s  # no git: a subfolder of the folder the session started in is part of it
        return Project(str(d), d, (d.name,))
    holder, git_dir = found
    root = git_dir.parent if git_dir.name == ".git" else holder  # main worktree; a submodule is its own repo
    key = _remote(git_dir) or str(root)
    old = {root.name, holder.name, d.name, str(root)} - {key, ""}
    return Project(key, root, tuple(sorted(old)), git=True)


def project_of(cwd: str | None, start: str | None = None) -> Project:
    """The project of a session working in `cwd`; `start`: the folder the session was started in
    (Claude Code's `CLAUDE_PROJECT_DIR`), used when there is no git repo."""
    return _resolve(str(Path(cwd or ".").resolve()), str(Path(start).resolve()) if start else None)


def display_name(key: str) -> str:
    """Short name for labels: the last part of the key ("github.com/a/shop" -> "shop")."""
    return "home" if key == HOME_KEY else key.rstrip("/").rsplit("/", 1)[-1]
