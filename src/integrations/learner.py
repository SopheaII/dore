"""When to run Haiku consolidation (`learn.consolidate`): rarely, in the background, never twice at once, backing
off after a failure and stopping at a daily token cap. The queue is raw memory not yet judged (`memory.episodes`)."""

from __future__ import annotations

import json
import threading
import time

from dore.learn.consolidate import BATCH, Said, consolidate
from dore.learn.judge import ClaudeCLI, JudgeError

JUDGED = "haiku-1"        # an episode judged by Haiku (`episodes.judged`)
DUE_SENTENCES = BATCH     # a batch is due when full (real replay: batches of ~8 cost 2x the calls) ...
DUE_AGE = 86400.0         # ... or when the oldest has waited a day
DAILY_TOKENS = 50_000     # cap on Haiku tokens a day (a normal day uses ~5k)
FIRST_WAIT, MAX_WAIT = 1800.0, 86400.0  # back-off after a failed call: 30 min, doubling, at most a day
_RUNNING = threading.Lock()


def queued(store, limit: int = BATCH) -> list[tuple]:
    """Oldest raw-memory sentences not yet judged: (id, content, project, session, created)."""
    with store._lock:
        return store.db.execute("SELECT id, content, project, session, created FROM episodes WHERE judged='' "
                                "ORDER BY id LIMIT ?", (limit,)).fetchall()


def _state(store) -> dict:
    try:
        return json.loads(store.meta("learner") or "{}")
    except ValueError:
        return {}


def due(store, now: float | None = None, ended: bool = False) -> bool:
    """A batch is due when full, when its oldest sentence has waited a day, or when a session the sentences come from
    is over (`ended`: SessionEnd; or a newer session has started), so what was said is known by the next session."""
    now = now or time.time()
    st = _state(store)
    if now < st.get("next_try", 0) or (st.get("day") == time.strftime("%Y-%m-%d")
                                       and st.get("tokens", 0) >= DAILY_TOKENS):
        return False
    with store._lock:
        n, oldest = store.db.execute("SELECT count(*), min(created) FROM episodes WHERE judged=''").fetchone()
        over = n > 0 and store.db.execute(
            "SELECT 1 FROM episodes WHERE judged='' AND session != (SELECT session FROM episodes ORDER BY id DESC "
            "LIMIT 1) LIMIT 1").fetchone() is not None
    return n >= DUE_SENTENCES or (n > 0 and (ended or over or now - (oldest or now) >= DUE_AGE))


def run_once(store, ask=None, ended: bool = False) -> dict | None:
    """Judge one batch if one is due and none is running. Returns the batch's stats, or None. A failed call leaves
    the sentences queued and sets when to try again."""
    if not _RUNNING.acquire(blocking=False):
        return None
    try:
        if not due(store, ended=ended):
            return None
        rows = queued(store)
        batch = [Said(c, p, s, t, id=i) for i, c, p, s, t in rows]
        st = _state(store)
        try:
            stats = consolidate(store, batch, ask or ClaudeCLI())
        except JudgeError as e:
            fails = st.get("fails", 0) + 1
            wait = min(MAX_WAIT, FIRST_WAIT * 2 ** (fails - 1))
            st.update(fails=fails, next_try=max(time.time() + wait, e.retry_at or 0), last_error=e.kind)
            store.meta("learner", json.dumps(st))
            return None
        made = stats["lines"]
        with store._lock:
            store.db.executemany("UPDATE episodes SET judged=?, told=?, note_id=? WHERE id=?",
                                 [(JUDGED, int(n in made), (made.get(n) or [None])[0], s.id)
                                  for n, s in enumerate(batch, 1)])
            store.db.commit()
        stats["archived"] = settle(store, {s.id: made.get(n, []) for n, s in enumerate(batch, 1)})
        u = stats.get("usage") or {}
        day = time.strftime("%Y-%m-%d")
        tokens = (st.get("tokens", 0) if st.get("day") == day else 0) + u.get("input", 0) + u.get("output", 0)
        store.meta("learner", json.dumps({"day": day, "tokens": tokens, "fails": 0, "next_try": 0}))
        return stats
    finally:
        _RUNNING.release()


def settle(store, judged: dict[int, list[int]]) -> int:
    """Provisional notes (made at once by the word rules) whose sentences Haiku has now all judged: kept when Haiku
    made or matched them, archived otherwise (never deleted; Haiku's own notes stand). Returns how many archived."""
    rows = store.db.execute("SELECT note_id, episodes FROM provisional").fetchall()
    done = {e for e, in store.db.execute(f"SELECT id FROM episodes WHERE judged='{JUDGED}'")}
    made_by = {}
    for r in store.db.execute(f"SELECT id, note_id FROM episodes WHERE judged='{JUDGED}' AND note_id IS NOT NULL"):
        made_by[r[0]] = {r[1]}
    for e, ids in judged.items():
        made_by.setdefault(e, set()).update(ids)
    gone = 0
    for note_id, eps in rows:
        eps = json.loads(eps)
        if not all(e in done for e in eps):
            continue
        if not any(note_id in made_by.get(e, ()) for e in eps) and store.archive(note_id):
            gone += 1
        store.db.execute("DELETE FROM provisional WHERE note_id=?", (note_id,))
    store.db.commit()
    return gone


def run_in_background(store, ask=None) -> threading.Thread | None:
    """Start `run_once` in a thread when a batch is due (the helper keeps answering prompts meanwhile)."""
    if not due(store) or _RUNNING.locked():
        return None
    t = threading.Thread(target=run_once, args=(store, ask), daemon=True)
    t.start()
    return t


def wait(timeout: float = 240.0) -> bool:
    """Wait for a running batch to finish (the helper is about to close the store). True when none is running."""
    if _RUNNING.acquire(timeout=timeout):
        _RUNNING.release()
        return True
    return False
