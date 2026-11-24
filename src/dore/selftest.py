"""End-to-end goal test with the real model and embedder, in a throw-away folder.

Never touches data/memory.db: every scenario uses a fresh store in a temporary
directory (deleted afterwards). Each question is asked with several seeds,
because one sample of a 1B model proves little.

    python -m dore.selftest            # all scenarios, 3 seeds
    python -m dore.selftest 5 car      # 5 seeds, only scenarios whose name contains "car"
"""

from __future__ import annotations

import re
import sys
import tempfile
import time
from pathlib import Path

from .agent import Agent
from .config import Config
from .core import Core
from .embed import FastEmbedder
from .memory import MemoryStore

UNKNOWN = re.compile(r"don't know|do not know|no information|not sure|haven't told|not mentioned|"
                     r"don't have (any )?information|no record|not aware|can't find|cannot find|unknown", re.I)


class Run:
    def __init__(self, core: Core, embedder, seeds: int):
        self.core, self.embedder, self.seeds = core, embedder, seeds
        self.results: list[tuple[str, str, int, int, list[str]]] = []
        self.chat_s = 0.0
        orig = core.chat

        def timed_chat(*a, **kw):
            t = time.perf_counter()
            try:
                return orig(*a, **kw)
            finally:
                self.chat_s += time.perf_counter() - t
        core.chat = timed_chat

    def agent(self, folder: Path) -> Agent:
        store = MemoryStore(folder / "memorytest.db", folder / "memorytest.faiss", self.embedder)
        return Agent(core=self.core, memory=store, n_ctx=self.core.n_ctx)

    def ask(self, scenario: str, a: Agent, question: str, want: str | None = None,
            avoid: str | None = None, label: str | None = None):
        """Ask with every seed. want=None means the right answer is "I don't know"."""
        ok, fails = 0, []
        for seed in range(self.seeds):
            self.core._llm.set_seed(seed)
            hist = list(a.history)
            ans = a.ask(question)
            a.history = hist  # every seed sees the same conversation
            good = bool(UNKNOWN.search(ans)) if want is None else want.lower() in ans.lower()
            if avoid and avoid.lower() in ans.lower():
                good = False
            ok += good
            if not good:
                fails.append(ans[:100])
        self.results.append((scenario, label or question, ok, self.seeds, fails))

    def check(self, scenario: str, label: str, passed: bool, detail: str = ""):
        self.results.append((scenario, label, int(passed), 1, [] if passed else [detail]))


# ---------------- scenarios ----------------

def s_chat_learning(r: Run, a: Agent):
    a.ask("My cat is called Mochi and I live in Phnom Penh.")
    a.ask("I work as a nurse at Calmette Hospital.")
    a.history.clear()
    r.ask("chat", a, "What is my cat called?", "Mochi")
    r.ask("chat", a, "Where do I live?", "Phnom Penh")
    r.ask("chat", a, "What is my job?", "Calmette")
    r.ask("chat", a, "What is my dog called?", None)
    r.ask("chat", a, "What is the capital of France?", "Paris")


def s_teach(r: Run, a: Agent):
    a.teach("The wifi password at home is lotus-42.")
    r.ask("teach", a, "What is the wifi password at home?", "lotus-42")


def s_please_remember(r: Run, a: Agent):
    a.ask("Please remember that my wife's name is Dara.")
    a.history.clear()
    r.ask("please-remember", a, "What is my wife's name?", "Dara")


def s_correct(r: Run, a: Agent):
    a.ask("My car is a Toyota.")
    a.history.clear()
    r.ask("correct", a, "What car do I have?", "Toyota", label="before /correct")
    a.ask("What car do I have?")
    wrong_id = a.last_answer_id
    a.correct("My car is a Honda.")
    a.history.clear()
    r.check("correct", "old answer marked wrong", a.memory.get(wrong_id).trust == "wrong")
    r.check("correct", "old fact 'Toyota' marked wrong (kept)", bool(a.last_demoted_ids),
            f"demoted: {a.last_demoted_ids}")
    r.ask("correct", a, "What car do I have?", "Honda", avoid="Toyota", label="after /correct")


def s_plain_correct(r: Run, a: Agent):
    """The user corrects in plain words (no /correct): the old fact must stop being used."""
    a.ask("My car is a Toyota.")
    a.ask("What car do I have?")
    wrong_id = a.last_answer_id
    a.ask("No, my car is a Honda.")
    a.history.clear()
    r.check("plain-correct", "old answer marked wrong", a.memory.get(wrong_id).trust == "wrong")
    r.check("plain-correct", "'Toyota' no longer searchable (kept)",
            not any("Toyota" in h.content for h in a.memory.search("my car", k=5, touch=False)))
    r.ask("plain-correct", a, "What car do I have?", "Honda", avoid="Toyota")


def s_reask(r: Run, a: Agent):
    """Reactions are learned without commands: asking again lowers the notes used."""
    a.ask("I live in Phnom Penh.")
    note = a.memory.search("I live in Phnom Penh", k=1, touch=False)[0].id
    a.ask("Where do I live?")
    a.ask("Which city do I live in?")
    r.check("reask", "asking again is noticed", a.last_signal == "reask", a.last_signal)
    r.check("reask", "notes used lose a point", a.memory.get(note).feedback == -1,
            f"feedback={a.memory.get(note).feedback}")
    a.ask("What is my cat called?")
    a.ask("What is my dog called?")
    r.check("reask", "dog after cat is a new question", a.last_signal == "moved_on", a.last_signal)


def s_newer_wins(r: Run, a: Agent):
    a.ask("I live in Phnom Penh.")
    a.ask("I moved to Siem Reap last week, so now I live in Siem Reap.")
    a.history.clear()
    r.ask("newer-wins", a, "Where do I live now?", "Siem Reap")


def s_newer_wins_plain(r: Run, a: Agent):
    a.ask("I live in Phnom Penh.")
    a.ask("I live in Siem Reap.")
    a.history.clear()
    r.ask("newer-wins-plain", a, "Where do I live?", "Siem Reap", avoid="Phnom Penh")


def s_near_duplicates(r: Run, a: Agent):
    a.teach("The server IP is 10.0.0.5.")
    a.teach("The server IP is 10.0.0.6.")  # embeddings score this pair 0.985
    rows = [c for (c,) in a.memory.db.execute("SELECT content FROM memories WHERE kind='fact'")]
    r.check("near-dup", "two different IPs both kept", len(rows) == 2, f"stored: {rows}")
    a.teach("My meeting is on Monday at 9.")
    a.teach("My meeting is on Monday at 9.")  # exact repeat: should merge
    n = a.memory.db.execute("SELECT COUNT(*) FROM memories WHERE content LIKE 'My meeting%'").fetchone()[0]
    r.check("near-dup", "exact repeat merged", n == 1, f"{n} rows")


def s_no_noise(r: Run, a: Agent):
    for msg in ("Thanks a lot!", "Hello, how are you", "Summarize the following text.",
                "Write a poem about rain.", "Can you help me with my homework"):
        a.ask(msg)
    rows = [c for (c,) in a.memory.db.execute("SELECT content FROM memories WHERE kind='statement'")]
    r.check("no-noise", "small talk / requests not stored as facts", not rows, f"stored as facts: {rows}")


def s_answers_not_reused(r: Run, a: Agent):
    a.ask("What does the KIBRA gene do?")
    ans_id = a.last_answer_id
    hits = [m.id for m in a.memory.search("KIBRA gene", k=10, touch=False)]
    r.check("approval", "unapproved answer not searchable", ans_id not in hits)
    a.good()
    hits = [m.id for m in a.memory.search("KIBRA gene", k=10, touch=False)]
    r.check("approval", "/good makes it searchable", ans_id in hits)


def s_persistence(r: Run, a: Agent, folder: Path):
    a.ask("My cat is called Mochi.")
    a.memory.close()
    b = r.agent(folder)
    r.ask("persistence", b, "What is my cat called?", "Mochi", label="after restart")
    b.memory.close()


def s_code(r: Run, a: Agent):
    res = a.solve_code("Write a function is_palindrome(s) that ignores case and spaces.",
                       tests="assert is_palindrome('Never odd or even')\nassert not is_palindrome('abc')")
    r.check("code", "tested solution saved as verified lesson",
            res.check.passed and res.memory_id is not None and a.memory.get(res.memory_id).trust == "verified",
            f"passed={res.check.passed} attempts={res.attempts}")
    hits = a.memory.search("check if a string is a palindrome", k=3, min_similarity=a.min_similarity, touch=False)
    r.check("code", "lesson found for a similar task", any(h.kind == "lesson" for h in hits))
    # Truly impossible: with only "f() == 2" the model sometimes just returns 2 and passes (2026-11-25).
    res2 = a.solve_code("Write f() returning 1.", tests="assert f() == 1\nassert f() == 2")
    r.check("code", "failed code not saved", res2.memory_id is None)


def s_long_paste(r: Run, a: Agent):
    filler = " ".join(f"Section {i} describes routine maintenance of the cooling system." for i in range(150))
    text = filler + " The emergency shutdown code is RED-7731. " + filler
    a.ask(text + " Please store this manual.")
    a.history.clear()
    kinds = dict(a.memory.db.execute("SELECT kind, COUNT(*) FROM memories GROUP BY kind").fetchall())
    r.check("long-paste", "stored as document chunks, not facts", "statement" not in kinds and "document" in kinds,
            str(kinds))
    r.ask("long-paste", a, "What is the emergency shutdown code?", "RED-7731")


def s_keyword(r: Run, a: Agent):
    a.teach("Server SRV-4471 is used for nightly backups.")
    for i in range(20):
        a.teach(f"Server rack {i} holds web machines and network switches number {i * 7}.")
    r.ask("keyword", a, "What is SRV-4471 used for?", "backup")
    hits = a.memory.search("SRV-4471", k=3, min_similarity=a.min_similarity, touch=False)
    r.check("keyword", "exact ID found first", bool(hits) and "SRV-4471" in hits[0].content,
            f"top: {hits[0].content if hits else None}")


def s_projects(r: Run, a: Agent):
    a.project = "shop"
    a.teach("The API port is 8080.")
    a.ask("My cat is called Mochi.")
    a.project = "blog"
    a.teach("The API port is 9090.")
    a.history.clear()
    r.ask("projects", a, "What port does the API use?", "9090", avoid="8080", label="blog sees only its port")
    r.ask("projects", a, "What is my cat called?", "Mochi", label="personal fact visible in other project")
    a.project = "shop"
    r.ask("projects", a, "What port does the API use?", "8080", avoid="9090", label="shop sees only its port")


def s_never_delete(r: Run, a: Agent):
    keep = a.teach("I am allergic to penicillin.", protected=True)
    other = a.teach("I parked on level 3.")
    a.memory.mark_wrong(other)
    total = a.memory.stats()["total"]
    r.check("never-delete", "protected item can't be archived", a.memory.archive(keep) is False)
    r.check("never-delete", "wrong item kept in database", a.memory.stats()["total"] == total)


SCENARIOS = [
    ("chat", s_chat_learning), ("teach", s_teach), ("please-remember", s_please_remember),
    ("correct", s_correct), ("plain-correct", s_plain_correct), ("reask", s_reask), ("newer-wins", s_newer_wins), ("newer-wins-plain", s_newer_wins_plain),
    ("near-dup", s_near_duplicates),
    ("no-noise", s_no_noise), ("approval", s_answers_not_reused), ("persistence", s_persistence),
    ("code", s_code), ("long-paste", s_long_paste), ("keyword", s_keyword), ("projects", s_projects), ("never-delete", s_never_delete),
]


def main(argv: list[str]):
    seeds = int(argv[0]) if argv else 3
    only = argv[1] if len(argv) > 1 else ""
    cfg = Config()
    embedder = FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed"))
    core = Core(cfg.model_path, n_ctx=cfg.n_ctx, n_threads=cfg.n_threads)
    r = Run(core, embedder, seeds)
    t0 = time.perf_counter()
    for name, fn in SCENARIOS:
        if only not in name:
            continue
        with tempfile.TemporaryDirectory(prefix="dore-selftest-") as tmp:
            folder = Path(tmp)
            a = r.agent(folder)
            try:
                fn(r, a, folder) if name == "persistence" else fn(r, a)
            except Exception as e:  # noqa: BLE001
                r.check(name, "scenario crashed", False, f"{type(e).__name__}: {e}")
            finally:
                try:
                    a.memory.close()
                except Exception:  # noqa: BLE001  (already closed)
                    pass
        print(f"  done: {name}", file=sys.stderr)
    total = time.perf_counter() - t0
    print(f"\n| Scenario | Check | Passed | Failures (sample) |\n|---|---|---|---|")
    ok = n = 0
    for scen, label, good, tries, fails in r.results:
        ok += good == tries
        n += 1
        print(f"| {scen} | {label} | {good}/{tries} | {'; '.join(dict.fromkeys(fails))[:150]} |")
    print(f"\n{ok}/{n} checks fully passed. Time {total:.0f}s, of which model {r.chat_s:.0f}s "
          f"(memory + rest {total - r.chat_s:.0f}s).")


if __name__ == "__main__":
    main(sys.argv[1:])
