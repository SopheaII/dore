"""Scores learning by Haiku consolidation on the labelled sets, next to the word-rule learner (`eval.learning`).

    python -m dore.eval.consolidation            # recorded answers only: 0 tokens
    python -m dore.eval.consolidation --live     # asks Haiku for missing answers (recorded for next time)
    python -m dore.eval.consolidation --real     # also the private real prompts (answers kept in data/eval/)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from dore.eval.cases import DEV, HELDOUT, UPDATES

ANSWERS = Path(__file__).with_name("judge_answers.json")  # made-up sentences only: safe to commit
REAL_ANSWERS = Path("data/eval/judge_real.json")          # private, git-ignored
REAL_LABELS = [Path("data/eval/real_labels.json"), Path("data/eval/real_labels_fresh.json")]


def _store(embedder):
    from dore.memory import MemoryStore
    d = Path(tempfile.mkdtemp(prefix="dore-cons-"))
    return MemoryStore(d / "m.db", None, embedder)


def score_messages(cases, embedder, ask, usage: list) -> dict:
    """Each case in its own store (no neighbours), many cases per call."""
    from dore.learn.consolidate import BATCH, Said, apply, sentences
    from dore.learn.judge import Item, judge
    s = {"facts": 0, "learned": 0, "scoped": 0, "skips": 0, "junk": 0, "hidden": 0, "rules": 0, "fails": []}
    lines = []  # (case index, Said)
    cases = [c for c in cases if c[1] is not None]
    for k, (text, _, _, _) in enumerate(cases):
        lines += [(k, Said(t, "proj", f"s{k}", 0.0)) for t in sentences(text)]
    stores = {k: _store(embedder) for k in range(len(cases))}
    got: dict[int, list] = {k: [] for k in range(len(cases))}
    for start in range(0, len(lines), BATCH):
        part = lines[start:start + BATCH]
        items = [Item(n, said.text) for n, (_, said) in enumerate(part, 1)]
        verdicts, u = judge(items, ask)
        usage.append(u)
        st = apply(lambda n: stores[part[n - 1][0]], items, [said for _, said in part], verdicts)
        for n, ids in st["lines"].items():
            k = part[n - 1][0]
            got[k] += [stores[k].get(i) for i in ids]
    for k, (text, expect, scope, style) in enumerate(cases):
        notes = [(m.content, "general" if m.project == "" else "project", stores[k].is_rule(m.id)) for m in got[k]]
        s["rules"] += sum(r for _, _, r in notes)
        if expect:
            s["facts"] += 1
            hit = [g for g in notes if expect.lower() in g[0].lower()]
            s["learned"] += bool(hit)
            ok = bool(hit) and (scope is None or any((sc == "general") == (scope == "general") for _, sc, _ in hit))
            s["scoped"] += ok
            if not ok:
                s["fails"].append(("missed" if not hit else "wrong scope", text, notes))
        else:
            s["skips"] += 1
            shown = [g for g in notes if not g[2]]  # a rule said once waits, hidden, for a repeat (`on_trial`)
            s["junk"] += bool(shown)
            s["hidden"] += bool(notes) and not shown
            if shown:
                s["fails"].append(("junk", text, notes))
    return s


def score_updates(embedder, ask, usage: list) -> dict:
    """The old note is in memory (as `eval.learning` does); the new sentence comes in a later session, the old note
    offered as a neighbour when close enough."""
    from dore.learn.consolidate import Said, apply, items_for
    from dore.learn.judge import Item, judge
    stores = [_store(embedder) for _ in UPDATES]
    for k, st in enumerate(stores):  # unique note ids across the batch, as in one real store
        st.db.execute("INSERT OR REPLACE INTO sqlite_sequence (name, seq) VALUES ('memories', ?)", (100 * (k + 1),))
    olds = {k: [stores[k].add(old, kind="statement", trust="verified", project="p", created=1.0)]
            for k, (old, _, _, _) in enumerate(UPDATES)}
    second = [Said(new, "p", "s2", 2.0) for _, new, _, _ in UPDATES]
    items = [Item(n, s.text, items_for(stores[n - 1], [s])[0].neighbours) for n, s in enumerate(second, 1)]
    verdicts, u = judge(items, ask)
    usage.append(u)
    apply(lambda n: stores[n - 1], items, second, verdicts)
    ok, fails, unstored = 0, [], 0
    for k, (old, new, must, style) in enumerate(UPDATES):
        m = stores[k].get(olds[k][0])
        replaced = m.replaced_by is not None or bool(stores[k].db.execute(
            "SELECT 1 FROM shadows WHERE note_id=?", (m.id,)).fetchone())
        ok += replaced == must
        if replaced != must:
            fails.append((style, old, new, "kept both" if must else "replaced"))
    return {"ok": ok, "n": len(UPDATES), "unstored": unstored, "fails": fails}


def main(argv: list[str] | None = None):
    argv = sys.argv[1:] if argv is None else argv
    from dore.config import Config
    from dore.learn.judge import ClaudeCLI, Recorded
    from dore.memory.embed import FastEmbedder
    cfg = Config()
    emb = FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed"))
    live = ClaudeCLI() if "--live" in argv else None
    ask = Recorded(ANSWERS, live)
    usage: list = []
    sets = [("DEV", DEV), ("HELDOUT", HELDOUT)]
    scores = {name: score_messages(c, emb, ask, usage) for name, c in sets}
    if "--real" in argv:
        real = [(r["text"], r["expect"], r.get("scope"), r.get("style", "real"))
                for f in REAL_LABELS if f.exists() for r in json.loads(f.read_text())]
        scores["REAL (private)"] = score_messages(real, emb, Recorded(REAL_ANSWERS, live), usage)
    print("| Set | Facts learned, right scope | Facts learned | Junk stored (shown) | Hidden rule lines | Rules made |\n"
          "|---|---|---|---|---|---|")
    for name, s in scores.items():
        print(f"| {name} | {s['scoped']}/{s['facts']} | {s['learned']}/{s['facts']} | {s['junk']}/{s['skips']} "
              f"| {s['hidden']}/{s['skips']} | {s['rules']} |")
    u = score_updates(emb, ask, usage)
    print(f"\n| Check | Result |\n|---|---|\n| Updates (replace or keep both, right) | {u['ok']}/{u['n']} "
          f"(old note not stored: {u['unstored']}) |")
    calls = [x for x in usage if not x.get("recorded")]
    print(f"\nHaiku calls this run: {len(calls)}, tokens in {sum(x['input'] for x in calls)}, "
          f"out {sum(x['output'] for x in calls)}, ${sum(x['usd'] for x in calls):.4f}")
    for name, s in scores.items():
        if name.startswith("REAL"):
            continue  # private text: counts only
        for kind, text, got in s["fails"]:
            print(f"{name} {kind}: {text[:70]!r} -> {[g[0][:50] + ' [' + g[1] + ']' for g in got][:3]}")
    for f in u["fails"]:
        print("update:", f)


if __name__ == "__main__":
    main()
