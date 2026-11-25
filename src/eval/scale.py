"""Scale check: months of Claude Code use in many projects, through the real prompt hook.

    python -m dore.eval.scale [projects] [weeks] [seed]     # default 12 projects, 24 weeks (~9k prompts)

Every project states each kind of fact once (in varied wording), ~15% change later (reworded),
most prompts are noise. Every 4 weeks every known fact is asked in its project. Shows whether
accuracy, stale values, leaks, speed and tokens hold up as memory grows. No LLM, throw-away store.
"""

from __future__ import annotations

import random
import sys

from dore.eval.stream import FILES, FIRST_STATEMENT, GENERAL_FACTS, NOISE, Msg, Question, Scenario, run

KINDS = {  # kind -> (question, wordings, value pool)
    "db": ("Which database does this project use?", FIRST_STATEMENT["db"],
           "PostgreSQL MySQL SQLite MongoDB DynamoDB CockroachDB MariaDB Firestore Supabase Neo4j".split()),
    "tests": ("How do I run the tests here?", FIRST_STATEMENT["tests"],
              "pytest vitest jest mocha nextest unittest playwright cypress ava tap".split()),
    "deploy": ("Where does this project deploy to?", FIRST_STATEMENT["deploy"],
               "Heroku Render Netlify Vercel Fly.io AWS GCP Azure Railway Cloudflare".split()),
    "port": ("What port does the dev server use?", FIRST_STATEMENT["port"], [str(p) for p in range(3000, 9000, 37)]),
    "cache": ("What do we use for caching?", ["We cache with {v}.", "the cache is {v}", "caching uses {v}"],
              "Redis Memcached Varnish Dragonfly KeyDB Hazelcast".split()),
    "queue": ("Which message queue does this project use?",
              ["The queue is {v}.", "we use {v} for queues", "jobs go through {v}"],
              "RabbitMQ Kafka SQS NATS Pulsar Celery BullMQ".split()),
    "auth": ("Who is the auth provider?",
             ["The auth provider is {v}.", "login uses {v}", "we authenticate with {v}"],
             "Auth0 Clerk Keycloak Cognito Firebase Okta Supertokens".split()),
    "node": ("Which Node version does this project need?",
             ["This project needs Node {v}.", "node version is {v}", "we run on node {v}"],
             ["16", "18", "20", "22", "24"]),
}
CHANGE = ["We switched the {k} to {v}.", "{K} is {v} now.", "actually the {k} is {v} now", "we moved {k} to {v}"]
KIND_WORD = {"db": "database", "tests": "test runner", "deploy": "hosting", "port": "dev port",
             "cache": "cache", "queue": "queue", "auth": "auth provider", "node": "node version"}


def scenario(projects: int = 12, weeks: int = 24, seed: int = 1, prompts: int = 30, check_every: int = 4) -> Scenario:
    r = random.Random(seed)
    names = [f"proj{i:02d}" for i in range(projects)]
    sc = Scenario()
    cur: dict = {}
    old: dict = {}
    plan: dict[int, dict[str, list]] = {}
    for p in names:
        for k, (_, wordings, pool) in KINDS.items():
            v = r.choice(pool)
            w = r.randrange(1, max(2, weeks // 3))
            plan.setdefault(w, {}).setdefault(p, []).append(("set", k, v, r.choice(wordings).format(v=v)))
            if r.random() < 0.15 and w < weeks:
                v2 = r.choice([x for x in pool if x != v])
                text = r.choice(CHANGE).format(k=KIND_WORD[k], K=KIND_WORD[k].capitalize(), v=v2)
                plan.setdefault(r.randrange(w + 1, weeks + 1), {}).setdefault(p, []).append(("set", k, v2, text))
    for i, (k, (_, texts, v)) in enumerate(GENERAL_FACTS.items()):
        plan.setdefault(1 + i, {}).setdefault(names[i % projects], []).append(("gen", k, v, r.choice(texts)))
    for week in range(1, weeks + 1):
        for p in names:
            mine = plan.get(week, {}).get(p, [])
            n = max(prompts, len(mine))
            slots = sorted(r.sample(range(n), len(mine)))
            fi = 0
            for i in range(n):
                if fi < len(mine) and i == slots[fi]:
                    kind, k, v, text = mine[fi]
                    key = (p if kind == "set" else "", k)
                    if key in cur and cur[key] != v:
                        old.setdefault(key, []).append(cur[key])
                    cur[key] = v
                    sc.messages.append(Msg(week, f"w{week}-{p}", p, text, True))
                    fi += 1
                else:
                    sc.messages.append(Msg(week, f"w{week}-{p}", p, r.choice(NOISE).format(f=r.choice(FILES)), False))
        if week % check_every == 0 or week == weeks:
            qs = []
            for (p, k), v in cur.items():
                if p:
                    others = sorted({cur.get((o, k)) for o in names if o != p} - {None, v} - set(old.get((p, k), [])))
                    qs.append(Question(p, k, KINDS[k][0], v, list(old.get((p, k), [])), others))
                else:
                    qs.append(Question(r.choice(names), k, GENERAL_FACTS[k][0], v, list(old.get(("", k), [])), []))
            sc.checkpoints[week] = qs
    return sc


def report(r: dict) -> str:
    out = ["| Week | Correct | Stale shown | Leak | Searchable notes | ms per question | Tokens per question |",
           "|---|---|---|---|---|---|---|"]
    for w in r["weekly"]:
        out.append(f"| {w['week']} | {w['correct']}/{w['questions']} ({100 * w['correct'] / max(1, w['questions']):.0f}%)"
                   f" | {w['stale']}/{w['with_old']} | {w['leak']} | {w['searchable']} | {w['q_ms']:.0f} | "
                   f"{w['q_tokens']:.0f} |")
    out.append(f"\nprompts {r['messages']} (facts {r['facts']}); junk {len(r['junk_msgs'])} msgs; missed "
               f"{len(r['missed'])}; tokens/work prompt {r['tokens_work']:.1f}; hook median {r['hook_ms_median']:.0f} ms,"
               f" p95 {r['hook_ms_p95']:.0f} ms; run {r['seconds']:.0f} s")
    return "\n".join(out)


def main(argv: list[str] | None = None):
    argv = sys.argv[1:] if argv is None else argv
    a = ([int(x) for x in argv] + [12, 24, 1][len(argv):])[:3]
    from dore.config import Config
    from dore.memory.embed import FastEmbedder
    cfg = Config()
    emb = FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed"))
    r = run(scenario(*a), emb)
    print(report(r))
    print(*[f"miss: {m}" for m in r["weekly"][-1]["misses"]], sep="\n")
    print(*[f"missed: {m!r}" for m in r["missed"]], sep="\n")


if __name__ == "__main__":
    main()
