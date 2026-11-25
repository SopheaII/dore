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
import sqlite3
import threading
import time
from pathlib import Path

import faiss
import numpy as np

from .embed import Embedder
HUB_WEIGHT = 0.7
CHANGE_SIMILARITY = 0.6  # a reworded update ("We switched the cache to Redis") must be this close to the old note
# Generic questions a developer asks about any project (not the eval's questions): a note close to
# many of them matches every prompt a little and is pushed down (`search`, hub correction).
HUB_QUESTIONS = (
    "How do I set this up?", "What version are we on?", "Where is the config file?", "Which library handles dates?",
    "How do I start the app locally?", "What is the API base URL?", "Who owns this service?", "Where are the logs?",
    "How do I build for production?", "What environment variables are needed?", "Which branch should I use?",
    "How is the data backed up?", "What framework is the frontend?", "Where are images stored?",
    "How do we handle errors?", "What is the release process?", "Which region are we in?", "How do I add a migration?",
    "What linter do we use?", "How are secrets managed?", "What does the CI run?", "How do I reset my password?",
    "Which payment provider do we use?", "What is the timeout?", "How many users do we have?")

from .rules import _dup_key, _is_identifier, _jaccard, _query_terms, _signature, changes, embed_text, replaces
from .schema import FTS_SCHEMA, SCHEMA
from .types import _COLS, SEARCHABLE_SQL, TRUST_LEVELS, Memory, _row, searchable

EMBED_BATCH = 256

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
        # Faster commits, readers don't block the writer. Switching a NEW file to WAL ignores the
        # timeout above and fails at once if another process does the same (the hook and its
        # helper starting together on a fresh install: the first fact was lost, 2026-11-25).
        for attempt in range(50):
            try:
                self.db.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError:
                if attempt == 49:
                    raise
                time.sleep(0.1)
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
        Same project or an older general note; never protected notes; an unverified note can't replace
        a verified one. Must be called with the lock held."""
        new = self.get(new_id)
        if not searchable(new.kind, new.trust, new.archived) or not self.index.ntotal:
            return []
        sims, ids = self.index.search(self._vector(new_id)[None, :], min(self.index.ntotal, 20))
        hits = [(float(s), int(i)) for s, i in zip(sims[0], ids[0]) if i not in (-1, new_id) and s >= min_similarity]
        rows = self.get_many([i for _, i in hits])
        done = []
        for sim, i in hits:
            m = rows.get(i)
            # Only older notes; in one batch (same time) only earlier ones, or two notes saved
            # together replaced each other and both left search.
            # Same project, or an older general ("") note: "Samnang works on the infra team" was
            # saved as general and its project-scoped update never replaced it (long-conversation
            # test 2026-11-25). A general note never replaces another project's own note.
            if (m is None or m.project not in (new.project, "")
                    or m.protected or m.created > new.created
                    or (m.created == new.created and m.id > new.id)
                    or m.kind not in ("fact", "statement", "correction")
                    or (m.trust == "verified" and new.trust != "verified")
                    or not (replaces(m.content, new.content)
                            or (sim >= CHANGE_SIMILARITY and changes(m.content, new.content)))):
                continue
            self.db.execute("UPDATE memories SET replaced_by=?, valid_to=? WHERE id=?", (new_id, time.time(), i))
            self._sync_index(m, self.get(i))
            done.append(i)
        return done

    def _add_batch(self, texts, kind, source, trust, protected, project) -> list[int]:
        vecs = self.embedder.embed([embed_text(t) for t in texts]).astype(np.float32)
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
            # Hub correction: a generic note ("Our servers are on Ubuntu 22.04") is close to almost
            # every question and crowded out the note that answers it. Each candidate loses
            # HUB_WEIGHT x how close it is to generic developer questions, relative to the other
            # candidates (scale kept, so thresholds on raw similarity are unchanged). Scale test
            # (12 projects, 12 weeks): right note first 67 -> 76 of 100.
            if len(found) > 1:
                hubs = np.sort(np.stack([self._vector(m.id) for m in found]) @ self._hub_bank().T, 1)[:, -5:].mean(1)
                centre = float(np.median(hubs))
                for m, h in zip(found, hubs):
                    m.focus = m.similarity - HUB_WEIGHT * (float(h) - centre)
                    m.rank -= HUB_WEIGHT * (float(h) - centre)
            else:
                for m in found:
                    m.focus = m.similarity
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

    def _hub_bank(self) -> np.ndarray:
        """Vectors of generic developer questions (embedded once per store)."""
        if getattr(self, "_hub_vecs", None) is None:
            try:
                self._hub_vecs = self.embedder.embed(list(HUB_QUESTIONS)).astype(np.float32)
            except Exception:  # an embedder that can't embed them (tests): no correction
                self._hub_vecs = np.zeros((1, self.embedder.dim), dtype=np.float32)
        return self._hub_vecs

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
