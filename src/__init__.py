"""dore: local long-term memory for Claude Code and other coding agents, learned from everyday use.

Layers (each uses only the ones above it):
    config        paths and settings
    memory/       fast memory: records, search, replace rules (no model)
    learn/        what to learn from a message (rules, no model)
    integrations/ Claude Code hooks and helper, MCP server, bridge for other agents
    eval/         checks and benchmarks (no LLM)

The public names below load on first use, so `dore-hook` (standard library only) stays fast.
"""

_API = {"Config": "dore.config", "MemoryStore": "dore.memory", "Memory": "dore.memory",
        "FastEmbedder": "dore.memory", "HashEmbedder": "dore.memory"}

__all__ = list(_API)


def __getattr__(name: str):
    if name in _API:
        import importlib
        return getattr(importlib.import_module(_API[name]), name)
    raise AttributeError(f"module 'dore' has no attribute {name!r}")
