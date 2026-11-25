"""dore: a local AI that keeps learning from everyday use.

Layers (each uses only the ones above it):
    config        paths and settings
    memory/       fast memory: records, search, replace rules (no model)
    learn/        what to learn from a message (rules, no model)
    assistant/    local LLM chat: core model, agent, code/maths checkers
    integrations/ Claude Code hooks and helper, MCP server, bridge for other agents
    apps/         command-line and browser chat
    eval/         benchmarks and the real-model self-test

The public names below load on first use, so `dore-hook` (standard library only) stays fast.
"""

_API = {"Config": "dore.config", "MemoryStore": "dore.memory", "Memory": "dore.memory",
        "FastEmbedder": "dore.memory", "HashEmbedder": "dore.memory", "Agent": "dore.assistant.agent"}

__all__ = list(_API)


def __getattr__(name: str):
    if name in _API:
        import importlib
        return getattr(importlib.import_module(_API[name]), name)
    raise AttributeError(f"module 'dore' has no attribute {name!r}")
