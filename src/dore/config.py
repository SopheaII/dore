"""Central configuration. Override paths with the DORE_DATA environment variable."""

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # project root (src/dore/config.py)
DATA = Path(os.environ.get("DORE_DATA", ROOT / "data"))


@dataclass
class Config:
    data_dir: Path = DATA
    model_path: Path = field(default_factory=lambda: DATA / "models" / "Llama-3.2-1B-Instruct-Q4_K_M.gguf")
    lora_path: Path | None = None
    n_ctx: int = 4096
    n_threads: int = 4  # memory-bound workload; extra hyperthreads add little
    embed_model: str = "BAAI/bge-small-en-v1.5"
    top_k: int = 5
    min_similarity: float = 0.5  # ignore memories less similar than this
    duplicate_threshold: float = 0.95  # cosine similarity above which a new item counts as a duplicate
    index_save_interval: float = 120.0  # seconds between index-file writes (rebuilt from SQLite after a crash)
    max_auto_statements: int = 20  # longer chat messages are stored as a document, not as facts
    max_fix_rounds: int = 3
    code_timeout_s: float = 10.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "memory.db"

    @property
    def index_path(self) -> Path:
        return self.data_dir / "memory.faiss"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def adapters_dir(self) -> Path:
        return self.data_dir / "adapters"
