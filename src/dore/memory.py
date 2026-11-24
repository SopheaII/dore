"""Fast memory: SQLite records + FAISS vector index.

Rules enforced here (see CLAUDE.md):
- nothing is ever hard-deleted; low-value items are archived;
- items marked `wrong`, archived items and the model's unapproved answers are
  kept in SQLite but left out of the vector index, so search never returns them;
- vectors are kept in SQLite so the FAISS index can always be rebuilt.

Speed notes:
- writes are batched (`add_many`): one embedding call, one index search, one commit;
- the index file is written at most every `index_save_interval` seconds (and on
  close). If the program dies in between, the index is checked against SQLite on
  the next start and rebuilt when they differ, so nothing is lost;
- the store is safe to share between threads (one lock around every operation).
"""

from __future__ import annotations

import math
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np

from .embed import Embedder

TRUST_LEVELS = ("verified", "unverified", "wrong")

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'fact',
    source      TEXT NOT NULL DEFAULT 'user',
    trust       TEXT NOT NULL DEFAULT 'unverified',
    protected   INTEGER NOT NULL DEFAULT 0,
    archived    INTEGER NOT NULL DEFAULT 0,
    created     REAL NOT NULL,
    last_used   REAL,
    times_used  INTEGER NOT NULL DEFAULT 0,
    times_seen  INTEGER NOT NULL DEFAULT 1,
    feedback    INTEGER NOT NULL DEFAULT 0,
    vector      BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mem_active ON memories(archived, trust);
"""

# Which rows belong in the vector index (keep in sync with `searchable`).
SEARCHABLE_SQL = "archived=0 AND trust!='wrong' AND NOT (kind='answer' AND trust!='verified')"

EMBED_BATCH = 256

_WORD = re.compile(r"[a-z0-9]+(?:[.:/-][a-z0-9]+)*")


def _signature(text: str) -> frozenset[str]:
    """Words and numbers of a text, ignoring case and punctuation. Two texts are only merged
    as duplicates when these match: embeddings alone score "server IP 10.0.0.5" vs
    "10.0.0.6" at 0.985, and merging them would lose one IP."""
    return frozenset(_WORD.findall(text.lower()))  # items embedded and de-duplicated together in add_many


def searchable(kind: str, trust: str, archived: bool = False) -> bool:
    """True if an item may be returned by search. The model's own answers only count
    once the user approves them, so made-up answers can't reinforce themselves."""
    return not archived and trust != "wrong" and not (kind == "answer" and trust != "verified")


@dataclass
class Memory:
    id: int
    content: str
    kind: str
    source: str
    trust: str
    protected: bool
    archived: bool
    created: float
    last_used: float | None
    times_used: int
    times_seen: int
    feedback: int
    similarity: float = 0.0
    rank: float = 0.0


_COLS = "id, content, kind, source, trust, protected, archived, created, last_used, times_used, times_seen, feedback"


def _row(r) -> Memory:
    return Memory(
        id=r[0], content=r[1], kind=r[2], source=r[3], trust=r[4], protected=bool(r[5]),
        archived=bool(r[6]), created=r[7], last_used=r[8], times_used=r[9], times_seen=r[10], feedback=r[11],
    )


class MemoryStore:
    def __init__(self, db_path: Path | str, index_path: Path | str | None, embedder: Embedder,
                 duplicate_threshold: float = 0.95, index_save_interval: float = 120.0):
        self.embedder = embedder
        self.dim = embedder.dim
        self.duplicate_threshold = duplicate_threshold
        self.index_save_interval = index_save_interval
        self.index_path = Path(index_path) if index_path else None
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")  # faster commits, readers don't block the writer
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self._dirty = False
        self._last_index_write = time.monotonic()
        self.index = self._load_or_rebuild_index()

    # ---------- index ----------
    def _new_index(self):
        return faiss.IndexIDMap2(faiss.IndexFlatIP(self.dim))

    def _searchable_ids(self) -> np.ndarray:
        rows = self.db.execute(f"SELECT id FROM memories WHERE {SEARCHABLE_SQL} ORDER BY id").fetchall()
        return np.array([r[0] for r in rows], dtype=np.int64)

    def _load_or_rebuild_index(self):
        if self.index_path and self.index_path.exists():
            try:
                idx = faiss.read_index(str(self.index_path))
            except RuntimeError:
                idx = None
            # Use the saved file only if it holds exactly the searchable rows.
            if idx is not None and idx.d == self.dim and np.array_equal(
                    np.sort(faiss.vector_to_array(idx.id_map)), self._searchable_ids()):
                return idx
        idx = self.rebuild_index()
        self._dirty = True
        return idx

    def rebuild_index(self):
        with self._lock:
            idx = self._new_index()
            cur = self.db.execute(f"SELECT id, vector FROM memories WHERE {SEARCHABLE_SQL}")
            while rows := cur.fetchmany(50_000):
                ids = np.array([r[0] for r in rows], dtype=np.int64)
                vecs = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32)
                if vecs.size != len(rows) * self.dim:
                    raise ValueError(
                        f"Stored vectors don't match the embedder's dim {self.dim}; "
                        "re-embed memories before switching embedding models."
                    )
                idx.add_with_ids(vecs.reshape(len(rows), self.dim), ids)
            self.index = idx
            self._dirty = True
            return idx

    def save(self, force: bool = False):
        """Commit SQLite and, if due (or forced), write the index file."""
        with self._lock:
            self.db.commit()
            due = time.monotonic() - self._last_index_write >= self.index_save_interval
            if self.index_path and self._dirty and (force or due):
                self.index_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.index_path.with_suffix(".tmp")
                faiss.write_index(self.index, str(tmp))
                tmp.replace(self.index_path)  # atomic: a crash never leaves a half-written index
                self._dirty = False
                self._last_index_write = time.monotonic()

    def _index_add(self, vecs: np.ndarray, ids: list[int]):
        if ids:
            self.index.add_with_ids(np.ascontiguousarray(vecs, dtype=np.float32), np.array(ids, dtype=np.int64))
            self._dirty = True

    def _index_drop(self, mem_id: int):
        self.index.remove_ids(np.array([mem_id], dtype=np.int64))
        self._dirty = True

    def _sync_index(self, before: Memory, after: Memory):
        """Add or remove one item from the index after its trust/archive state changed."""
        was = searchable(before.kind, before.trust, before.archived)
        now = searchable(after.kind, after.trust, after.archived)
        if was and not now:
            self._index_drop(after.id)
        elif now and not was:
            self._index_add(self._vector(after.id)[None, :], [after.id])

    # ---------- write ----------
    def add(self, content: str, kind: str = "fact", source: str = "user", trust: str = "unverified",
            protected: bool = False) -> int:
        """Store one memory; see `add_many`. Returns its id (or the id it merged into)."""
        return self.add_many([content], kind=kind, source=source, trust=trust, protected=protected)[0]

    def add_many(self, contents: list[str], kind: str = "fact", source: str = "user",
                 trust: str = "unverified", protected: bool = False) -> list[int]:
        """Store several memories with the same metadata in one batch.

        A near-duplicate of a searchable item (in the store or earlier in this batch)
        is merged into it instead of stored again. Returns one id per input, in order.
        """
        if trust not in TRUST_LEVELS:
            raise ValueError(f"trust must be one of {TRUST_LEVELS}")
        texts = [c.strip() for c in contents]
        if any(not t for t in texts):
            raise ValueError("empty memory")
        out: list[int] = []
        with self._lock:
            for start in range(0, len(texts), EMBED_BATCH):
                out += self._add_batch(texts[start:start + EMBED_BATCH], kind, source, trust, protected)
            self.db.commit()
        return out

    def _add_batch(self, texts, kind, source, trust, protected) -> list[int]:
        vecs = self.embedder.embed(texts).astype(np.float32)
        indexed = searchable(kind, trust)
        thr = self.duplicate_threshold
        # Items that can't be searched (wrong, unapproved answers) are never merged:
        # merging an answer into a user's fact would let /correct mark that fact wrong.
        if indexed and self.index.ntotal:
            nn_sim, nn_id = self.index.search(vecs, 1)
        else:
            nn_sim = np.full((len(texts), 1), -1.0, dtype=np.float32)
            nn_id = np.full((len(texts), 1), -1, dtype=np.int64)
        within = vecs @ vecs.T if indexed and len(texts) > 1 else None
        sigs = [_signature(t) for t in texts]
        cand = [int(i) for i in nn_id[:, 0] if i != -1]
        cand_sigs = {}
        if cand:
            q = f"SELECT id, content FROM memories WHERE id IN ({','.join('?' * len(set(cand)))})"
            cand_sigs = {i: _signature(c) for i, c in self.db.execute(q, list(set(cand)))}

        now = time.time()
        ids: list[int] = []
        new_rows: list[int] = []  # positions in this batch that were inserted and go in the index
        new_ids: list[int] = []
        for i, (text, vec) in enumerate(zip(texts, vecs)):
            dup, best = None, thr
            if indexed:
                if (nn_id[i, 0] != -1 and nn_sim[i, 0] >= best
                        and cand_sigs.get(int(nn_id[i, 0])) == sigs[i]):
                    dup, best = int(nn_id[i, 0]), float(nn_sim[i, 0])
                if within is not None and new_rows:
                    sims = within[i, new_rows]
                    for j in np.argsort(-sims):
                        if sims[j] < best:
                            break
                        if sigs[new_rows[j]] == sigs[i]:
                            dup = new_ids[j]
                            break
            if dup is not None:
                self._merge(dup, text, trust, protected, now)
                ids.append(dup)
                continue
            cur = self.db.execute(
                "INSERT INTO memories (content, kind, source, trust, protected, created, vector) "
                "VALUES (?,?,?,?,?,?,?)",
                (text, kind, source, trust, int(protected), now, vec.tobytes()),
            )
            ids.append(cur.lastrowid)
            if indexed:
                new_rows.append(i)
                new_ids.append(cur.lastrowid)
        self._index_add(vecs[new_rows], new_ids)
        return ids

    def _merge(self, dup_id: int, text: str, trust: str, protected: bool, now: float):
        # Keep the stronger trust level; refresh the text and date (newer wins) if verified.
        cur_trust = self.db.execute("SELECT trust FROM memories WHERE id=?", (dup_id,)).fetchone()[0]
        new_trust = "verified" if "verified" in (cur_trust, trust) else cur_trust
        self.db.execute(
            "UPDATE memories SET times_seen=times_seen+1, trust=?, protected=MAX(protected, ?), created=? "
            "WHERE id=?", (new_trust, int(protected), now, dup_id))
        if trust == "verified":
            self.db.execute("UPDATE memories SET content=? WHERE id=?", (text, dup_id))

    def set_trust(self, mem_id: int, trust: str):
        if trust not in TRUST_LEVELS:
            raise ValueError(f"trust must be one of {TRUST_LEVELS}")
        with self._lock:
            before = self.get(mem_id)
            self.db.execute("UPDATE memories SET trust=? WHERE id=?", (trust, mem_id))
            self.db.commit()
            self._sync_index(before, self.get(mem_id))

    def mark_wrong(self, mem_id: int):
        self.set_trust(mem_id, "wrong")

    def protect(self, mem_id: int, value: bool = True):
        with self._lock:
            self.get(mem_id)  # KeyError if it doesn't exist
            self.db.execute("UPDATE memories SET protected=? WHERE id=?", (int(value), mem_id))
            self.db.commit()

    def feedback(self, mem_id: int, delta: int):
        with self._lock:
            self.db.execute("UPDATE memories SET feedback=feedback+? WHERE id=?", (delta, mem_id))
            self.db.commit()

    def archive(self, mem_id: int) -> bool:
        """Archive (never delete). Protected items are refused."""
        with self._lock:
            before = self.get(mem_id)
            if before.protected or before.archived:
                return False
            self.db.execute("UPDATE memories SET archived=1 WHERE id=?", (mem_id,))
            self.db.commit()
            self._sync_index(before, self.get(mem_id))
            return True

    def restore(self, mem_id: int):
        with self._lock:
            before = self.get(mem_id)
            if not before.archived:
                return
            self.db.execute("UPDATE memories SET archived=0 WHERE id=?", (mem_id,))
            self.db.commit()
            self._sync_index(before, self.get(mem_id))

    # ---------- read ----------
    def _vector(self, mem_id: int) -> np.ndarray:
        blob = self.db.execute("SELECT vector FROM memories WHERE id=?", (mem_id,)).fetchone()[0]
        return np.frombuffer(blob, dtype=np.float32).copy()

    def get(self, mem_id: int) -> Memory:
        with self._lock:
            r = self.db.execute(f"SELECT {_COLS} FROM memories WHERE id=?", (mem_id,)).fetchone()
        if r is None:
            raise KeyError(mem_id)
        return _row(r)

    def get_many(self, ids: list[int]) -> dict[int, Memory]:
        if not ids:
            return {}
        with self._lock:
            rows = self.db.execute(
                f"SELECT {_COLS} FROM memories WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
        return {r[0]: _row(r) for r in rows}

    def similar(self, text: str, ids: list[int]) -> list[Memory]:
        """The given memories with `.similarity` to `text` filled in (no ranking, no index)."""
        mems = self.get_many(list(ids))
        if not mems:
            return []
        vec = self.embedder.embed([text])[0]
        out = []
        for mid, m in mems.items():
            m.similarity = float(self._vector(mid) @ vec)
            out.append(m)
        return sorted(out, key=lambda m: m.similarity, reverse=True)

    def search(self, query: str, k: int = 5, min_similarity: float = 0.0, touch: bool = True) -> list[Memory]:
        """Return up to k searchable memories, ranked by similarity with small bonuses for
        verified, recent and positively-rated items."""
        vec = self.embedder.embed([query or " "]).astype(np.float32)
        with self._lock:
            if self.index.ntotal == 0:
                return []
            n = min(self.index.ntotal, max(k * 4, 20))
            sims, ids = self.index.search(vec, n)
            hits = [(float(s), int(i)) for s, i in zip(sims[0], ids[0]) if i != -1 and s >= min_similarity]
            rows = self.get_many([i for _, i in hits])
            now = time.time()
            found = []
            for sim, mid in hits:
                m = rows.get(mid)
                if m is None or not searchable(m.kind, m.trust, m.archived):  # index out of step: skip
                    continue
                m.similarity = sim
                age_days = (now - m.created) / 86400
                m.rank = (
                    sim
                    + (0.05 if m.trust == "verified" else 0.0)
                    + 0.03 * math.exp(-age_days / 30)  # newer wins on near-ties
                    + 0.02 * math.tanh(m.feedback / 3)
                )
                found.append(m)
            found.sort(key=lambda m: m.rank, reverse=True)
            found = found[:k]
            if touch and found:
                self.db.executemany(
                    "UPDATE memories SET times_used=times_used+1, last_used=? WHERE id=?",
                    [(now, m.id) for m in found],
                )
                self.db.commit()
            return found

    def stats(self) -> dict:
        with self._lock:
            q = lambda sql: self.db.execute(sql).fetchone()[0]  # noqa: E731
            return {
                "total": q("SELECT COUNT(*) FROM memories"),
                "searchable": self.index.ntotal,
                "verified": q("SELECT COUNT(*) FROM memories WHERE trust='verified' AND archived=0"),
                "unverified": q("SELECT COUNT(*) FROM memories WHERE trust='unverified' AND archived=0"),
                "answers_waiting_approval": q(
                    "SELECT COUNT(*) FROM memories WHERE kind='answer' AND trust='unverified' AND archived=0"),
                "wrong": q("SELECT COUNT(*) FROM memories WHERE trust='wrong'"),
                "archived": q("SELECT COUNT(*) FROM memories WHERE archived=1"),
                "protected": q("SELECT COUNT(*) FROM memories WHERE protected=1"),
            }

    def close(self):
        with self._lock:
            self.save(force=True)
            self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
