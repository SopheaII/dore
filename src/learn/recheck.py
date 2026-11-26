"""Re-judge stored notes with today's learning rules, like a person re-thinking old memories.

    python -m dore.learn.recheck            # dry run: list notes today's rules would not store
    python -m dore.learn.recheck --apply    # archive them (kept in SQLite, `MemoryStore.restore` brings one back)

Only the user's own statements are re-judged (`source="user"`, `kind="statement"`), never protected
notes, documents, lessons or Claude's notes. Nothing is deleted. A note passes when today's rules
still learn its words from it (`message_facts`), so rule improvements also clean what older rules
stored ("Now turn it on and show on status line too", pasted UI lines).
"""

from __future__ import annotations

import re
import sys

from dore.learn.statements import message_facts
from dore.memory import SEARCHABLE_SQL, MemoryStore


STANDING_NO = re.compile(r"^\s*(?:please\s+)?(?:don'?t|do not|never|no need|stop|avoid)\b", re.I)


def _kept(content: str) -> bool:
    found = message_facts(content)
    words = set(content.lower().split())
    # The same fact, possibly trimmed ("No, X" -> "X", a fact clause out of a request).
    return any(len(set(f.lower().split()) & words) >= max(2, len(set(f.lower().split())) * 0.6) for f in found)


def recheck(store: MemoryStore, apply: bool = False) -> list[tuple[int, str]]:
    """Notes today's rules would not learn; archived when `apply`. Returns (id, content)."""
    rows = store.db.execute(
        f"SELECT id, content FROM memories WHERE {SEARCHABLE_SQL} AND source='user' AND kind='statement' "
        "AND protected=0 AND replaced_by IS NULL ORDER BY id").fetchall()
    # A standing "don't / never / no need" instruction may be a lasting rule even when today's rules
    # read it as a request ("Don't run the slow e2e suite, just use the unit tests"): never archived here.
    out = [(i, c) for i, c in rows if not _kept(c) and not STANDING_NO.match(c)]
    if apply:
        for i, _ in out:
            store.archive(i)
        store.save(force=True)
    return out


def main(argv: list[str] | None = None):
    argv = sys.argv[1:] if argv is None else argv
    from dore.config import Config
    from dore.memory.embed import FastEmbedder
    cfg = Config()
    store = MemoryStore(cfg.db_path, cfg.index_path,
                        FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed")))
    apply = "--apply" in argv
    found = recheck(store, apply=apply)
    total = store.db.execute(f"SELECT count(*) FROM memories WHERE {SEARCHABLE_SQL}").fetchone()[0]
    print(f"{'archived' if apply else 'would archive'} {len(found)} notes ({total} searchable now):")
    for i, c in found:
        print(f"  #{i} {c[:120]}")
    if found and not apply:
        print("run with --apply to archive them (kept, reversible)")
    store.close()


if __name__ == "__main__":
    main()
