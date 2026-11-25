"""Conversation check of the Claude Code hook path: does memory stay right as facts change?

    python -m dore.eval.conversation          # short + long, ~10 s, no LLM, throw-away store
    python -m dore.eval.conversation short    # 2 sessions, 7 questions ("shopcart" project)
    python -m dore.eval.conversation long     # 20 sessions, 486 messages, 80 questions

Messages go through `hooks.on_prompt` exactly as in Claude Code, with the real embedder.
Each question then gets a fresh session (no session-start rules block for `long`). Scores:
- correct: the current value is in what the hook adds (or nothing added when nothing was said);
- old value shown: an outdated value is also added (it should have been replaced);
- tokens: characters added / 4.
Results on 2026-11-25 after the replace fixes: short 5/7, old 0/3; long 80/80, old 0/53, ~46 tokens.
"""

from __future__ import annotations

import random
import sys
import tempfile
import time
from pathlib import Path

SHORT_SESSIONS = [
    [
        "hey, can you add discount codes to the cart? codes should be case-insensitive. finance decided the max "
        "discount is 50% because anything higher loses money on shipping. fyi our production server is still on "
        "python 3.9 so keep the code compatible. add tests",
        "Our staging server runs on port 8443.",
        "We use pytest for all tests, not unittest.",
        "The payment provider is Stripe.",
        "add a SUMMER code for 60% off please",
        "rename x to total in calc.py",
    ],
    [
        "Our staging server now runs on port 9443.",
        "No, the max discount is 40%, finance changed it.",
        "The payment provider is Adyen now.",
    ],
]
SHORT_QUESTIONS = [  # (question, current answer or None = nothing should be added, outdated answers)
    ("What port does the staging server use?", "9443", ["8443"]),
    ("What is the maximum discount allowed?", "40%", ["50%"]),
    ("Which payment provider do we use?", "Adyen", ["Stripe"]),
    ("Which Python version is production on?", "3.9", []),
    ("Which test framework should I use?", "pytest", []),
    ("Are discount codes case sensitive?", "case-insensitive", []),
    ("What database do we use?", None, []),
]


def long_scenario(seed: int = 7):
    """60 services whose port changes 0-3 times, 20 people who may change team, 300 requests."""
    r = random.Random(seed)
    services = [f"{a}-{b}" for a in "billing search auth cart email report media audit sync queue".split()
                for b in "api worker gateway cache web db".split()]
    people = ("Alex Sam Robin Kim Lee Jo Max Ana Ben Eva Ivan Lena Omar Pia Raj Sara Tom Uma Yan Zoe").split()
    teams = "payments search platform mobile data security growth infra web support".split()
    requests = ["add tests for {s}", "rename x to total in {s}.py", "fix the bug in the {s} handler",
                "refactor the {s} module", "can you explain how {s} works?", "write a docstring for {s}",
                "run the linter on {s}"]
    events, current, old = [], {}, {}
    for s in services:
        port = r.randrange(2000, 9999)
        events.append((r.randrange(0, 5), f"The {s} service runs on port {port}."))
        current[s], day = str(port), 5
        for _ in range(r.choice([0, 1, 2, 3])):
            day += r.randrange(1, 5)
            new = r.randrange(2000, 9999)
            old.setdefault(s, []).append(current[s])
            current[s] = str(new)
            events.append((min(day, 19), f"The {s} service now runs on port {new}."))
    for p in people:
        team = r.choice(teams)
        events.append((r.randrange(0, 5), f"{p} works on the {team} team."))
        current[p] = team
        if r.random() < 0.5:
            new = r.choice([t for t in teams if t != team])
            old[p], current[p] = [team], new
            events.append((r.randrange(6, 20), f"{p} works on the {new} team now."))
    for _ in range(300):
        events.append((r.randrange(0, 20), r.choice(requests).format(s=r.choice(services))))
    events.sort(key=lambda e: e[0])
    sessions = [[m for d, m in events if d == i] for i in range(20)]
    questions = ([(f"What port does the {s} service use?", current[s], old.get(s, [])) for s in services]
                 + [(f"Which team does {p} work on?", current[p], old.get(p, [])) for p in people])
    return sessions, questions


def run(sessions, questions, embedder, rules_block: bool = True) -> dict:
    from dore.integrations.hooks import _State, on_prompt
    from dore.memory import MemoryStore
    d = Path(tempfile.mkdtemp(prefix="dore-conv-"))
    store = MemoryStore(d / "m.db", None, embedder)
    t = time.time()
    for i, sess in enumerate(sessions):
        state = _State(d, f"s{i}")
        for msg in sess:
            on_prompt(store, msg, "proj", state)
    ok = stale = chars = 0
    misses = []
    for i, (q, cur, olds) in enumerate(questions):
        state = _State(d, f"q{i}")
        state.d["rules_done"] = not rules_block
        ctx = on_prompt(store, q, "proj", state)
        words = set(ctx.lower().replace(",", " ").replace(". ", " ").replace(".\n", " ").split())
        hit = (cur is None and not ctx) or (cur is not None and (cur.lower() in words or cur.lower() in ctx.lower()))
        ok += hit
        stale += any(o.lower() in words for o in olds)
        chars += len(ctx)
        if not hit:
            misses.append(q)
    store.close()
    return {"correct": ok, "questions": len(questions), "old_shown": stale,
            "changed": sum(1 for q in questions if q[2]), "tokens": chars / 4 / len(questions),
            "seconds": time.time() - t, "misses": misses}


def main(argv: list[str] | None = None):
    which = (argv if argv is not None else sys.argv[1:]) or ["all"]
    from dore.config import Config
    from dore.memory.embed import FastEmbedder
    cfg = Config()
    emb = FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed"))
    rows = []
    if which[0] in ("all", "short"):
        rows.append(("short (7 questions)", run(SHORT_SESSIONS, SHORT_QUESTIONS, emb)))
    if which[0] in ("all", "long"):
        rows.append(("long (80 questions)", run(*long_scenario(), emb, rules_block=False)))
    print("| Check | Correct | Old value shown | Tokens/question | Time |\n|---|---|---|---|---|")
    for name, r in rows:
        print(f"| {name} | {r['correct']}/{r['questions']} | {r['old_shown']}/{r['changed']} | "
              f"~{r['tokens']:.0f} | {r['seconds']:.1f} s |")
    for name, r in rows:
        for q in r["misses"]:
            print(f"miss ({name}): {q}")


if __name__ == "__main__":
    main()
