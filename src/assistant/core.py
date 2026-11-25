"""Stable core: a llama.cpp model plus an optional LoRA adapter.

Swapping adapters loads a second instance and then switches over, because
llama.cpp cannot load a new adapter file into a running model.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterator, Protocol


class ChatModel(Protocol):
    """What the agent needs from a model. `n_ctx` and `count_tokens` are optional:
    without them the agent estimates ~3 characters per token."""

    def chat(self, messages: list[dict], max_tokens: int = 512, temperature: float = 0.3) -> str: ...


class Core:
    def __init__(self, model_path: Path | str, lora_path: Path | str | None = None,
                 n_ctx: int = 4096, n_threads: int = 4):
        self.model_path = Path(model_path)
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self._lock = threading.Lock()
        self.lora_path = Path(lora_path) if lora_path else None
        self._llm = self._load(self.lora_path)

    def _load(self, lora_path: Path | None):
        from llama_cpp import Llama

        if not self.model_path.exists():
            raise FileNotFoundError(f"Model not found: {self.model_path}")
        return Llama(
            model_path=str(self.model_path),
            lora_path=str(lora_path) if lora_path else None,
            n_ctx=self.n_ctx, n_threads=self.n_threads, verbose=False,
        )

    def count_tokens(self, text: str) -> int:
        return len(self._llm.tokenize(text.encode("utf-8"), add_bos=False, special=False))

    def chat(self, messages: list[dict], max_tokens: int = 512, temperature: float = 0.3) -> str:
        with self._lock:
            out = self._llm.create_chat_completion(messages=messages, max_tokens=max_tokens,
                                                   temperature=temperature)
        return out["choices"][0]["message"]["content"] or ""

    def stream(self, messages: list[dict], max_tokens: int = 512, temperature: float = 0.3) -> Iterator[str]:
        with self._lock:
            for part in self._llm.create_chat_completion(messages=messages, max_tokens=max_tokens,
                                                         temperature=temperature, stream=True):
                delta = part["choices"][0]["delta"].get("content")
                if delta:
                    yield delta

    def swap_adapter(self, lora_path: Path | str | None):
        """Load the new adapter in a fresh instance, then switch. The old one keeps
        answering until the switch, and is kept if loading fails."""
        new_path = Path(lora_path) if lora_path else None
        new_llm = self._load(new_path)
        with self._lock:
            old, self._llm, self.lora_path = self._llm, new_llm, new_path
        del old
