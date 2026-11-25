"""Benchmarks for the current machine (save results under reports/, git-ignored). Usage:

    python -m dore.bench llm [model.gguf ...]
    python -m dore.bench search
    python -m dore.bench embed
    python -m dore.bench memory [items]     # store speed at scale (random vectors, no model)
    python -m dore.bench remember           # auto-remember speed with the real embedder
    python -m dore.bench scale [projects]   # can recall still find the right fact among ~10k similar ones?
    python -m dore.bench stream [seed]      # simulated weeks of Claude Code use (dore.eval.stream)
"""

from __future__ import annotations

import resource
import sys
import time
from pathlib import Path

import numpy as np

from dore.config import Config


def rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20


def bench_llm(paths: list[str]):
    from llama_cpp import Llama

    cfg = Config()
    paths = paths or sorted(str(p) for p in (cfg.data_dir / "models").glob("*.gguf"))
    prompt = [{"role": "user", "content": "Explain in about 150 words how synapses store memories."}]
    for path in paths:
        t = time.perf_counter()
        llm = Llama(model_path=path, n_ctx=2048, n_threads=cfg.n_threads, verbose=False)
        load_s = time.perf_counter() - t
        llm.create_chat_completion(messages=[{"role": "user", "content": "hi"}], max_tokens=8)  # warm-up
        t = time.perf_counter()
        out = llm.create_chat_completion(messages=prompt, max_tokens=200, temperature=0.3)
        dt = time.perf_counter() - t
        u = out["usage"]
        print(f"{Path(path).name}: load {load_s:.1f}s | prompt {u['prompt_tokens']} tok | "
              f"gen {u['completion_tokens']} tok in {dt:.1f}s = {u['completion_tokens'] / dt:.1f} tok/s "
              f"(incl. prompt) | peak RSS {rss_gb():.2f} GB")
        del llm


def bench_search(dim: int = 384):
    import faiss

    rng = np.random.default_rng(0)
    for n in (10_000, 100_000, 1_000_000):
        x = rng.standard_normal((n, dim), dtype=np.float32)
        x /= np.linalg.norm(x, axis=1, keepdims=True)
        q = x[rng.integers(0, n, 100)] + 0.01
        flat = faiss.IndexFlatIP(dim)
        flat.add(x)
        t = time.perf_counter()
        flat.search(q, 5)
        flat_ms = (time.perf_counter() - t) / len(q) * 1000
        hnsw = faiss.IndexHNSWFlat(dim, 32, faiss.METRIC_INNER_PRODUCT)
        t = time.perf_counter()
        hnsw.add(x)
        build_s = time.perf_counter() - t
        hnsw.hnsw.efSearch = 64
        t = time.perf_counter()
        hnsw.search(q, 5)
        hnsw_ms = (time.perf_counter() - t) / len(q) * 1000
        print(f"{n:>9,} items: exact {flat_ms:7.2f} ms/query | HNSW {hnsw_ms:5.2f} ms/query "
              f"(build {build_s:.0f}s) | vectors {x.nbytes / 2**30:.2f} GB")
        del x, flat, hnsw


def bench_embed():
    from dore.memory.embed import FastEmbedder

    cfg = Config()
    e = FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed"))
    texts = [f"Paragraph {i}: neurons connect through synapses whose strength changes with learning. " * 8
             for i in range(200)]
    t = time.perf_counter()
    e.embed(texts)
    dt = time.perf_counter() - t
    print(f"embedded {len(texts)} chunks (~{len(texts[0])} chars) in {dt:.1f}s = {len(texts) / dt:.0f} chunks/s")


class _RandomEmbedder:
    """Fast fake embedder (random unit vectors) so store costs can be measured alone."""

    dim = 384

    def __init__(self):
        self.rng = np.random.default_rng(0)

    def embed(self, texts):
        v = self.rng.standard_normal((len(texts), self.dim)).astype(np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)


def _timed(fn, repeat=1):
    t = time.perf_counter()
    for _ in range(repeat):
        out = fn()
    return (time.perf_counter() - t) / repeat, out


def bench_memory(args: list[str]):
    import tempfile

    from dore.memory import MemoryStore

    n = int(args[0]) if args else 100_000
    with tempfile.TemporaryDirectory(prefix="dore-bench-") as tmp:
        db, ix = Path(tmp) / "m.db", Path(tmp) / "m.faiss"
        s = MemoryStore(db, ix, _RandomEmbedder(), index_save_interval=1e9)
        texts = [f"memory item {i}" for i in range(n)]
        dt, _ = _timed(lambda: s.add_many(texts, trust="verified"))
        print(f"bulk add_many {n:,} items: {dt:.1f}s = {n / dt:,.0f} items/s")
        dt, _ = _timed(lambda: s.add_many([f"statement {i}" for i in range(20)], kind="statement"), 20)
        print(f"one chat message (20 statements, one batch): {dt * 1000:.1f} ms")
        dt, _ = _timed(lambda: s.add("one item"), 50)
        print(f"single add (embed excluded): {dt * 1000:.2f} ms")
        dt, _ = _timed(lambda: s.search("query", k=5), 100)
        print(f"search top-5 among {s.index.ntotal:,}: {dt * 1000:.2f} ms")
        dt, _ = _timed(lambda: s.save(), 20)
        print(f"save() per chat turn (index write not due): {dt * 1000:.2f} ms")
        s.add("one more item")
        dt, _ = _timed(lambda: s.save(force=True))
        print(f"save(force) incl. index file: {dt * 1000:.0f} ms ({ix.stat().st_size / 2**20:.0f} MB)")
        s.close()
        dt, s2 = _timed(lambda: MemoryStore(db, ix, _RandomEmbedder()))
        print(f"startup, index file valid: {dt:.2f}s")
        s2.add("added after save")  # make the saved file stale, then 'crash'
        s2.db.commit()
        s2.db.close()
        dt, s3 = _timed(lambda: MemoryStore(db, ix, _RandomEmbedder()))
        print(f"startup after crash (index rebuilt from SQLite): {dt:.2f}s")
        s3.close()
        print(f"database size: {db.stat().st_size / 2**20:.0f} MB | peak RSS {rss_gb():.2f} GB")


def bench_remember():
    import tempfile

    from dore.assistant.agent import Agent
    from dore.memory.embed import FastEmbedder
    from dore.memory import MemoryStore

    cfg = Config()
    e = FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed"))
    e.embed(["warm up"])
    words = "neurons connect through synapses whose strength changes with learning and sleep".split()
    rng = np.random.default_rng(0)

    def sentences(k):
        return [" ".join(rng.choice(words, 10)).capitalize() + f" number {i}." for i in range(k)]

    with tempfile.TemporaryDirectory(prefix="dore-bench-") as tmp:
        store = MemoryStore(Path(tmp) / "m.db", None, e)
        agent = Agent(core=None, memory=store)
        for k in (3, 20):
            sents = sentences(k)
            dt_one, _ = _timed(lambda: [store.add(x) for x in sents])
            sents = sentences(k)
            dt_batch, _ = _timed(lambda: agent.remember_statements(" ".join(sents)))
            print(f"chat message with {k} statements: one-by-one {dt_one:.2f}s | batched {dt_batch:.2f}s")
        paste = " ".join(sentences(500))
        dt, ids = _timed(lambda: agent.remember_statements(paste))
        print(f"pasted text, 500 sentences ({len(paste):,} chars): {dt:.2f}s -> {len(ids)} document chunks")
        dt, _ = _timed(lambda: store.search("how do synapses learn during sleep", k=5), 20)
        print(f"search incl. embedding the question: {dt * 1000:.0f} ms")
        store.close()


SERVICES = ("billing checkout auth search gateway notifications inventory reports payments shipping catalog "
            "users sessions analytics email sms media uploads exports imports scheduler queue cache config "
            "audit admin pricing orders invoices refunds reviews ratings recommendations feeds webhooks "
            "ledger loyalty coupons tickets").split()
ATTRS = [  # (fact template, question template, values)
    ("The {s} service runs on port {v}.", "What port does {s} listen on?", [str(p) for p in range(3000, 9999, 7)]),
    ("{s} is pinned to version {v}.", "Which version of {s} do we use?", [f"{a}.{b}.{c}" for a in range(1, 6)
                                                                         for b in range(10) for c in range(5)]),
    ("Requests to {s} time out after {v} seconds.", "How long is the {s} timeout?", [str(t) for t in range(5, 300, 5)]),
    ("{s} stores its data in {v}.", "Which database does {s} use?",
     "Postgres MySQL Redis MongoDB SQLite DynamoDB Cassandra ClickHouse Elasticsearch MariaDB".split()),
    ("{v} owns the {s} service.", "Who is responsible for {s}?",
     "Dara Sokha Vanna Chenda Rithy Bopha Sophal Kosal Malis Piseth Nary Visal".split()),
    ("{s} is deployed every {v}.", "When do we deploy {s}?",
     "Monday Tuesday Wednesday Thursday Friday morning evening night hour".split()),
    ("{s} is hosted in the {v} region.", "Where is {s} hosted?",
     "Singapore Tokyo Frankfurt Virginia Oregon Sydney Mumbai London".split()),
    ("{s} retries failed calls {v} times.", "How many retries does {s} do?", [str(n) for n in range(1, 13)]),
]
FILLER = ["In {p} we chose {a} over {b} because it was simpler to operate.",
          "The {s} bug in {p} was caused by a timezone mismatch in the {a} client.",
          "Code review rule for {p}: every {s} change needs a test for the {a} path.",
          "The {s} dashboard in {p} shows {a} latency and {b} errors."]
WORDS = "Kafka RabbitMQ gRPC REST GraphQL Docker Kubernetes Terraform Nginx Celery Sentry Grafana".split()


def bench_scale(args: list[str]):
    """Hide target facts among many similar ones and measure how often recall finds them."""
    import tempfile

    from dore.memory.embed import FastEmbedder
    from dore.memory import MemoryStore

    n_projects = int(args[0]) if args else 25
    rng = np.random.default_rng(42)
    projects = [f"proj{i:02d}" for i in range(n_projects)]
    facts, truth = [], {}  # truth[(project, service, attr)] = value
    for p in projects:
        for s in SERVICES:
            for ai, (ft, _, vals) in enumerate(ATTRS):
                v = str(rng.choice(vals))
                truth[(p, s, ai)] = v
                facts.append((p, ft.format(s=s, v=v)))
        for _ in range(len(SERVICES) * 2):
            t = FILLER[rng.integers(len(FILLER))]
            a, b = rng.choice(WORDS, 2, replace=False)
            facts.append((p, t.format(p=p, s=rng.choice(SERVICES), a=a, b=b)))
    cfg = Config()
    e = FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed"))
    with tempfile.TemporaryDirectory(prefix="dore-scale-") as tmp:
        store = MemoryStore(Path(tmp) / "scale.db", None, e, duplicate_threshold=1.01)
        t = time.perf_counter()
        for p in projects:
            store.add_many([f for q, f in facts if q == p], trust="verified", project=p)
        print(f"stored {len(facts):,} notes in {n_projects} projects in {time.perf_counter() - t:.0f}s")
        keys = list(truth)
        targets = [keys[i] for i in rng.choice(len(keys), 100, replace=False)]

        def score(**kw):
            hit1 = hit3 = 0
            lat = []
            for p, s, ai in targets:
                q = ATTRS[ai][1].format(s=s)
                t = time.perf_counter()
                hits = store.search(q, k=3, min_similarity=0.5, touch=False,
                                    project=p if kw.get("scoped", True) else None,
                                    keyword=kw.get("keyword", True))
                lat.append(time.perf_counter() - t)
                want = ATTRS[ai][0].format(s=s, v=truth[(p, s, ai)])
                ok = [h.content == want and h.project == p for h in hits]
                hit1 += bool(ok[:1] and ok[0])
                hit3 += any(ok)
            return hit1, hit3, 1000 * float(np.median(lat))

        print(f"\n| Search | Right fact 1st | Right fact in top 3 | Median time |\n|---|---|---|---|")
        for label, kw in (("project + hybrid (default)", {}), ("project, meaning only", {"keyword": False}),
                          ("no project filter", {"scoped": False})):
            h1, h3, ms = score(**kw)
            print(f"| {label} | {h1}/100 | {h3}/100 | {ms:.0f} ms |")
        unknown = ["What is the {s} cache eviction policy?", "Which CDN serves {s} images?",
                   "What is the SLA for {s}?", "Which font does the {s} page use?"]
        empty = tokens = 0
        for i in range(100):
            q = unknown[i % 4].format(s=SERVICES[i % len(SERVICES)])
            hits = store.search(q, k=3, min_similarity=0.5, touch=False, project=projects[i % n_projects])
            empty += not hits
            tokens += sum(len(h.content) for h in hits) // 4
        print(f"\nquestions with no answer in memory: {empty}/100 returned nothing; "
              f"~{tokens / 100:.0f} tokens of notes per question otherwise (estimate: chars/4)")
        store.close()


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "search"
    {"llm": lambda: bench_llm(sys.argv[2:]), "search": bench_search, "embed": bench_embed,
     "memory": lambda: bench_memory(sys.argv[2:]), "remember": bench_remember,
     "scale": lambda: bench_scale(sys.argv[2:]),
     "stream": lambda: __import__("dore.eval.stream", fromlist=["main"]).main(sys.argv[2:])}[what]()
