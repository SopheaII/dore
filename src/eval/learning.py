"""Scores what dore learns on the labelled sets: `python -m dore.eval.learning` (`--real`, `--styles`)."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from dore.eval.cases import DEV, HELDOUT, RETRIEVAL, UPDATES

REAL_LABELS = Path("data/eval/real_labels.json")


SIMILAR = None  # the hook's meaning check for parallel clauses (`hooks.similar_fn`), set by main()


def learn(text: str, project: str = "proj") -> list[tuple[str, str]]:
    """(note, scope) pairs the Claude Code hook would store for one message."""
    from dore.learn.statements import message_facts, scope_for
    return [(f, scope_for(f, project) or "general") for f in message_facts(text, SIMILAR)]


def score_messages(cases) -> dict:
    s = {"facts": 0, "learned": 0, "scoped": 0, "skips": 0, "junk": 0, "by_style": defaultdict(lambda: [0, 0]),
         "fails": []}
    for text, expect, scope, style in cases:
        if expect is None:
            continue
        got = learn(text)
        st = s["by_style"][style]
        st[1] += 1
        if expect:
            s["facts"] += 1
            hit = [g for g in got if expect.lower() in g[0].lower()]
            s["learned"] += bool(hit)
            ok = bool(hit) and (scope is None or any((sc == "general") == (scope == "general") for _, sc in hit))
            s["scoped"] += ok
            st[0] += ok
            if not ok:
                s["fails"].append(("missed" if not hit else "wrong scope", text, got))
        else:
            s["skips"] += 1
            s["junk"] += bool(got)
            st[0] += not got
            if got:
                s["fails"].append(("junk", text, got))
    return s


def score_updates(embedder) -> dict:
    from dore.memory import MemoryStore
    ok, fails = 0, []
    for old, new, must, style in UPDATES:
        d = Path(tempfile.mkdtemp(prefix="dore-upd-"))
        store = MemoryStore(d / "m.db", None, embedder)
        a = store.add(old, kind="statement", trust="verified", project="p", supersede=True)
        time.sleep(0.002)
        store.add(new, kind="statement", trust="verified", project="p", supersede=True)
        replaced = store.get(a).replaced_by is not None
        store.close()
        ok += replaced == must
        if replaced != must:
            fails.append((style, old, new, "kept both" if must else "replaced"))
    return {"ok": ok, "n": len(UPDATES), "fails": fails}


def score_retrieval(embedder) -> dict:
    """Every RETRIEVAL note plus all DEV/HELDOUT facts as distractors; ask each question in a fresh
    hook session and check the note is in what the hook adds."""
    from dore.integrations.hooks import _State, prompt_context
    from dore.memory import MemoryStore
    d = Path(tempfile.mkdtemp(prefix="dore-ret-"))
    store = MemoryStore(d / "m.db", None, embedder)
    distract = [t for t, e, _, st in DEV + HELDOUT if e and st not in ("other-language", "mixed", "correction")]
    from dore.learn.grammar import topic_key  # as the hook saves facts (`hooks.save_facts`)
    store.add_many(distract, kind="statement", trust="verified", project="p", keys=[topic_key(t) for t in distract])
    ids = [store.add(n, kind="statement", trust="verified", project="p", key=topic_key(n)) for n, _, _ in RETRIEVAL]
    ok, fails = 0, []
    for (note, q, style), mid in zip(RETRIEVAL, ids):
        st = _State(d, f"q{mid}")
        st.d["rules_done"] = True
        ctx = prompt_context(store, q, "p", st)
        hit = f"#{mid} " in ctx
        ok += hit
        if not hit:
            fails.append((style, q, note))
    store.close()
    return {"ok": ok, "n": len(RETRIEVAL), "fails": fails}


def _row(name: str, s: dict) -> str:
    return (f"| {name} | {s['scoped']}/{s['facts']} | {s['learned']}/{s['facts']} | "
            f"{s['junk']}/{s['skips']} |")


def main(argv: list[str] | None = None):
    argv = sys.argv[1:] if argv is None else argv
    from dore.config import Config
    from dore.memory.embed import FastEmbedder
    cfg = Config()
    emb = FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed"))
    global SIMILAR

    def SIMILAR(a: str, b: str) -> float:  # noqa: N802 - same check as the hook
        v = emb.embed([a, b])
        return float(v[0] @ v[1])
    sets = [("DEV", DEV), ("HELDOUT", HELDOUT)]
    if "--real" in argv and REAL_LABELS.exists():
        real = json.loads(REAL_LABELS.read_text())
        sets.append(("REAL (private)", [(r["text"], r["expect"], r.get("scope"), r.get("style", "real"))
                                         for r in real]))
    scores = {name: score_messages(c) for name, c in sets}
    print("| Set | Facts learned, right scope | Facts learned | Junk stored |\n|---|---|---|---|")
    for name, s in scores.items():
        print(_row(name, s))
    u, r = score_updates(emb), score_retrieval(emb)
    print(f"\n| Check | Result |\n|---|---|\n| Updates (replace or keep both, right) | {u['ok']}/{u['n']} |\n"
          f"| Retrieval (note shown for a rephrased question) | {r['ok']}/{r['n']} |")
    if "--styles" in argv:
        print("\n| Style | " + " | ".join(scores) + " |\n|---|" + "---|" * len(scores))
        styles = sorted({k for s in scores.values() for k in s["by_style"]})
        for st in styles:
            cells = [f"{s['by_style'][st][0]}/{s['by_style'][st][1]}" if st in s["by_style"] else "-"
                     for s in scores.values()]
            print(f"| {st} | " + " | ".join(cells) + " |")
    for name, s in scores.items():
        if name.startswith("REAL"):
            continue  # private text: counts only
        for kind, text, got in s["fails"]:
            print(f"{name} {kind}: {text[:70]!r} -> {[g[0][:50] + ' [' + g[1] + ']' for g in got][:3]}")
    for f in u["fails"]:
        print("update:", f)
    for f in r["fails"]:
        print("retrieval:", f)


if __name__ == "__main__":
    main()
