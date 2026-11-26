"""Fast memory: SQLite records plus a FAISS vector index. Nothing is hard-deleted; archived and wrong notes stay out of search."""

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
ARCHIVE_TRIES = 3

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

from .rules import _dup_key, _is_identifier, _jaccard, _query_terms, _signature, changes, embed_text, local_value, replaces
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
        if not hasattr(self, "key_index"):  # rebuild_index (above) already built it
            self.key_index = self._load_key_index()
        self._data_version = self.db.execute("PRAGMA data_version").fetchone()[0]

    def _migrate(self):
        """Bring an older memory.db up to date (adds columns/indexes; never removes data)."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(memories)")}
        if "project" not in cols:
            self.db.execute("ALTER TABLE memories ADD COLUMN project TEXT NOT NULL DEFAULT ''")
        for col, typ in (("last_seen", "REAL"), ("replaced_by", "INTEGER"), ("valid_to", "REAL"),
                         ("key_vector", "BLOB"), ("tries", "INTEGER NOT NULL DEFAULT 0"),
                         ("uses", "INTEGER NOT NULL DEFAULT 0"), ("said_in", "TEXT"),
                         ("rule", "INTEGER NOT NULL DEFAULT 0")):
            if col not in cols:
                self.db.execute(f"ALTER TABLE memories ADD COLUMN {col} {typ}")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_mem_rule ON memories(project) WHERE rule=1")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS reply_words (word TEXT PRIMARY KEY, n INTEGER NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS shadows (note_id INTEGER NOT NULL, project TEXT NOT NULL, "
                        "by_id INTEGER NOT NULL, PRIMARY KEY (note_id, project))")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_mem_project ON memories(project)")
        if "words_key" not in cols:  # same words in the same order (`rules._dup_key`), for exact repeats
            self.db.execute("ALTER TABLE memories ADD COLUMN words_key TEXT")
            for col in ("rule_when", "rule_not"):  # a rule's situation and forbidden words (`learn.judge`)
                if col not in cols:
                    self.db.execute(f"ALTER TABLE memories ADD COLUMN {col} TEXT")
            self.db.executemany("UPDATE memories SET words_key=? WHERE id=?",
                                [(" ".join(_dup_key(c)), i) for i, c in self.db.execute(
                                    "SELECT id, content FROM memories").fetchall()])
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_mem_words ON memories(project, words_key)")
        # Notes the word rules made at once while the Haiku learner was on; settled when Haiku judged their sentences.
        self.db.execute("CREATE TABLE IF NOT EXISTS provisional (note_id INTEGER PRIMARY KEY, episodes TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS note_sessions (note_id INTEGER NOT NULL, session TEXT NOT NULL, "
                        "PRIMARY KEY (note_id, session))")
        had_fts = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='memories_fts'").fetchone() is not None
        self.db.executescript(FTS_SCHEMA)
        if not had_fts:
            self.db.execute("INSERT INTO memories_fts(memories_fts) VALUES ('rebuild')")
        self.db.commit()

    # ---------- index ----------
    def _new_index(self):
        return faiss.IndexIDMap2(faiss.IndexFlatIP(self.dim))

    def _build_key_index(self):
        """Topic-key vectors of the searchable notes that have one (`add_many(keys=...)`)."""
        idx = self._new_index()
        cur = self.db.execute(f"SELECT id, key_vector FROM memories WHERE {SEARCHABLE_SQL} AND length(key_vector) > 0")
        while rows := cur.fetchmany(50_000):
            idx.add_with_ids(np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), self.dim),
                             np.array([r[0] for r in rows], dtype=np.int64))
        return idx

    def _key_path(self) -> Path | None:
        return self.index_path.with_name(self.index_path.stem + ".keys" + self.index_path.suffix) if self.index_path else None

    def _load_key_index(self):
        """The saved key index if it holds exactly the searchable notes with a key; else rebuilt from
        SQLite (a cold hook at 100k notes would otherwise read ~150 MB of key vectors per prompt)."""
        p = self._key_path()
        if p and p.exists():
            try:
                idx = faiss.read_index(str(p))
            except RuntimeError:
                idx = None
            want = np.array([r[0] for r in self.db.execute(
                f"SELECT id FROM memories WHERE {SEARCHABLE_SQL} AND length(key_vector) > 0 ORDER BY id")], dtype=np.int64)
            if idx is not None and idx.d == self.dim and np.array_equal(np.sort(faiss.vector_to_array(idx.id_map)), want):
                return idx
        self._dirty = True
        return self._build_key_index()

    def _key_add(self, ids: list[int]):
        if not ids:
            return
        rows = self.db.execute(f"SELECT id, key_vector FROM memories WHERE length(key_vector) > 0 AND id IN "
                               f"({','.join('?' * len(ids))})", [int(i) for i in ids]).fetchall()
        if rows:
            self.key_index.add_with_ids(
                np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), self.dim),
                np.array([r[0] for r in rows], dtype=np.int64))
            self._dirty = True

    def _key_vector(self, mem_id: int) -> np.ndarray | None:
        blob = self.db.execute("SELECT key_vector FROM memories WHERE id=?", (mem_id,)).fetchone()[0]
        return np.frombuffer(blob, dtype=np.float32) if blob else None  # b"": checked, no key

    def missing_keys(self, limit: int = 500) -> list[tuple[int, str]]:
        """Searchable statements saved before topic keys existed: (id, content)."""
        with self._lock:
            return self.db.execute(f"SELECT id, content FROM memories WHERE {SEARCHABLE_SQL} AND kind='statement' "
                                   "AND key_vector IS NULL ORDER BY id LIMIT ?", (limit,)).fetchall()

    def set_keys(self, pairs: list[tuple[int, str | None]]):
        """Store topic keys for existing notes (None = checked, no key: stored as b"")."""
        with self._lock:
            have = [(i, k) for i, k in pairs if k]
            vecs = self.embedder.embed([embed_text(k) for _, k in have]).astype(np.float32) if have else []
            blobs = {i: v.tobytes() for (i, _), v in zip(have, vecs)}
            self.db.executemany("UPDATE memories SET key_vector=? WHERE id=?",
                                [(blobs.get(i, b""), i) for i, _ in pairs])
            self.db.commit()
            ids = [i for i in blobs if i not in set(faiss.vector_to_array(self.key_index.id_map).tolist())]
            self._key_add([i for i in ids if self.db.execute(
                f"SELECT 1 FROM memories WHERE id=? AND {SEARCHABLE_SQL}", (i,)).fetchone()])

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
            self.key_index.remove_ids(extra.astype(np.int64))
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
            self.key_index = self._build_key_index()
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
                ktmp = self.index_path.with_suffix(f".{os.getpid()}.keys.tmp")
                faiss.write_index(self.key_index, str(ktmp))
                ktmp.replace(self._key_path())
                self._dirty = False
                self._last_index_write = time.monotonic()

    def _index_add(self, vecs: np.ndarray, ids: list[int]):
        if ids:
            self.index.add_with_ids(np.ascontiguousarray(vecs, dtype=np.float32), np.array(ids, dtype=np.int64))
            if getattr(self, "key_index", None) is not None:  # not yet built while the store opens
                self._key_add(ids)
            self._dirty = True

    def _index_drop(self, mem_id: int):
        self.index.remove_ids(np.array([mem_id], dtype=np.int64))
        self.key_index.remove_ids(np.array([mem_id], dtype=np.int64))
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
            protected: bool = False, project: str = "", supersede: bool = False, key: str | None = None,
            created: float | None = None) -> int:
        """Store one memory; see `add_many`. Returns its id (or the id it merged into)."""
        return self.add_many([content], kind=kind, source=source, trust=trust, protected=protected,
                             project=project, supersede=supersede, keys=None if key is None else [key],
                             created=created)[0]

    def add_many(self, contents: list[str], kind: str = "fact", source: str = "user",
                 trust: str = "unverified", protected: bool = False, project: str = "",
                 supersede: bool = False, keys: list[str | None] | None = None,
                 created: float | None = None) -> list[int]:
        """Store several memories with the same metadata in one batch.

        A near-duplicate of a searchable item (in the store or earlier in this batch)
        is merged into it instead of stored again. Returns one id per input, in order.
        `project` scopes the memory ("" = general, visible from every project).
        supersede: each new item replaces older notes it updates (`replaces`), in input
        order, so "I live in X. ... I live in Y." ends with Y. Ids in `last_replaced`.
        keys: per note, an optional topic-key text (`learn.grammar.topic_key`) embedded as a second
        vector; search scores a note by the closer of its two vectors. Used only for search.
        created: when it was said, for a note learned later from raw memory (`memory.episodes`); default now.
        An older date never replaces a newer note, and a newer note it would have updated replaces it.
        """
        if trust not in TRUST_LEVELS:
            raise ValueError(f"trust must be one of {TRUST_LEVELS}")
        texts = [c.strip() for c in contents]
        if any(not t for t in texts):
            raise ValueError("empty memory")
        given = keys is not None  # keys checked by the caller: a None key is stored as b"" (no key)
        keys = list(keys) if given else [None] * len(texts)
        if len(keys) != len(texts):
            raise ValueError("one key per memory")
        out: list[int] = []
        with self._lock:
            self._refresh()
            self.last_replaced = []
            first_new = (self.db.execute("SELECT MAX(id) FROM memories").fetchone()[0] or 0) + 1
            for start in range(0, len(texts), EMBED_BATCH):
                out += self._add_batch(texts[start:start + EMBED_BATCH], kind, source, trust, protected,
                                       project, keys[start:start + EMBED_BATCH], given, created)
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
            # A note dated before newer notes (learned later from raw memory): a newer note that updates it
            # wins ("newer wins"), the same rules the other way round.
            if (m is not None and m.created > new.created and new.project in (m.project, "")
                    and m.kind in ("fact", "statement", "correction") and not new.protected
                    and (m.trust == "verified" or new.trust != "verified")
                    and (replaces(new.content, m.content)
                         or (sim >= CHANGE_SIMILARITY and changes(new.content, m.content)))):
                self.db.execute("UPDATE memories SET replaced_by=?, valid_to=? WHERE id=?", (i, m.created, new_id))
                self._sync_index(new, self.get(new_id))
                return done
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
            if m.project == "" and new.project:
                origin = self.db.execute("SELECT said_in FROM memories WHERE id=?", (i,)).fetchone()[0]
                if local_value(new.content) or (origin is not None and origin != new.project):
                    self.db.execute("INSERT OR REPLACE INTO shadows (note_id, project, by_id) VALUES (?,?,?)",
                                    (i, new.project, new_id))
                    continue
                self.db.execute("UPDATE memories SET project='' WHERE id=?", (new_id,))
                new = self.get(new_id)
            self.db.execute("UPDATE OR IGNORE shadows SET note_id=? WHERE note_id=?", (new_id, i))
            self.db.execute("UPDATE memories SET replaced_by=?, valid_to=? WHERE id=?", (new_id, time.time(), i))
            self._sync_index(m, self.get(i))
            done.append(i)
        return done

    def _add_batch(self, texts, kind, source, trust, protected, project, keys, keys_given=False,
                   created: float | None = None) -> list[int]:
        vecs = self.embedder.embed([embed_text(t) for t in texts]).astype(np.float32)
        kpos = [i for i, k in enumerate(keys) if k]
        kvecs = dict(zip(kpos, self.embedder.embed([embed_text(keys[i]) for i in kpos]).astype(np.float32))) if kpos else {}
        indexed = searchable(kind, trust)
        # Same words in the same order, in the same project = the same note said again (case and punctuation
        # aside). Items that can't be searched (wrong, unapproved answers) are never merged: merging an answer
        # into a user's fact would let /correct mark that fact wrong. A threshold above 1 turns merging off.
        merge = indexed and self.duplicate_threshold <= 1.0
        sigs = [" ".join(_dup_key(t)) for t in texts]
        now = created or time.time()
        ids: list[int] = []
        new_rows: list[int] = []  # positions in this batch that were inserted and go in the index
        new_ids: list[int] = []
        for i, (text, vec) in enumerate(zip(texts, vecs)):
            dup = None
            if merge:
                dup = self.same_words(text, project)
                if dup is None:
                    dup = next((new_ids[j] for j, r in enumerate(new_rows) if sigs[r] == sigs[i]), None)
            if dup is not None:
                self._merge(dup, text, source, trust, protected, now)
                ids.append(dup)
                continue
            back = self._tried_out(sigs[i], project) if indexed and source == "user" else None
            if back is not None:  # said again after a trial archived it: the repeat proves it
                before = self.get(back)
                self.db.execute("UPDATE memories SET archived=0 WHERE id=?", (back,))
                self._merge(back, text, source, trust, protected, now)
                self._sync_index(before, self.get(back))
                ids.append(back)
                continue
            cur = self.db.execute(
                "INSERT INTO memories (content, kind, source, trust, protected, created, vector, project, key_vector, "
                "rule, words_key) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (text, kind, source, trust, int(protected), now, vec.tobytes(), project,
                 kvecs[i].tobytes() if i in kvecs else (b"" if keys_given else None), 0, sigs[i]),
            )
            ids.append(cur.lastrowid)
            if indexed:
                new_rows.append(i)
                new_ids.append(cur.lastrowid)
        self._index_add(vecs[new_rows], new_ids)
        return ids

    def _tried_out(self, sig: str, project: str) -> int | None:
        """A note with the same words that a trial archived (`mark_tried`), in this project."""
        row = self.db.execute("SELECT id FROM memories WHERE archived=1 AND project=? AND words_key=? AND uses=0 "
                              "AND tries>=? LIMIT 1", (project, sig, ARCHIVE_TRIES)).fetchone()
        return row[0] if row else None

    def same_words(self, text: str, project: str) -> int | None:
        """A searchable note of this project (or general, for project "") with the same words in the same order."""
        row = self.db.execute(f"SELECT id FROM memories WHERE project=? AND words_key=? AND {SEARCHABLE_SQL} "
                              "ORDER BY id LIMIT 1", (project, " ".join(_dup_key(text)))).fetchone()
        return row[0] if row else None

    def said_again(self, mem_id: int, when: float, session: str, first: bool = False) -> bool:
        """The user said this note (again) in `session`. A repeat counts once per session: said twice in one chat is
        the same moment. `first`: the note was just made from it. Returns True when it counted."""
        with self._lock:
            new = self.db.execute("INSERT OR IGNORE INTO note_sessions (note_id, session) VALUES (?, ?)",
                                  (mem_id, session or "")).rowcount == 1
            if new and not first:
                self.db.execute("UPDATE memories SET times_seen=times_seen+1, last_seen=MAX(coalesce(last_seen, 0), ?) "
                                "WHERE id=?", (when, mem_id))
            self.db.commit()
        return new and not first

    def replace(self, old: int, new: int, project_only: str | None = None):
        """`new` updates `old` (kept, dated, no longer searched). `project_only`: the update holds in that project
        only, so a general note is hidden there instead of replaced. A protected note is never replaced."""
        with self._lock:
            m = self.get(old)
            if m.protected:
                return
            if project_only and m.project == "":
                self.db.execute("INSERT OR REPLACE INTO shadows (note_id, project, by_id) VALUES (?,?,?)",
                                (old, project_only, new))
            else:
                self.db.execute("UPDATE OR IGNORE shadows SET note_id=? WHERE note_id=?", (new, old))
                self.db.execute("UPDATE memories SET replaced_by=?, valid_to=? WHERE id=?", (new, time.time(), old))
                self._sync_index(m, self.get(old))
            self.db.commit()

    def is_rule(self, mem_id: int) -> bool:
        row = self.db.execute("SELECT rule FROM memories WHERE id=?", (mem_id,)).fetchone()
        return bool(row and row[0])

    def set_rule_words(self, mem_id: int, when: list[str], forbid: list[str]):
        """A rule's situation words and the words that would break it (practice, `hooks.practised`)."""
        import json
        with self._lock:
            self.db.execute("UPDATE memories SET rule_when=?, rule_not=? WHERE id=?",
                            (json.dumps(when), json.dumps(forbid), mem_id))
            self.db.commit()

    def _merge(self, dup_id: int, text: str, source: str, trust: str, protected: bool, now: float):
        """Same fact stated again. Keep the stronger trust level and the first date (`created`);
        `last_seen` records the repeat (recency uses it). If the repeat is what makes the note
        verified, its source changes too, so an agent's note the user confirms says `user`."""
        cur_trust = self.db.execute("SELECT trust FROM memories WHERE id=?", (dup_id,)).fetchone()[0]
        new_trust = "verified" if "verified" in (cur_trust, trust) else cur_trust
        self.db.execute(
            "UPDATE memories SET times_seen=times_seen+1, trust=?, protected=MAX(protected, ?), "
            "last_seen=MAX(coalesce(last_seen, 0), ?) WHERE id=?", (new_trust, int(protected), now, dup_id))
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

    def mark_rules(self, flags: dict[int, bool]):
        """Mark notes as instructions (`memories.rule`, read by `rule_notes`); decided by the caller (the hook uses
        the sentence's form, `grammar.instruction`)."""
        if flags:
            with self._lock:
                self.db.executemany("UPDATE memories SET rule=? WHERE id=?", [(int(v), i) for i, v in flags.items()])
                self.db.commit()

    def meta(self, key: str, value: str | None = None) -> str | None:
        """Read (or, with `value`, write) a small setting kept in the memory file."""
        with self._lock:
            if value is not None:
                self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
                self.db.commit()
                return value
            row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def rule_notes(self, project: str) -> list[Memory]:
        """Searchable verified rule notes of this project and general ones: an indexed lookup of rule notes only
        (the rest of memory is not read)."""
        with self._lock:
            self._refresh()
            rows = self.db.execute(
                f"SELECT {_COLS} FROM memories WHERE rule=1 AND project IN (?, '') AND trust='verified' "
                f"AND {SEARCHABLE_SQL}", (project,)).fetchall()
        return [_row(r) for r in rows]

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
        self.last_query_vector = vec[0]  # reused by raw-memory recall (`memory.episodes`): no second embedding
        terms = _query_terms(query) if keyword else []
        with self._lock:
            self._refresh()
            if self.index.ntotal == 0:
                return []
            hidden = {r[0] for r in self.db.execute("SELECT note_id FROM shadows WHERE project=?", (project,))} \
                if project else set()
            ok = lambda m: (searchable(m.kind, m.trust, m.archived)  # noqa: E731
                            and (project is None or m.project in (project, "")) and m.id not in hidden)
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
            # Topic-key candidates ("answer, emoji: I prefer short answers..." for "How long should
            # your answers be?"): a note scores by the closer of its two vectors.
            if self.key_index.ntotal:
                ksims, kids = self.key_index.search(vec, min(self.key_index.ntotal, n))
                khits = {int(i): float(s) for s, i in zip(ksims[0], kids[0]) if i != -1}
                rows = self.get_many([i for i in khits if i not in cands])
                for mid, m in rows.items():
                    if ok(m):
                        m.similarity = float(self._vector(mid) @ vec[0])
                        cands[mid] = m
                for mid, m in cands.items():
                    ks = khits.get(mid)
                    if ks is None and (kv := self._key_vector(mid)) is not None:
                        ks = float(kv @ vec[0])
                    if ks is not None and ks > m.similarity:
                        m.similarity = ks
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
                        kv = self._key_vector(mid)
                        m.similarity = max(float(self._vector(mid) @ vec[0]),
                                           float(kv @ vec[0]) if kv is not None else -1.0)
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
                # Found is not used: `last_used` is only Claude using a note (it gives strength, `memory.activation`).
                self.db.executemany("UPDATE memories SET times_used=times_used+1 WHERE id=?", [(m.id,) for m in picked])
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

    def count_reply(self, words: set[str]):
        """Count one of Claude's replies in the word statistics (`reply_words`)."""
        with self._lock:
            self.db.executemany("INSERT INTO reply_words (word, n) VALUES (?, 1) "
                                "ON CONFLICT(word) DO UPDATE SET n = n + 1", [(w,) for w in (*words, "")])
            self.db.commit()

    def reply_counts(self, words: set[str]) -> tuple[int, dict[str, int]]:
        """(replies counted, {word: replies containing it}) for these words."""
        ws = list(words) + [""]
        with self._lock:
            rows = dict(self.db.execute(
                f"SELECT word, n FROM reply_words WHERE word IN ({','.join('?' * len(ws))})", ws).fetchall())
        return rows.pop("", 0), rows

    def mark_tried(self, ids: list[int], used: set[int]) -> list[int]:
        """Count a try for shown notes; unused after `ARCHIVE_TRIES` -> archived. Returns archived ids."""
        from .types import on_trial
        gone = []
        with self._lock:
            for i in ids:
                self.db.execute("UPDATE memories SET tries = tries + 1, uses = uses + ?, "
                                "last_used = CASE WHEN ? THEN ? ELSE last_used END WHERE id=?",
                                (int(i in used), int(i in used), time.time(), i))
            self.db.commit()
            for i, m in self.get_many(ids).items():
                if (on_trial(m) or m.kind == "requirement") and m.uses == 0 and m.tries >= ARCHIVE_TRIES \
                        and self.archive(i):
                    gone.append(i)
        return gone

    def rename_project(self, old: list[str], new: str) -> int:
        """Move notes under older project keys to `new` (never general ones). Returns the count moved."""
        old = [o for o in old if o and o != new]
        if not old:
            return 0
        q = ",".join("?" * len(old))
        with self._lock:
            n = self.db.execute(f"UPDATE memories SET project=? WHERE project IN ({q})", (new, *old)).rowcount
            self.db.execute(f"UPDATE episodes SET project=? WHERE project IN ({q})", (new, *old))
            self.db.execute(f"UPDATE episodes SET scope=? WHERE scope IN ({q})", (new, *old))
            self.db.commit()
        return n

    def mark_said_in(self, ids: list[int], project: str):
        """Record the project the user said these notes in (a general note keeps where it came from)."""
        if ids:
            with self._lock:
                self.db.execute(f"UPDATE memories SET said_in=? WHERE said_in IS NULL AND id IN "
                                f"({','.join('?' * len(ids))})", (project, *ids))
                self.db.commit()

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
