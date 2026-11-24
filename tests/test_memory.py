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
    hits = store.search("synapse count", k=2, diverse=1.0)
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


def test_projects_are_separate_but_general_facts_are_shared(store):
    store.duplicate_threshold = 1.01
    a = store.add("the api port is 8080", trust="verified", project="shop")
    b = store.add("the api port is 9090", trust="verified", project="blog")
    g = store.add("my editor is neovim with api plugins", trust="verified")
    ids = [m.id for m in store.search("api port", k=5, project="shop")]
    assert a in ids and b not in ids and g in ids
    assert {m.id for m in store.search("api port", k=5)} >= {a, b}  # no project: everything
    assert store.projects() == {"shop": 1, "blog": 1, "": 1}


def test_same_text_in_two_projects_is_not_merged(store):
    a = store.add("deploy with make release", project="shop")
    b = store.add("deploy with make release", project="blog")
    assert a != b


def test_keyword_search_finds_exact_identifiers(store):
    code = store.add("The emergency shutdown code is RED-7731.", trust="verified")
    for i in range(30):
        store.add(f"routine maintenance note number {i} about pumps and valves")
    hits = store.search("RED-7731", k=3, min_similarity=0.99)  # meaning alone would never pass 0.99
    assert hits and hits[0].id == code and hits[0].keyword == 1.0


def test_keyword_match_on_common_word_alone_is_not_enough(store):
    store.add("the server room is cold")
    assert store.search("server", k=3, min_similarity=0.99) == []


def test_near_duplicate_results_are_skipped(store):
    store.duplicate_threshold = 1.01
    store.add("the brain uses about 20 watts")
    store.add("the brain uses about 20 watts!")
    store.add("neurons fire electrical spikes")
    hits = store.search("brain watts", k=2)
    assert len({h.content.rstrip("!") for h in hits}) == 2


def test_old_database_is_migrated(tmp_path):
    import sqlite3

    import numpy as np
    db = sqlite3.connect(tmp_path / "old.db")
    db.execute("""CREATE TABLE memories (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'fact', source TEXT NOT NULL DEFAULT 'user', trust TEXT NOT NULL DEFAULT
        'unverified', protected INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0, created REAL
        NOT NULL, last_used REAL, times_used INTEGER NOT NULL DEFAULT 0, times_seen INTEGER NOT NULL DEFAULT 1,
        feedback INTEGER NOT NULL DEFAULT 0, vector BLOB NOT NULL)""")
    vec = HashEmbedder().embed(["the wifi code is lotus-42"])[0].astype(np.float32).tobytes()
    db.execute("INSERT INTO memories (content, trust, created, vector) VALUES (?, 'verified', 0, ?)",
               ("the wifi code is lotus-42", vec))
    db.commit()
    db.close()
    s = MemoryStore(tmp_path / "old.db", None, HashEmbedder())
    hits = s.search("lotus-42", k=1, min_similarity=0.99)
    assert hits and hits[0].project == ""
    s.close()


def test_two_processes_sharing_one_database_see_each_other(tmp_path):
    # Two stores on the same files = two Claude Code sessions, each with its own index.
    s1 = MemoryStore(tmp_path / "m.db", tmp_path / "m.faiss", HashEmbedder())
    s2 = MemoryStore(tmp_path / "m.db", tmp_path / "m.faiss", HashEmbedder())
    a = s1.add("the staging port is 5433", trust="verified")
    assert [h.id for h in s2.search("staging port", k=1)] == [a]       # s2 sees s1's write
    b = s2.add("the cache ttl is 300 seconds", trust="verified")
    assert b in [h.id for h in s1.search("cache ttl seconds", k=2)]    # and the other way
    s1.mark_wrong(a)
    assert a not in [h.id for h in s2.search("staging port", k=3)]     # s2 drops what s1 marked wrong
    assert s1.add("the staging port is 5433", trust="verified") != a  # no merge into a wrong item
    s1.close()
    s2.close()


def test_word_order_matters_for_duplicates(store):
    # Probe 2026-11-25: a word-set check merged these into one note.
    a = store.add("Alice reports to Bob", trust="verified")
    b = store.add("Bob reports to Alice", trust="verified")
    assert a != b and store.stats()["total"] == 2


def test_merge_keeps_first_date_and_takes_user_source(store):
    import time
    a = store.add("The deploy key lives in vault", source="agent", trust="unverified")
    first = store.get(a).created
    time.sleep(0.01)
    assert store.add("The deploy key lives in vault.", source="user", trust="verified") == a
    m = store.get(a)
    assert m.created == first and m.last_seen > first
    assert m.trust == "verified" and m.source == "user" and m.times_seen == 2


def test_opposite_notes_are_not_hidden_as_near_duplicates(store):
    # Probe 2026-11-25: the near-duplicate filter hid the newer, opposite note.
    store.add("use tabs for indentation in this repo", trust="verified")
    store.add("do not use tabs for indentation in this repo", trust="verified")
    hits = store.search("tabs for indentation", k=2, diverse=0.5)
    assert len(hits) == 2


def test_keyword_search_skips_wrong_rows_in_sql(store):
    # The keyword search takes its best 50 rows: wrong rows must not use up those places.
    store.duplicate_threshold = 1.01
    for i in range(60):
        store.mark_wrong(store.add("zebra 4471"))
    for i in range(30):  # closer in meaning, so the vector search's 20 candidates miss the good note
        store.add("zebra")
    good = store.add("the gate code is 4471 for zebra", trust="verified")
    hits = store.search("zebra 4471", k=5, min_similarity=0.6)
    assert good in [h.id for h in hits]


def test_demote_respects_protection_and_user_facts(store):
    user = store.add("My editor is neovim", source="user", trust="verified")
    prot = store.add("Production runs Python 3.9", source="agent", trust="unverified", protected=True)
    agent = store.add("The cache is redis", source="agent", trust="unverified")
    done, refused = store.demote([user, prot, agent, 999], by_user=False)
    assert done == [agent] and sorted(refused) == sorted([user, prot])
    done, refused = store.demote([user], by_user=True)
    assert done == [user] and store.get(user).trust == "wrong"


def test_same_frame():
    from dore.memory import same_frame
    assert same_frame("My car is a Toyota", "My car is a Honda")
    assert same_frame("I live in Phnom Penh", "I live in Siem Reap")
    assert same_frame("Use tabs for indentation", "Do not use tabs for indentation")
    assert same_frame("The server IP is 10.0.0.5", "The server IP is 10.0.0.6")
    assert not same_frame("I bought my car in 2020", "My car is a Honda")
    assert not same_frame("My car has a broken mirror", "My car is a Honda")
    assert not same_frame("My car is a Toyota", "My car is a Toyota.")
    assert not same_frame("I was born in 1990", "I was born in Paris")


def test_replaces_rule():
    from dore.memory import replaces
    assert replaces("I live in Phnom Penh", "I live in Siem Reap")
    assert replaces("My car is a Toyota", "My car is a Honda")
    assert replaces("Use tabs for indentation", "Do not use tabs for indentation")
    assert not replaces("I have a dog called Buddy", "I have a dog called Max")
    assert not replaces("My friend name is King", "My friend name is Dara")
    assert not replaces("I bought my car in 2020", "My car is a Honda")


def test_unverified_note_cannot_replace_verified(store):
    old = store.add("the api port is 8080", source="user", trust="verified")
    store.add("the api port is 9090", source="agent", trust="unverified", supersede=True)
    assert store.last_replaced == [] and store.get(old).replaced_by is None


def test_replaced_note_is_kept_but_not_searched(store):
    old = store.add("the api port is 8080", trust="verified")
    new = store.add("the api port is 9090", trust="verified", supersede=True)
    assert store.last_replaced == [old] and store.get(old).replaced_by == new
    assert [h.id for h in store.search("api port", k=5)] == [new]
    assert store.stats()["total"] == 2


def test_protected_and_other_project_notes_are_not_replaced(store):
    prot = store.add("the api port is 8080", trust="verified", protected=True)
    other = store.add("the api port is 7070", trust="verified", project="blog")
    store.add("the api port is 9090", trust="verified", supersede=True)
    assert store.last_replaced == []
    assert store.get(prot).replaced_by is None and store.get(other).replaced_by is None


def test_feedback_reorders_close_notes_but_cannot_lift_unrelated(store):
    a = store.add("the team lunch is on friday", trust="verified")
    b = store.add("the team lunch is at noon", trust="verified")
    first = store.search("team lunch", k=2, touch=False)[0].id
    other = b if first == a else a
    store.feedback(other, 6)
    assert store.search("team lunch", k=2, touch=False)[0].id == other
    c = store.add("quantum chromodynamics lecture notes", trust="verified")
    store.feedback(c, 100)
    assert c not in [h.id for h in store.search("team lunch", k=3, min_similarity=0.3, touch=False)]
