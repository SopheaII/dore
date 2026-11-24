import pytest

from dore.embed import HashEmbedder
from dore.memory import MemoryStore


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "m.db", tmp_path / "m.faiss", HashEmbedder())
    yield s
    s.close()


def test_add_and_search(store):
    store.add("Phnom Penh is the capital of Cambodia", trust="verified")
    store.add("The hippocampus forms new episodic memories")
    hits = store.search("what is the capital of Cambodia", k=1)
    assert hits and "Phnom Penh" in hits[0].content
    assert store.get(hits[0].id).times_used == 1


def test_duplicate_merges_and_keeps_strongest_trust(store):
    a = store.add("The brain uses about 20 watts")
    b = store.add("The brain uses about 20 watts", trust="verified")
    assert a == b
    m = store.get(a)
    assert m.times_seen == 2 and m.trust == "verified"
    assert store.stats()["total"] == 1


def test_wrong_items_are_never_returned(store):
    mid = store.add("The capital of Cambodia is Siem Reap")
    store.mark_wrong(mid)
    assert all(h.id != mid for h in store.search("capital of Cambodia", k=5))
    assert store.get(mid).trust == "wrong"  # kept, not deleted


def test_archive_never_deletes_and_respects_protect(store):
    a = store.add("allergy to penicillin", protected=True)
    b = store.add("parked the car on level 3")
    assert store.archive(a) is False
    assert store.archive(b) is True
    assert store.get(b).archived
    assert all(h.id != b for h in store.search("car parked level", k=5))
    store.restore(b)
    assert any(h.id == b for h in store.search("car parked level", k=5))


def test_index_rebuilds_after_restart(tmp_path):
    s = MemoryStore(tmp_path / "m.db", tmp_path / "m.faiss", HashEmbedder())
    s.add("grid cells were discovered in 2005")
    wrong = s.add("place cells were discovered in 1999")
    s.mark_wrong(wrong)
    s.close()
    (tmp_path / "m.faiss").unlink()  # lose the index: must rebuild from SQLite
    s2 = MemoryStore(tmp_path / "m.db", tmp_path / "m.faiss", HashEmbedder())
    assert s2.index.ntotal == 1
    assert "2005" in s2.search("grid cells discovered", k=1)[0].content
    s2.close()


def test_verified_ranks_above_unverified_on_tie(store):
    store.duplicate_threshold = 1.01  # disable merging for this test
    u = store.add("synapse count is about 100 trillion")
    v = store.add("synapse count is about 100 trillion!", trust="verified")
    hits = store.search("synapse count", k=2)
    assert hits[0].id == v and hits[1].id == u


def test_add_many_batches_and_merges_duplicates(store):
    first = store.add("the hippocampus stores episodes", trust="verified")
    ids = store.add_many(["grid cells map space", "the hippocampus stores episodes",
                          "grid cells map space", "place cells fire in places"])
    assert ids[1] == first and ids[0] == ids[2] and len(set(ids)) == 3
    assert store.stats()["total"] == 3 and store.index.ntotal == 3
    assert store.get(ids[0]).times_seen == 2


def test_unapproved_answers_stay_out_of_index(store):
    fact = store.add("my cat is called Mochi", trust="verified")
    ans = store.add("Q: cat name\nA: Rex", kind="answer", source="model")
    assert store.index.ntotal == 1
    assert [h.id for h in store.search("cat name", k=5)] == [fact]
    store.set_trust(ans, "verified")  # /good
    assert store.index.ntotal == 2 and ans in [h.id for h in store.search("cat name", k=5)]


def test_index_file_written_only_when_due(tmp_path):
    s = MemoryStore(tmp_path / "m.db", tmp_path / "m.faiss", HashEmbedder(), index_save_interval=3600)
    s.add("first fact here")
    s.save()
    assert not (tmp_path / "m.faiss").exists()  # not due yet
    s.save(force=True)
    assert (tmp_path / "m.faiss").exists()
    s.close()


def test_stale_index_after_crash_is_rebuilt(tmp_path):
    s = MemoryStore(tmp_path / "m.db", tmp_path / "m.faiss", HashEmbedder(), index_save_interval=3600)
    a = s.add("alpha beta gamma")
    s.save(force=True)
    s.add("delta epsilon zeta")  # committed to SQLite, index file now stale
    s.archive(a)                  # same count as the saved file, different items
    s.db.commit()
    s.db.close()                  # "crash": no final index write
    s2 = MemoryStore(tmp_path / "m.db", tmp_path / "m.faiss", HashEmbedder())
    assert s2.index.ntotal == 1
    assert "delta" in s2.search("delta epsilon", k=1)[0].content
    assert s2.search("alpha beta gamma", k=5, min_similarity=0.5) == []
    s2.close()


def test_protect_unknown_id_raises(store):
    with pytest.raises(KeyError):
        store.protect(999)


def test_threads_can_share_the_store(store):
    import threading

    errors = []

    def writer(n):
        try:
            for i in range(30):
                store.add(f"t{n}x{i} alpha{n}y{i} beta{i}z{n}")
                store.search(f"alpha{n}y{i}", k=3)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and store.stats()["total"] == store.index.ntotal == 120


def test_different_numbers_are_never_merged(store):
    store.duplicate_threshold = 0.5  # even with a loose threshold
    a = store.add("The server IP is 10.0.0.5.", trust="verified")
    b = store.add("The server IP is 10.0.0.6.", trust="verified")
    c = store.add("the server ip is 10.0.0.5", trust="verified")  # same words: merged
    assert a != b and c == a and store.stats()["total"] == 2
