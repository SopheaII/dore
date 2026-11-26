"""SQLite schema of the memory store: one row per memory, plus an FTS5 keyword index."""

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
    valid_to    REAL,
    key_vector  BLOB
);
CREATE INDEX IF NOT EXISTS idx_mem_active ON memories(archived, trust);

-- Raw memory (like the hippocampus): each sentence the user typed that no rule stored as a note.
-- Hidden (0 tokens); recalled only on a strong cue, re-judged when the rules change (`memory.episodes`).
CREATE TABLE IF NOT EXISTS episodes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT NOT NULL,
    project     TEXT NOT NULL DEFAULT '',   -- folder it was said in
    scope       TEXT,                       -- '' (about the user) or the project; set when consolidated
    told        INTEGER,                    -- 1 = tells something (not a request); set when consolidated
    session     TEXT NOT NULL DEFAULT '',
    created     REAL NOT NULL,
    vector      BLOB,                       -- set while idle (`consolidate`), never on the prompt path
    judged      TEXT NOT NULL DEFAULT '',   -- version of the learning rules it was last judged with
    note_id     INTEGER,                    -- the note it became when newer rules learned it
    times_seen  INTEGER NOT NULL DEFAULT 1,
    last_seen   REAL,
    recalled    INTEGER NOT NULL DEFAULT 0  -- times shown on a cue
);
CREATE INDEX IF NOT EXISTS idx_ep_text ON episodes(project, content);
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
