"""A project is its git repo, not its folder name."""

import subprocess
from pathlib import Path

import pytest

from dore.integrations import project as P
from dore.integrations.hooks import resolve_project
from dore.memory import MemoryStore
from dore.memory.embed import HashEmbedder


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"],
                        "HOME": str(cwd)})


def repo(path: Path, remote: str | None = None) -> Path:
    path.mkdir(parents=True)
    git("init", "-q", cwd=path)
    if remote:
        git("remote", "add", "origin", remote, cwd=path)
    (path / "f").write_text("x")
    git("add", "f", cwd=path)
    git("commit", "-qm", "x", cwd=path)
    return path


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    P._resolve.cache_clear()
    monkeypatch.setattr(P.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    (tmp_path / "home").mkdir()
    yield
    P._resolve.cache_clear()


def test_subfolders_and_worktrees_share_the_repo(tmp_path):
    r = repo(tmp_path / "work" / "shop")
    (r / "npm" / "deep").mkdir(parents=True)
    git("worktree", "add", "-q", str(tmp_path / "wt" / "feature-x"), cwd=r)
    key = P.project_of(str(r)).key
    assert key == str(r.resolve())
    assert P.project_of(str(r / "npm" / "deep")).key == key
    assert P.project_of(str(tmp_path / "wt" / "feature-x")).key == key


def test_same_folder_name_in_two_repos_stays_apart(tmp_path):
    a = repo(tmp_path / "a" / "api", "git@github.com:acme/api.git")
    b = repo(tmp_path / "b" / "api", "https://github.com/other/api.git")
    assert P.project_of(str(a)).key == "github.com/acme/api"
    assert P.project_of(str(b)).key == "github.com/other/api"
    assert P.display_name("github.com/acme/api") == "api"


@pytest.mark.parametrize("url,key", [
    ("https://user:secret-token@github.com/Acme/Shop.git", "github.com/Acme/Shop"),
    ("ssh://git@gitlab.example.com:2222/team/app.git", "gitlab.example.com/team/app"),
    ("git@GitHub.com:me/dore-memory.git", "github.com/me/dore-memory"),
])
def test_remote_keys_drop_credentials_and_ports(tmp_path, url, key):
    r = repo(tmp_path / "r", url)
    assert P.project_of(str(r)).key == key


def test_no_git_is_the_full_path_and_home_is_its_own_place(tmp_path):
    d = tmp_path / "notes" / "shop"
    d.mkdir(parents=True)
    assert P.project_of(str(d)).key == str(d.resolve())
    assert P.project_of(str(tmp_path / "home")).key == P.HOME_KEY
    assert P.display_name(P.HOME_KEY) == "home"


def test_a_repo_in_the_home_folder_does_not_own_every_folder_under_it(tmp_path):
    home = tmp_path / "home"
    git("init", "-q", cwd=home)  # dotfiles
    plain = home / "Documents" / "todo"
    plain.mkdir(parents=True)
    assert P.project_of(str(plain)).key == str(plain.resolve())


def test_notes_under_old_folder_names_move_to_the_repo(tmp_path):
    r = repo(tmp_path / "dore", "git@github.com:me/dore-memory.git")
    (r / "npm").mkdir()
    s = MemoryStore(tmp_path / "m.db", tmp_path / "m.faiss", HashEmbedder())
    a = s.add("The site deploys to Fly", trust="verified", project="dore")
    b = s.add("The package is published by CI", trust="verified", project="npm")
    g = s.add("My editor is Helix", trust="verified", project="")
    o = s.add("The blog uses Hugo", trust="verified", project="blog")
    key = resolve_project(s, str(r / "npm"))
    assert key == "github.com/me/dore-memory"
    assert [s.get(i).project for i in (a, b, g, o)] == [key, key, "", "blog"]
    s.close()


def test_opencode_sends_its_folder_and_the_bridge_finds_the_repo(tmp_path):
    from dore.integrations.bridge import Bridge
    r = repo(tmp_path / "shop", "git@github.com:acme/shop.git")
    (r / "web").mkdir()
    b = Bridge()
    assert b.project({"project": str(r / "web")}, store=False) == "github.com/acme/shop"
    assert b.project({"project": "shop"}, store=False) == "shop"  # a key given by the caller is kept
    assert b.project({"project": str(tmp_path / "home")}, store=False) == P.HOME_KEY


def test_no_git_subfolder_of_the_start_folder_is_part_of_it(tmp_path):
    blog = tmp_path / "work" / "blog"
    (blog / "posts" / "2026").mkdir(parents=True)
    other = tmp_path / "work" / "notes"
    other.mkdir()
    key = P.project_of(str(blog / "posts" / "2026"), start=str(blog)).key
    assert key == str(blog.resolve())
    assert P.project_of(str(other), start=str(blog)).key == str(other.resolve())  # not under the start folder
    assert P.project_of(str(blog / "posts"), start=str(tmp_path / "home")).key == str((blog / "posts").resolve())


def test_git_wins_over_the_start_folder(tmp_path):
    r = repo(tmp_path / "work" / "api", "git@github.com:acme/api.git")
    assert P.project_of(str(r), start=str(tmp_path / "work")).key == "github.com/acme/api"
