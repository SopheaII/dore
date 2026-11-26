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


def due(store, now: float | None = None) -> bool:
    now = now or time.time()
    st = _state(store)
    if now < st.get("next_try", 0) or (st.get("day") == time.strftime("%Y-%m-%d")
                                       and st.get("tokens", 0) >= DAILY_TOKENS):
        return False
    with store._lock:
        n, oldest = store.db.execute("SELECT count(*), min(created) FROM episodes WHERE judged=''").fetchone()
    return n >= DUE_SENTENCES or (n > 0 and now - (oldest or now) >= DUE_AGE)


def run_once(store, ask=None) -> dict | None:
    """Judge one batch if one is due and none is running. Returns the batch's stats, or None. A failed call leaves
    the sentences queued and sets when to try again."""
    if not _RUNNING.acquire(blocking=False):
        return None
    try:
        if not due(store):
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
        u = stats.get("usage") or {}
        day = time.strftime("%Y-%m-%d")
        tokens = (st.get("tokens", 0) if st.get("day") == day else 0) + u.get("input", 0) + u.get("output", 0)
        store.meta("learner", json.dumps({"day": day, "tokens": tokens, "fails": 0, "next_try": 0}))
        return stats
    finally:
        _RUNNING.release()


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
