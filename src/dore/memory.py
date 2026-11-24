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
- the store is safe to share between threads (one lock around every operation);
- several processes may open the same memory.db (e.g. one per Claude Code session):
  SQLite is the shared truth, and each process updates its own vector index from it
  before searching when another process has written (`PRAGMA data_version`).
"""

from __future__ import annotations

import math
import os
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
    vector      BLOB NOT NULL,
    last_seen   REAL,
    replaced_by INTEGER,
    valid_to    REAL
);
CREATE INDEX IF NOT EXISTS idx_mem_active ON memories(archived, trust);
"""

# Keyword index (SQLite FTS5), kept in step with `memories` by triggers.
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content, content='memories', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS mem_fts_ins AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS mem_fts_upd AFTER UPDATE OF content ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS mem_fts_del AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;
"""

STOPWORDS = frozenset("""a an the is are am was were be been being do does did i me my mine you your yours we our
he she it its they them their what which who whom whose where when why how this that these those of in on at to
for from by with about as and or not no yes can could will would should shall may might must have has had
there here please tell know any some""".split())

# Which rows belong in the vector index (keep in sync with `searchable`).
SEARCHABLE_SQL = ("archived=0 AND trust!='wrong' AND NOT (kind='answer' AND trust!='verified') "
                  "AND replaced_by IS NULL")

EMBED_BATCH = 256

_WORD = re.compile(r"[a-z0-9]+(?:[.:/-][a-z0-9]+)*")


def _signature(text: str) -> frozenset[str]:
    """Set of words and numbers of a text, ignoring case and punctuation (keyword matching)."""
    return frozenset(_WORD.findall(text.lower()))


def _dup_key(text: str) -> tuple[str, ...]:
    """Words and numbers of a text IN ORDER, ignoring case and punctuation. Two texts are only
    merged as duplicates when these match: embeddings alone score "server IP 10.0.0.5" vs
    "10.0.0.6" at 0.985, and a word set alone merged "Alice reports to Bob" with "Bob reports
    to Alice" (probe 2026-11-25)."""
    return tuple(_WORD.findall(text.lower()))


_NEGATION = frozenset("not no never don t doesn didn isn aren wasn won do does".split())


def _frame(old: str, new: str) -> tuple[tuple, tuple, tuple]:
    """(shared words, changed part of old, changed part of new): the words both texts share
    at the start and the end, and what differs in between."""
    a, b = _dup_key(old), _dup_key(new)
    p = 0
    while p < min(len(a), len(b)) and a[p] == b[p]:
        p += 1
    q = 0
    while q < min(len(a), len(b)) - p and a[-1 - q] == b[-1 - q]:
        q += 1
    return a[:p] + a[len(a) - q:], a[p:len(a) - q], b[p:len(b) - q]


# A changed detail after these words replaces the old one ("I live in X" -> "I live in Y");
# after the MULTI ones both can be true at once ("I have a dog Buddy" + "I have a dog Max";
# Mem0's model deleted the first dog in exactly this case).
SINGLE_VALUE = frozenset("""is am are was were m s live lives living work works working moved move use uses
using prefer prefers runs run running called named name born""".split())
MULTI_VALUE = frozenset("""have has had got get like likes love loves enjoy also another and or visited know knows
friend friends kid kids child children brother brothers sister sisters cousin cousins colleague colleagues
pet pets""".split())


def replaces(old: str, new: str) -> bool:
    """True when `new` is an update of `old`: one detail changed (`same_frame`) in a sentence
    that can only hold one value at a time. Unclear cases return False: both are kept."""
    if not same_frame(old, new):
        return False
    shared = set(_frame(old, new)[0])
    return bool(shared & SINGLE_VALUE) and not shared & MULTI_VALUE


def same_frame(old: str, new: str, max_change: int = 3) -> bool:
    """True when `new` is `old` with one detail changed: same words before and after, and only
    a short part different ("My car is a Toyota" -> "My car is a Honda", "Use tabs" -> "Do not
    use tabs"). Used to decide which notes a correction replaces, so "I bought my car in 2020"
    is not marked wrong by "My car is a Honda". Limit: it can't tell kinds of detail apart
    ("My car is red" -> "My car is a Honda" also matches)."""
    shared, da, db = _frame(old, new)
    if not da and not db:
        return False  # same words: a repeat, not a change
    if len(da) > max_change or len(db) > max_change or len(shared) < 2:
        return False
    if not da or not db:  # one side only adds words: a change only if it is a negation
        return set(da or db) <= _NEGATION
    if any(c.isdigit() for c in "".join(da)) != any(c.isdigit() for c in "".join(db)):
        return False  # a number replaced by a word (or back) is a different detail
    return True


def _jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a or b else 1.0


def _query_terms(text: str) -> list[str]:
    """Words and identifiers of a query worth matching by keyword (no stopwords)."""
    return [t for t in dict.fromkeys(_WORD.findall(text.lower())) if t not in STOPWORDS and len(t) > 1]


def _is_identifier(term: str) -> bool:
    """Codes, IPs, versions, ports...: exact matches on these matter more than meaning."""
    return any(c.isdigit() for c in term) or any(c in ".:/-" for c in term)


def searchable(kind: str, trust: str, archived: bool = False, replaced: bool = False) -> bool:
    """True if an item may be returned by search. The model's own answers only count
    once the user approves them, so made-up answers can't reinforce themselves. A fact
    replaced by a newer one (`replaced_by`) is kept but no longer returned."""
    return (not archived and not replaced and trust != "wrong"
            and not (kind == "answer" and trust != "verified"))


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
    project: str = ""
    last_seen: float | None = None  # last time the same fact was stated again
    replaced_by: int | None = None   # newer memory that replaced this one (kept, not searched)
    valid_to: float | None = None    # when it was replaced
    similarity: float = 0.0
    keyword: float = 0.0  # share of the query's keywords found in this memory
    rank: float = 0.0


_COLS = ("id, content, kind, source, trust, protected, archived, created, last_used, times_used, times_seen, "
         "feedback, project, last_seen, replaced_by, valid_to")


def _row(r) -> Memory:
    return Memory(
        id=r[0], content=r[1], kind=r[2], source=r[3], trust=r[4], protected=bool(r[5]),
        archived=bool(r[6]), created=r[7], last_used=r[8], times_used=r[9], times_seen=r[10], feedback=r[11],
        project=r[12], last_seen=r[13], replaced_by=r[14], valid_to=r[15],
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
        # timeout: another process (a Claude Code session, the hook) may be writing; wait for it
        # instead of failing after SQLite's 5 s default and losing the write.
        self.db = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
        self.db.execute("PRAGMA journal_mode=WAL")  # faster commits, readers don't block the writer
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self._migrate()
        self._dirty = False
        self.last_replaced: list[int] = []  # ids the last add_many(supersede=True) replaced
        self._last_index_write = time.monotonic()
        self.index = self._load_or_rebuild_index()
        self._data_version = self.db.execute("PRAGMA data_version").fetchone()[0]

    def _migrate(self):
        """Bring an older memory.db up to date (adds columns/indexes; never removes data)."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(memories)")}
        if "project" not in cols:
            self.db.execute("ALTER TABLE memories ADD COLUMN project TEXT NOT NULL DEFAULT ''")
        for col, typ in (("last_seen", "REAL"), ("replaced_by", "INTEGER"), ("valid_to", "REAL")):
            if col not in cols:
                self.db.execute(f"ALTER TABLE memories ADD COLUMN {col} {typ}")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_mem_project ON memories(project)")
        had_fts = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='memories_fts'").fetchone() is not None
        self.db.executescript(FTS_SCHEMA)
        if not had_fts:
            self.db.execute("INSERT INTO memories_fts(memories_fts) VALUES ('rebuild')")
        self.db.commit()

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

    def _refresh(self):
        """Catch up with writes made by other processes since we last looked (cheap no-op
        when nothing changed). Must be called with the lock held."""
        v = self.db.execute("PRAGMA data_version").fetchone()[0]
        if v == self._data_version:
            return
        self._data_version = v
        want = self._searchable_ids()
        have = np.sort(faiss.vector_to_array(self.index.id_map))
        extra = np.setdiff1d(have, want)
        missing = np.setdiff1d(want, have)
        if extra.size:
            self.index.remove_ids(extra.astype(np.int64))
            self._dirty = True
        for start in range(0, missing.size, 5000):
            chunk = [int(i) for i in missing[start:start + 5000]]
            rows = self.db.execute(
                f"SELECT id, vector FROM memories WHERE id IN ({','.join('?' * len(chunk))})", chunk).fetchall()
            vecs = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), self.dim)
            self._index_add(vecs, [r[0] for r in rows])

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
                tmp = self.index_path.with_suffix(f".{os.getpid()}.tmp")  # unique per process
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
        was = searchable(before.kind, before.trust, before.archived, before.replaced_by is not None)
        now = searchable(after.kind, after.trust, after.archived, after.replaced_by is not None)
        if was and not now:
            self._index_drop(after.id)
        elif now and not was:
            self._index_add(self._vector(after.id)[None, :], [after.id])

    # ---------- write ----------
    def add(self, content: str, kind: str = "fact", source: str = "user", trust: str = "unverified",
            protected: bool = False, project: str = "", supersede: bool = False) -> int:
        """Store one memory; see `add_many`. Returns its id (or the id it merged into)."""
        return self.add_many([content], kind=kind, source=source, trust=trust, protected=protected,
                             project=project, supersede=supersede)[0]

    def add_many(self, contents: list[str], kind: str = "fact", source: str = "user",
                 trust: str = "unverified", protected: bool = False, project: str = "",
                 supersede: bool = False) -> list[int]:
        """Store several memories with the same metadata in one batch.

        A near-duplicate of a searchable item (in the store or earlier in this batch)
        is merged into it instead of stored again. Returns one id per input, in order.
        `project` scopes the memory ("" = general, visible from every project).
        supersede: each new item replaces older notes it updates (`replaces`), in input
        order, so "I live in X. ... I live in Y." ends with Y. Ids in `last_replaced`.
        """
        if trust not in TRUST_LEVELS:
            raise ValueError(f"trust must be one of {TRUST_LEVELS}")
        texts = [c.strip() for c in contents]
        if any(not t for t in texts):
            raise ValueError("empty memory")
        out: list[int] = []
        with self._lock:
            self._refresh()
            self.last_replaced = []
            first_new = (self.db.execute("SELECT MAX(id) FROM memories").fetchone()[0] or 0) + 1
            for start in range(0, len(texts), EMBED_BATCH):
                out += self._add_batch(texts[start:start + EMBED_BATCH], kind, source, trust, protected,
                                       project)
                # Commit per batch: the next batch's embedding (slow) must not run while this
                # process holds SQLite's write lock, or other sessions' writes time out.
                self.db.commit()
            if supersede:
                for mid in dict.fromkeys(i for i in out if i >= first_new):
                    self.last_replaced += self._supersede(mid)
                self.db.commit()
        return out

    def _supersede(self, new_id: int, min_similarity: float = 0.6) -> list[int]:
        """Mark older notes that `new_id` updates as replaced (kept, dated, no longer searched).
        min_similarity only shortlists candidates; `replaces` decides. Real updates measured
        0.76-0.90 with bge-small (city, car, port, editor, age, names; 2026-11-25).
        Only within the same project; never protected notes; an unverified note can't replace
        a verified one. Must be called with the lock held."""
        new = self.get(new_id)
        if not searchable(new.kind, new.trust, new.archived) or not self.index.ntotal:
            return []
        sims, ids = self.index.search(self._vector(new_id)[None, :], min(self.index.ntotal, 20))
        hits = [(float(s), int(i)) for s, i in zip(sims[0], ids[0]) if i not in (-1, new_id) and s >= min_similarity]
        rows = self.get_many([i for _, i in hits])
        done = []
        for _, i in hits:
            m = rows.get(i)
            if (m is None or m.project != new.project or m.protected or m.created > new.created
                    or m.kind not in ("fact", "statement", "correction")
                    or (m.trust == "verified" and new.trust != "verified")
                    or not replaces(m.content, new.content)):
                continue
            self.db.execute("UPDATE memories SET replaced_by=?, valid_to=? WHERE id=?", (new_id, time.time(), i))
            self._sync_index(m, self.get(i))
            done.append(i)
        return done

    def _add_batch(self, texts, kind, source, trust, protected, project) -> list[int]:
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
        sigs = [_dup_key(t) for t in texts]
        cand = [int(i) for i in nn_id[:, 0] if i != -1]
        cand_sigs = {}
        if cand:
            # Only merge within the same project.
            q = f"SELECT id, content, project FROM memories WHERE id IN ({','.join('?' * len(set(cand)))})"
            cand_sigs = {i: _dup_key(c) for i, c, pr in self.db.execute(q, list(set(cand))) if pr == project}

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
                self._merge(dup, text, source, trust, protected, now)
                ids.append(dup)
                continue
            cur = self.db.execute(
                "INSERT INTO memories (content, kind, source, trust, protected, created, vector, project) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (text, kind, source, trust, int(protected), now, vec.tobytes(), project),
            )
            ids.append(cur.lastrowid)
            if indexed:
                new_rows.append(i)
                new_ids.append(cur.lastrowid)
        self._index_add(vecs[new_rows], new_ids)
        return ids

    def _merge(self, dup_id: int, text: str, source: str, trust: str, protected: bool, now: float):
        """Same fact stated again. Keep the stronger trust level and the first date (`created`);
        `last_seen` records the repeat (recency uses it). If the repeat is what makes the note
        verified, its source changes too, so an agent's note the user confirms says `user`."""
        cur_trust = self.db.execute("SELECT trust FROM memories WHERE id=?", (dup_id,)).fetchone()[0]
        new_trust = "verified" if "verified" in (cur_trust, trust) else cur_trust
        self.db.execute(
            "UPDATE memories SET times_seen=times_seen+1, trust=?, protected=MAX(protected, ?), last_seen=? "
            "WHERE id=?", (new_trust, int(protected), now, dup_id))
        if trust == "verified":
            # Same words in the same order: only case/punctuation can differ; keep the newer form.
            self.db.execute("UPDATE memories SET content=? WHERE id=?", (text, dup_id))
            if cur_trust != "verified":
                self.db.execute("UPDATE memories SET source=? WHERE id=?", (source, dup_id))

    def set_trust(self, mem_id: int, trust: str):
        if trust not in TRUST_LEVELS:
            raise ValueError(f"trust must be one of {TRUST_LEVELS}")
        with self._lock:
            self._refresh()
            before = self.get(mem_id)
            self.db.execute("UPDATE memories SET trust=? WHERE id=?", (trust, mem_id))
            self.db.commit()
            self._sync_index(before, self.get(mem_id))

    def mark_wrong(self, mem_id: int):
        self.set_trust(mem_id, "wrong")

    def demote(self, ids: list[int], by_user: bool) -> tuple[list[int], list[int]]:
        """Mark notes wrong on someone's say-so; returns (marked, refused). Protected notes are
        never marked wrong this way, and only the user can mark a note the user stated: an
        agent's correction can't overrule the user. Unknown ids are skipped."""
        done, refused = [], []
        for i in ids:
            try:
                m = self.get(int(i))
            except (KeyError, TypeError, ValueError):
                continue
            if m.trust == "wrong":
                continue
            if m.protected or (not by_user and m.source == "user" and m.trust == "verified"):
                refused.append(m.id)
                continue
            self.mark_wrong(m.id)
            done.append(m.id)
        return done, refused

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
            self._refresh()
            before = self.get(mem_id)
            if before.protected or before.archived:
                return False
            self.db.execute("UPDATE memories SET archived=1 WHERE id=?", (mem_id,))
            self.db.commit()
            self._sync_index(before, self.get(mem_id))
            return True

    def restore(self, mem_id: int):
        with self._lock:
            self._refresh()
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

    def search(self, query: str, k: int = 5, min_similarity: float = 0.0, touch: bool = True,
               project: str | None = None, keyword: bool = True, diverse: float = 0.9) -> list[Memory]:
        """Hybrid search: meaning (FAISS) + exact keywords (FTS5).

        Returns up to k searchable memories ranked by similarity, plus bonuses for keyword
        matches, verified, recent and positively-rated items.
        - project: None = everything; otherwise that project plus general ("") memories.
        - A memory below min_similarity still counts if it contains an identifier from the
          query (code, IP, version...) or at least half (and at least 2) of its keywords.
        - diverse: skip a result whose meaning is this close to one already picked, so near-
          duplicates don't fill all k places (1.0 disables).
        """
        vec = self.embedder.embed([query or " "]).astype(np.float32)
        terms = _query_terms(query) if keyword else []
        with self._lock:
            self._refresh()
            if self.index.ntotal == 0:
                return []
            ok = lambda m: (searchable(m.kind, m.trust, m.archived)  # noqa: E731
                            and (project is None or m.project in (project, "")))
            cands: dict[int, Memory] = {}
            # Meaning candidates. With a project filter, widen the search until enough pass it.
            n = min(self.index.ntotal, max(k * 4, 20))
            while True:
                sims, ids = self.index.search(vec, n)
                hits = [(float(s), int(i)) for s, i in zip(sims[0], ids[0]) if i != -1]
                rows = self.get_many([i for _, i in hits if i not in cands])
                for sim, mid in hits:
                    m = rows.get(mid)
                    if m is not None and ok(m):
                        m.similarity = sim
                        cands[mid] = m
                enough = sum(m.similarity >= min_similarity for m in cands.values()) >= k
                if enough or project is None or n >= min(self.index.ntotal, 2000):
                    break
                n = min(self.index.ntotal, n * 4, 2000)
            # Keyword candidates the meaning search missed.
            if terms:
                # Filter in SQL, so wrong/archived rows and unapproved answers can't use up the 50 places.
                fts_q = " OR ".join(f'"{t}"' for t in terms)
                where, args = "", [fts_q]
                if project is not None:
                    where, args = " AND m.project IN (?, '')", [fts_q, project]
                kw_ids = [r[0] for r in self.db.execute(
                    "SELECT m.id FROM memories_fts f JOIN memories m ON m.id = f.rowid "
                    f"WHERE memories_fts MATCH ? AND {SEARCHABLE_SQL}{where} "  # its columns exist only in m
                    "ORDER BY f.rank LIMIT 50", args)]
                extra = self.get_many([i for i in kw_ids if i not in cands])
                for mid, m in extra.items():
                    if ok(m):
                        m.similarity = float(self._vector(mid) @ vec[0])
                        cands[mid] = m
            now = time.time()
            found = []
            for m in cands.values():
                words = _signature(m.content)
                matched = [t for t in terms if t in words]
                m.keyword = len(matched) / len(terms) if terms else 0.0
                ident = any(_is_identifier(t) for t in matched)
                if not (m.similarity >= min_similarity or ident or (len(matched) >= 2 and m.keyword >= 0.5)):
                    continue
                age_days = (now - max(m.created, m.last_seen or 0.0)) / 86400
                m.rank = (
                    m.similarity
                    + 0.15 * m.keyword
                    + (0.1 if ident else 0.0)
                    + (0.05 if m.trust == "verified" else 0.0)
                    + 0.03 * math.exp(-age_days / 30)  # newer wins on near-ties
                    # Feedback (explicit +/-3, guessed +/-1) moves a note by up to 0.06: enough to
                    # reorder close candidates, never enough to lift an unrelated note (< 0.5).
                    + 0.06 * math.tanh(m.feedback / 4)
                )
                found.append(m)
            found.sort(key=lambda m: m.rank, reverse=True)
            picked, picked_vecs, picked_words = [], [], []
            for m in found:
                if len(picked) == k:
                    break
                v = self._vector(m.id)
                w = _signature(m.content)
                # Skip only true near-copies: close in meaning AND in words. Notes close in meaning
                # but with different words may contradict each other ("Use tabs" / "Do not use
                # tabs"); hiding one could hide the newer fact (probe 2026-11-25).
                if diverse < 1.0 and any(float(v @ pv) >= diverse and _jaccard(w, pw) >= 0.8
                                         for pv, pw in zip(picked_vecs, picked_words)):
                    continue
                picked.append(m)
                picked_vecs.append(v)
                picked_words.append(w)
            if touch and picked:
                self.db.executemany(
                    "UPDATE memories SET times_used=times_used+1, last_used=? WHERE id=?",
                    [(now, m.id) for m in picked],
                )
                self.db.commit()
            return picked

    def projects(self) -> dict[str, int]:
        """Project name -> number of searchable memories ("" = general)."""
        with self._lock:
            return dict(self.db.execute(
                f"SELECT project, COUNT(*) FROM memories WHERE {SEARCHABLE_SQL} GROUP BY project").fetchall())

    def stats(self) -> dict:
        with self._lock:
            self._refresh()
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
