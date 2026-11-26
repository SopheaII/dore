"""Auto-update: never on the prompt path, silent, easy to turn off."""

import json

import pytest

from dore.integrations import update

DAY = update.EVERY


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    for v in update.OFF_VARS:
        monkeypatch.delenv(v, raising=False)


def _install(d, version="0.1.4"):
    (d / update.INSTALL_FILE).write_text(json.dumps({"version": version}))


def _runner():
    started = []
    return started, lambda d, v: started.append(v) or True


def test_no_npm_install_never_checks(tmp_path):
    calls, (started, run) = [], _runner()
    assert not update.check(tmp_path, fetch=lambda: calls.append(1) or "9.9.9", now=1e9, run=run)
    assert calls == [] and started == []


def test_newer_version_updates_once_a_day(tmp_path):
    _install(tmp_path)
    calls, (started, run) = [], _runner()
    fetch = lambda: calls.append(1) or "0.1.5"
    assert update.check(tmp_path, fetch=fetch, now=1e9, run=run)
    assert not update.check(tmp_path, fetch=fetch, now=1e9 + DAY / 2, run=run)  # same day: no request
    assert calls == [1] and started == ["0.1.5"]
    _install(tmp_path, "0.1.5")  # what `npx dore-memory update` writes when it finishes
    assert update.check(tmp_path, fetch=fetch, now=1e9 + DAY, run=run)
    assert started == ["0.1.5"]  # already there: nothing to do


def test_failure_waits_a_day(tmp_path):
    _install(tmp_path)
    calls, (started, run) = [], _runner()
    assert update.check(tmp_path, fetch=lambda: calls.append(1) or None, now=1e9, run=run)
    assert not update.check(tmp_path, fetch=lambda: calls.append(1) or None, now=1e9 + 60, run=run)
    assert calls == [1] and started == []


@pytest.mark.parametrize("latest,updates", [("0.1.4", False), ("0.1.3", False), ("0.1.10", True),
                                            ("0.2.0-beta", False), ("junk", False)])
def test_only_a_newer_release_is_installed(tmp_path, latest, updates):
    _install(tmp_path)
    started, run = _runner()
    update.check(tmp_path, fetch=lambda: latest, now=1e9, run=run)
    assert bool(started) is updates


@pytest.mark.parametrize("var", update.OFF_VARS)
def test_turned_off(tmp_path, monkeypatch, var):
    _install(tmp_path)
    monkeypatch.setenv(var, "1")
    calls, (started, run) = [], _runner()
    assert not update.check(tmp_path, fetch=lambda: calls.append(1) or "0.3.0", now=1e9, run=run)
    assert calls == [] and started == []


def test_off_value_zero_keeps_it_on(monkeypatch):
    monkeypatch.setenv("DO_NOT_TRACK", "0")
    assert not update.disabled()


def test_without_npx_nothing_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(update.shutil, "which", lambda name: None)
    assert not update.start_update(tmp_path, "0.1.5")
    assert not (tmp_path / update.LOG_FILE).exists()
