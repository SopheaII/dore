"""Raw memory of what the user said (like the hippocampus): nothing the user types is lost.

The learning rules decide at once which sentences become notes, and they miss some lasting facts
(a fact shaped like "rust is the language that i care most about" was dropped as a broken piece).
A person does not decide perfectly in the moment either: a quick trace of everything is kept, and
later cues, repetition and replay decide what lasts. So every typed sentence that is not a note is
kept here as an episode:

- saving is plain text on the prompt path (no embedding, ~0.1 ms);
- `embed_pending` gives episodes a vector while idle (the warm helper, SessionEnd), like sleep;
- `recall` finds an episode from an earlier session for a question that matches it strongly;
- `to_judge` / `mark_judged`: episodes are judged again when the learning rules change, so a fixed
  rule also learns what was said before it was fixed (`integrations.hooks.consolidate`).

Episodes are never searched as notes and never overrule a note; once Haiku judged one as teaching nothing, it is
deleted (`MemoryStore.forget_noise`).
"""

from __future__ import annotations

import time

import numpy as np

from .rules import embed_text


def add(store, sentences: list[str], project: str, session: str = "", judged: str = "",
        created: float | None = None) -> list[int]:
    """Keep sentences as episodes; the same sentence again in the same folder counts as seen again."""
    ids = []
    now = created or time.time()
    with store._lock:
        for s in dict.fromkeys(x.strip() for x in sentences if x.strip()):
            row = store.db.execute("SELECT id FROM episodes WHERE project=? AND content=?", (project, s)).fetchone()
            if row:
                store.db.execute("UPDATE episodes SET times_seen=times_seen+1, last_seen=? WHERE id=?", (now, row[0]))
                ids.append(row[0])
            else:
                ids.append(store.db.execute(
                    "INSERT INTO episodes (content, project, session, created, judged) VALUES (?,?,?,?,?)",
                    (s, project, session, now, judged)).lastrowid)
    return ids


def embed_pending(store, limit: int = 64) -> int:
    """Give up to `limit` new episodes a vector (one batch). Returns how many."""
    with store._lock:
        rows = store.db.execute("SELECT id, content FROM episodes WHERE vector IS NULL ORDER BY id LIMIT ?",
                                (limit,)).fetchall()
    if not rows:
        return 0
    vecs = store.embedder.embed([embed_text(c) for _, c in rows]).astype(np.float32)  # outside the lock
    with store._lock:
        store.db.executemany("UPDATE episodes SET vector=? WHERE id=?",
                             [(v.tobytes(), i) for (i, _), v in zip(rows, vecs)])
        store.db.commit()
    return len(rows)


def _matrix(store):
    """All episode vectors, cached on the store; reloaded only when episodes were embedded since."""
    stamp = store.db.execute("SELECT count(*), max(id) FROM episodes WHERE vector IS NOT NULL").fetchone()
    cache = getattr(store, "_episode_cache", None)
    if cache is None or cache[0] != stamp:
        rows = store.db.execute("SELECT id, vector FROM episodes WHERE vector IS NOT NULL ORDER BY id").fetchall()
        ids = np.array([r[0] for r in rows], dtype=np.int64)
        mat = (np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), store.dim)
               if rows else np.zeros((0, store.dim), dtype=np.float32))
        cache = store._episode_cache = (stamp, ids, mat)
    return cache[1], cache[2]


def recall(store, vec: np.ndarray, project: str, session: str = "", exclude=(), min_similarity: float = 0.7,
           k: int = 1) -> list[tuple[int, str, float, float]]:
    """Episodes from earlier sessions close to `vec` (a question's vector) that tell something (not
    requests: on the real replay recalled requests were nearly all noise, "please build it again"),
    in this project or about the user, not yet learned as notes. Returns (id, content, created, similarity),
    best first."""
    with store._lock:
        ids, mat = _matrix(store)
        if not len(ids):
            return []
        sims = mat @ np.asarray(vec, dtype=np.float32).reshape(-1)
        top = [int(j) for j in np.argsort(-sims)[:k + 10] if sims[j] >= min_similarity]
        if not top:
            return []
        rows = {r[0]: r for r in store.db.execute(
            f"SELECT id, content, created, coalesce(scope, project), session, note_id FROM episodes "
            f"WHERE told=1 AND id IN ({','.join('?' * len(top))})", [int(ids[j]) for j in top])}
        out = []
        for j in top:
            r = rows.get(int(ids[j]))
            if (r is None or r[5] is not None or r[0] in exclude or r[3] not in (project, "")
                    or (session and r[4] == session)):
                continue
            out.append((r[0], r[1], r[2], float(sims[j])))
            if len(out) == k:
                break
        if out:
            store.db.execute(f"UPDATE episodes SET recalled=recalled+1 WHERE id IN ({','.join('?' * len(out))})",
                             [o[0] for o in out])
        return out


def to_judge(store, version: str, limit: int = 200) -> list[tuple[int, str, str, float]]:
    """Episodes not yet judged with the rules of `version`, or never consolidated, and not yet learned:
    (id, content, project, created)."""
    with store._lock:
        return store.db.execute(
            "SELECT id, content, project, created FROM episodes WHERE (judged != ? OR told IS NULL) "
            "AND note_id IS NULL ORDER BY id LIMIT ?", (version, limit)).fetchall()


def mark_judged(store, ep_id: int, version: str, scope: str, told: bool, note_id: int | None = None):
    with store._lock:
        store.db.execute("UPDATE episodes SET judged=?, scope=?, told=?, note_id=? WHERE id=?",
                         (version, scope, int(told), note_id, ep_id))


def stats(store) -> dict:
    r = store.db.execute("SELECT count(*), sum(vector IS NULL), sum(note_id IS NOT NULL), sum(recalled) "
                         "FROM episodes").fetchone()
    return {"episodes": r[0], "pending": r[1] or 0, "learned_later": r[2] or 0, "recalled": r[3] or 0}
