"""Central configuration. Override paths with the DORE_DATA environment variable."""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # project root (src/config.py)
# A source checkout keeps data/ in the repo; an installed package (pip, npx dore-memory) has no repo,
# so its data goes to ~/.dore-memory/data (or $DORE_HOME/data).
_HOME = Path(os.environ.get("DORE_HOME", Path.home() / ".dore-memory"))
_DEFAULT_DATA = ROOT / "data" if (ROOT / "pyproject.toml").exists() else _HOME / "data"
DATA = Path(os.environ.get("DORE_DATA", _DEFAULT_DATA))


@dataclass
class Config:
    data_dir: Path = DATA
    n_threads: int = 4  # memory-bound workload; extra hyperthreads add little
    embed_model: str = "BAAI/bge-small-en-v1.5"
    top_k: int = 5
    min_similarity: float = 0.5  # ignore memories less similar than this
    duplicate_threshold: float = 0.95  # cosine similarity above which a new item counts as a duplicate
    index_save_interval: float = 120.0  # seconds between index-file writes (rebuilt from SQLite after a crash)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "memory.db"

    @property
    def index_path(self) -> Path:
        return self.data_dir / "memory.faiss"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"
