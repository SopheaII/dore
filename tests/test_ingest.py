from dore.ingest import chunk_text


def test_chunking_respects_size():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 100 for i in range(20))
    chunks = chunk_text(text, max_chars=1200, overlap=100)
    assert len(chunks) > 1
    assert all(len(c) <= 1200 for c in chunks)
    assert "Paragraph 19" in chunks[-1]
