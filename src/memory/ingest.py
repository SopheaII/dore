"""Split documents into chunks and store them in fast memory."""

from __future__ import annotations

import re
from pathlib import Path

from .store import MemoryStore


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    """Split on paragraph boundaries into chunks of at most ~max_chars.

    Paragraphs longer than max_chars are split by sentences, then hard-wrapped.
    Consecutive chunks share `overlap` characters of context.
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    for p in paras:
        if len(p) <= max_chars:
            pieces.append(p)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", p)
        buf = ""
        for s in sentences:
            while len(s) > max_chars:  # very long sentence: hard wrap
                if buf:
                    pieces.append(buf)
                    buf = ""
                pieces.append(s[:max_chars])
                s = s[max_chars:]
            if len(buf) + len(s) + 1 > max_chars and buf:
                pieces.append(buf)
                buf = s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            pieces.append(buf)

    chunks: list[str] = []
    buf = ""
    for piece in pieces:
        if buf and len(buf) + len(piece) + 2 > max_chars:
            chunks.append(buf)
            tail = buf[-overlap:] if overlap else ""
            buf = f"{tail}\n\n{piece}" if tail else piece
            if len(buf) > max_chars:
                buf = piece
        else:
            buf = f"{buf}\n\n{piece}" if buf else piece
    if buf:
        chunks.append(buf)
    return chunks


def ingest_text(store: MemoryStore, text: str, source: str, trust: str = "unverified",
                kind: str = "document", project: str = "") -> list[int]:
    chunks = chunk_text(text)
    ids = store.add_many(chunks, kind=kind, source=source, trust=trust, project=project) if chunks else []
    store.save()
    return ids


def ingest_file(store: MemoryStore, path: str | Path, trust: str = "unverified", project: str = "") -> list[int]:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return ingest_text(store, text, source=f"file:{path.name}", trust=trust, project=project)
