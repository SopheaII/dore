"""Layer 1, fast memory: every fact, lesson and correction as a record (SQLite) found by meaning
(FAISS) and keywords (FTS5). No language model here.

- types.py   the record (`Memory`), trust levels, which records search may return
- schema.py  SQLite tables and the keyword index
- rules.py   text rules: duplicates, same fact with one detail changed, which note replaces which
- store.py   `MemoryStore`: add, merge, replace, search, feedback, archive
- embed.py   embedding models; ingest.py: documents split into chunks
"""

from .embed import Embedder, FastEmbedder, HashEmbedder
from .rules import replaces, same_frame
from .store import MemoryStore
from .types import SEARCHABLE_SQL, TRUST_LEVELS, Memory, searchable

__all__ = ["Embedder", "FastEmbedder", "HashEmbedder", "Memory", "MemoryStore", "SEARCHABLE_SQL",
           "TRUST_LEVELS", "replaces", "same_frame", "searchable"]
