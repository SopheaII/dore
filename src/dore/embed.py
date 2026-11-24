"""Text embeddings. Vectors are L2-normalised so inner product == cosine similarity."""

from typing import Protocol

import numpy as np


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


def _normalise(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return v / norms


class FastEmbedder:
    """ONNX embedding model via fastembed (no PyTorch needed)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", cache_dir: str | None = None):
        from fastembed import TextEmbedding

        # Default cache is /tmp, which is wiped on reboot; keep it under data/ instead.
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self.dim = int(self._model.embedding_size) if hasattr(self._model, "embedding_size") else len(
            next(iter(self._model.embed(["dim probe"])))
        )

    def embed(self, texts: list[str]) -> np.ndarray:
        return _normalise(np.stack(list(self._model.embed(texts))))


class HashEmbedder:
    """Deterministic bag-of-words embedder for tests (no model download)."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        import hashlib

        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for word in t.lower().split():
                h = int(hashlib.md5(word.strip(".,!?;:\"'()").encode()).hexdigest(), 16)
                out[i, h % self.dim] += 1.0
        return _normalise(out)
