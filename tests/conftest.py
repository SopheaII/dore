import pytest

from dore.assistant.agent import Agent
from dore.memory.embed import HashEmbedder
from dore.memory import MemoryStore


class FakeCore:
    """Scripted replies; records the prompts it receives. Counts ~1 token per word."""

    def __init__(self, replies, n_ctx=4096):
        self.replies = list(replies)
        self.prompts = []
        self.n_ctx = n_ctx

    def count_tokens(self, text):
        return len(text.split())

    def chat(self, messages, max_tokens=512, temperature=0.3):
        used = sum(self.count_tokens(m["content"]) for m in messages)
        assert used + max_tokens <= self.n_ctx, f"prompt overflow: {used} + {max_tokens} > {self.n_ctx}"
        self.prompts.append(messages)
        return self.replies.pop(0)


@pytest.fixture
def make(tmp_path):
    def _make(replies, n_ctx=4096, **kw):
        store = MemoryStore(tmp_path / "m.db", tmp_path / "m.faiss", HashEmbedder())
        return Agent(core=FakeCore(replies, n_ctx), memory=store, min_similarity=0.0, n_ctx=n_ctx, **kw)
    return _make
