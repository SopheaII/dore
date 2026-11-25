"""bench stream: simulated weeks of Claude Code use in several projects, through the real prompt hook.

    python -m dore.eval.stream            # ~4 weeks, 3 projects, one 220-prompt session; no LLM
    python -m dore.eval.bench stream      # same

Each project states its own value for the same kinds of fact (database, port, deploy target...), so a
note shown in the wrong project is visible. Facts change over the weeks (some in the same words, some
reworded, one as "No, ..."), most messages are noise (requests, thanks, errors, pasted tracebacks).
At the end of each week every known question is asked in a fresh session of each project.

Scores (higher correct, everything else lower is better):
- correct: the current value is in what the hook adds (or, when nothing is known, no other project's value);
- stale: an outdated value of the same fact is also shown;
- leak: another project's value is shown without the "(from project X)" label;
- repeat mistakes: the same question missed in two weeks in a row with no change in between;
- junk: noise messages that were stored as notes; missed: fact messages that stored nothing;
- tokens: characters the hook adds / 4, on work prompts (not the checkpoint questions).
"""

from __future__ import annotations

import random
import re
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

PROJECTS = ("shop", "blog", "api")
WEEKS = 4

# kind -> (question, {project: first value}); statements are written per event below.
PROJECT_FACTS = {
    "db": ("Which database does this project use?", {"shop": "PostgreSQL", "blog": "SQLite", "api": "MongoDB"}),
    "tests": ("How do I run the tests here?", {"shop": "pytest", "blog": "vitest", "api": "nextest"}),
    "deploy": ("Where does this project deploy to?", {"shop": "Heroku", "blog": "Netlify", "api": "AWS"}),
    "branch": ("What is the main branch called?", {"shop": "develop", "blog": "master", "api": "trunk"}),
    "port": ("What port does the dev server use?", {"shop": "3000", "blog": "4000", "api": "8080"}),
    "css": ("Which CSS framework do we use for styling?", {"shop": "Tailwind", "blog": "Bootstrap"}),
}
# Several wordings per fact (plain, casual, non-native); each seed picks one, so a rule tuned to
# one wording shows up as a drop on other seeds.
FIRST_STATEMENT = {
    "db": ["This project uses {v} as its database.", "the database is {v}", "our db are {v}",
           "We store everything in {v}."],
    "tests": ["We run the tests with {v}.", "tests use {v}", "Our test runner is {v}.", "we test with {v} here"],
    "deploy": ["We deploy to {v}.", "this app is deployed on {v}", "Production runs on {v}.", "we host it on {v}"],
    "branch": ["The main branch is called {v}.", "main branch is {v}", "We merge everything into {v}.",
               "our default branch name are {v}"],
    "port": ["The dev server runs on port {v}.", "dev server port is {v}", "Locally the app listens on port {v}.",
             "we run dev on port {v}"],
    "css": ["We style the pages with {v}.", "styling is done with {v}", "The UI uses {v} for CSS.", "we use {v} for css"],
}
GENERAL_FACTS = {  # kind -> (question, statements, value); about the user or the organisation
    "answers": ("How long should your answers be?", ["I prefer short answers without emojis.",
                "i like short answer, no emoji", "Keep your answers short, I don't like long ones."], "short"),
    "editor": ("Which editor do I use?", ["My editor is Neovim.", "i use neovim as my editor",
               "I write all my code in Neovim."], "Neovim"),
    "ubuntu": ("Which Ubuntu version is on the production server?", ["Our production server runs Ubuntu 22.04.",
               "our production server are ubuntu 22.04", "Our production servers are on Ubuntu 22.04."], "22.04"),
    "name": ("What is my name?", ["My name is Dara.", "my name dara", "I'm Dara, by the way."], "Dara"),
}
# (week, project, kind, new value, message). Project "" = a general fact (said in `said_in`).
CHANGES = [  # (week, project, kind, new value, wordings)
    (2, "shop", "deploy", "Render", ["We deploy to Render now.", "we moved hosting to Render",
                                     "Production runs on Render now."]),
    (2, "api", "port", "8081", ["The dev server runs on port 8081 now.", "dev port changed to 8081",
                                "I moved the dev server to port 8081."]),
    (3, "api", "db", "DynamoDB", ["No, the database is DynamoDB now, we moved off MongoDB.",
                                  "we migrated the database to DynamoDB", "Actually our db is DynamoDB now."]),
    (3, "shop", "port", "3001", ["I moved the dev server to port 3001.", "dev server port is 3001 now",
                                 "Locally the app listens on port 3001 now."]),
    (3, "", "editor", "Helix", ["My editor is Helix now.", "I switched my editor to Helix.",
                                "i use helix now instead of neovim"]),
    (3, "", "ubuntu", "24.04", ["Our production server runs Ubuntu 24.04 now.",
                                "we upgraded the production server to Ubuntu 24.04"]),
    (4, "blog", "deploy", "Cloudflare", ["We deploy to Cloudflare now.", "the blog is hosted on Cloudflare now",
                                         "we moved the blog to Cloudflare"]),
]
GENERAL_SAID_IN = {"answers": "shop", "editor": "blog", "ubuntu": "api", "name": "shop"}

NOISE = [
    "add tests for {f}", "fix the failing test in {f}", "refactor {f} into smaller functions",
    "rename the variable x to total in {f}", "can you explain what {f} does?", "why is {f} so slow?",
    "run the linter", "commit this", "looks good, now update the README", "thanks!", "ok", "perfect",
    "no wait, undo that", "[Request interrupted by user]", "/clear", "try again", "use a dataclass instead",
    "make it async", "hmm that's not right, the test still fails", "it still fails with the same error",
    "what does this error mean?\nTraceback (most recent call last):\n  File \"{f}\", line 12, in <module>\n"
    "    main()\nKeyError: 'user_id'",
    "I think the bug is in {f}.", "I don't like this approach, try something simpler.",
    "great, that works. next, add pagination to the list endpoint",
    "This test is flaky, it passed on the second run.",
    "seem the page are slow when load {f}", "why it show error on {f}", "i want it more faster",
    "please make the table more clean", "can it support dark mode", "it work now thank",
    "I guess the cache is the problem.", "Not sure why {f} breaks.", "ok now commit and push",
    "the build passed this time", "we will look at {f} tomorrow",
    "✅ Done.\nUpdated {f} and ran the tests.", "warning: unused import in {f}\n  --> {f}:3:1",
]
FILES = ["cart.py", "models.py", "views.py", "utils.py", "auth.py", "api.py", "settings.py", "index.ts"]


@dataclass
class Msg:
    week: int
    session: str
    project: str
    text: str
    is_fact: bool


@dataclass
class Question:
    project: str
    kind: str
    text: str
    expect: str | None
    old: list[str]
    others: list[str]  # other projects' values of the same kind (must not be shown unlabelled)


@dataclass
class Scenario:
    messages: list[Msg] = field(default_factory=list)
    checkpoints: dict[int, list[Question]] = field(default_factory=dict)  # week -> questions
    long_session: str = ""


def scenario(seed: int = 7, long_prompts: int = 220) -> Scenario:
    r = random.Random(seed)
    sc = Scenario()
    cur = {(p, k): v for k, (_, vals) in PROJECT_FACTS.items() for p, v in vals.items()}
    old: dict[tuple[str, str], list[str]] = {}
    all_vals: dict[str, set[str]] = {k: set(vals.values()) for k, (_, vals) in PROJECT_FACTS.items()}
    gen_cur = {k: v for k, (_, _, v) in GENERAL_FACTS.items()}
    gen_said: set[str] = set()
    facts_said: dict[tuple[str, str], str] = {}
    for _, p, k, v, _ in CHANGES:  # noqa: B007
        if p:
            all_vals[k].add(v)

    def noise():
        return r.choice(NOISE).format(f=r.choice(FILES))

    for week in range(1, WEEKS + 1):
        facts = {p: [] for p in PROJECTS}
        if week == 1:
            for (p, k), v in cur.items():
                text = r.choice(FIRST_STATEMENT[k]).format(v=v)
                if (p, k) == ("shop", "css"):  # a fact inside a request
                    text = "hey, can you set up the cart page? fyi " + text[:1].lower() + text[1:]
                facts[p].append(text)
                facts_said[(p, k)] = text
            for k, (_, texts, _) in GENERAL_FACTS.items():
                facts[GENERAL_SAID_IN[k]].append(r.choice(texts))
                gen_said.add(k)
        if week == 2:
            facts["blog"].append(facts_said[("blog", "tests")])  # said again: must merge, not grow
        for w, p, k, v, texts in CHANGES:
            if w != week:
                continue
            text = r.choice(texts)
            if p:
                old.setdefault((p, k), []).append(cur[(p, k)])
                cur[(p, k)] = v
                facts[p].append(text)
            else:
                old.setdefault(("", k), []).append(gen_cur[k])
                gen_cur[k] = v
                facts[GENERAL_SAID_IN[k]].append(text)
        for p in PROJECTS:
            r.shuffle(facts[p])
            for s in range(2):
                sid = f"w{week}-{p}-{s}"
                n = long_prompts if (week, p, s) == (2, "shop", 0) else 12
                if n == long_prompts:
                    sc.long_session = sid
                mine = facts[p][s::2]
                slots = sorted(r.sample(range(n), len(mine)))
                fi = 0
                for i in range(n):
                    if fi < len(mine) and i == slots[fi]:
                        sc.messages.append(Msg(week, sid, p, mine[fi], True))
                        fi += 1
                    else:
                        sc.messages.append(Msg(week, sid, p, noise(), False))
        qs = []
        for p in PROJECTS:
            for k, (q, _) in PROJECT_FACTS.items():
                want = cur.get((p, k))
                others = sorted(all_vals[k] - {want} - set(old.get((p, k), [])))
                qs.append(Question(p, k, q, want, list(old.get((p, k), [])), others))
            for k in sorted(gen_said):
                q, _, _ = GENERAL_FACTS[k]
                qs.append(Question(p, k, q, gen_cur[k], list(old.get(("", k), [])), []))
        sc.checkpoints[week] = qs
    return sc


def _has(value: str, text: str) -> bool:
    return re.search(r"(?<![\w.])" + re.escape(value.lower()) + r"(?![\w])", text.lower()) is not None


def run(sc: Scenario, embedder) -> dict:
    from dore.integrations.hooks import _State, message_key, on_prompt
    from dore.memory import SEARCHABLE_SQL, MemoryStore
    d = Path(tempfile.mkdtemp(prefix="dore-stream-"))
    store = MemoryStore(d / "m.db", None, embedder)
    rows = lambda: store.db.execute("SELECT count(*) FROM memories").fetchone()[0]  # noqa: E731
    states: dict[str, _State] = {}
    work_tokens, long_tokens, hook_ms = [], [], []
    junk_msgs, junk_rows, missed, stored_per_session = [], 0, [], {}
    weekly, misses_by_week = [], {}
    t0 = time.time()
    by_week: dict[int, list[Msg]] = {}
    for m in sc.messages:
        by_week.setdefault(m.week, []).append(m)
    weeks = sorted(set(by_week) | set(sc.checkpoints))
    for week in weeks:
        for m in by_week.get(week, []):
            st = states.setdefault(m.session, _State(d, m.session))
            before = rows()
            t = time.perf_counter()
            ctx = on_prompt(store, m.text, m.project, st)
            hook_ms.append(1000 * (time.perf_counter() - t))
            added = rows() - before
            stored_per_session[m.session] = stored_per_session.get(m.session, 0) + added
            learned = message_key(m.text) in st.d.get("learned", [])
            if m.is_fact and not learned:
                missed.append(m.text)
            if not m.is_fact and learned:
                junk_msgs.append(m.text)
                junk_rows += added
            work_tokens.append(len(ctx) / 4)
            if m.session == sc.long_session:
                long_tokens.append(len(ctx) / 4)
        ok = stale = leak = q_chars = 0
        if week not in sc.checkpoints:
            continue
        misses = set()
        details = []
        t_q = time.perf_counter()
        for i, q in enumerate(sc.checkpoints[week]):
            st = _State(d, f"q{week}-{i}")
            st.d["rules_done"] = True  # measure note search; the session-start rules block is separate
            ctx = on_prompt(store, q.text, q.project, st)
            q_chars += len(ctx)
            own = "\n".join(line for line in ctx.splitlines() if "(from project" not in line)
            leaked = [v for v in q.others if _has(v, own)]
            hit = (not leaked) if q.expect is None else _has(q.expect, ctx)
            ok += hit
            stale += any(_has(v, ctx) for v in q.old)
            leak += bool(leaked)
            if not hit:
                misses.add((q.project, q.kind, q.expect))
                details.append(f"{q.project}: {q.text} (want {q.expect}"
                               + (f"; shown {', '.join(leaked)}" if leaked else "") + ")")
        misses_by_week[week] = misses
        rows_now = store.db.execute(f"SELECT count(*) FROM memories WHERE {SEARCHABLE_SQL}").fetchone()[0]
        weekly.append({"week": week, "searchable": rows_now,
                       "q_ms": 1000 * (time.perf_counter() - t_q) / max(1, len(sc.checkpoints[week])),
                       "q_tokens": q_chars / 4 / max(1, len(sc.checkpoints[week])),
                       "correct": ok, "questions": len(sc.checkpoints[week]), "stale": stale,
                       "with_old": sum(1 for q in sc.checkpoints[week] if q.old), "leak": leak,
                       "misses": details})
    cps = sorted(misses_by_week)
    repeats = sum(len(misses_by_week[a] & misses_by_week[b]) for a, b in zip(cps, cps[1:]))
    searchable = store.db.execute(f"SELECT count(*) FROM memories WHERE {SEARCHABLE_SQL}").fetchone()[0]
    total = rows()
    store.close()
    lt = long_tokens
    short_sessions = [v for s, v in stored_per_session.items() if s != sc.long_session]
    return {
        "weekly": weekly, "repeats": repeats,
        "messages": len(sc.messages), "facts": sum(m.is_fact for m in sc.messages),
        "junk_msgs": junk_msgs, "junk_rows": junk_rows, "missed": missed,
        "notes_per_session": statistics.mean(short_sessions),
        "notes_long_session": stored_per_session.get(sc.long_session, 0),
        "tokens_work": statistics.mean(work_tokens),
        "tokens_long_first": statistics.mean(lt[:50]) if lt else 0.0,
        "tokens_long_last": statistics.mean(lt[-50:]) if lt else 0.0,
        "rows": total, "searchable": searchable,
        "hook_ms_median": statistics.median(hook_ms),
        "hook_ms_p95": sorted(hook_ms)[int(0.95 * (len(hook_ms) - 1))],
        "seconds": time.time() - t0,
    }


def report(r: dict) -> str:
    out = ["| Week | Correct | Stale shown | Other-project leak |", "|---|---|---|---|"]
    for w in r["weekly"]:
        out.append(f"| {w['week']} | {w['correct']}/{w['questions']} | {w['stale']}/{w['with_old']} | {w['leak']} |")
    out += ["", "| Measure | Value |", "|---|---|",
            f"| Messages (facts) | {r['messages']} ({r['facts']}) |",
            f"| Repeat mistakes (missed 2 weeks in a row) | {r['repeats']} |",
            f"| Junk: noise messages stored | {len(r['junk_msgs'])} ({r['junk_rows']} notes) |",
            f"| Missed: fact messages not stored | {len(r['missed'])} |",
            f"| Notes stored per normal session | {r['notes_per_session']:.1f} |",
            f"| Notes stored in the long session | {r['notes_long_session']} |",
            f"| Tokens added per work prompt | ~{r['tokens_work']:.0f} |",
            f"| Long session: tokens per prompt, first 50 / last 50 | ~{r['tokens_long_first']:.0f} / "
            f"~{r['tokens_long_last']:.0f} |",
            f"| Store size (searchable) | {r['rows']} ({r['searchable']}) |",
            f"| Hook time per prompt, median / p95 | {r['hook_ms_median']:.0f} / {r['hook_ms_p95']:.0f} ms |",
            f"| Run time | {r['seconds']:.1f} s |"]
    for w in r["weekly"]:
        out += [f"miss (week {w['week']}) {m}" for m in w["misses"]]
    out += [f"junk: {t!r}" for t in dict.fromkeys(r["junk_msgs"])]
    out += [f"missed: {t!r}" for t in r["missed"]]
    return "\n".join(out)


def main(argv: list[str] | None = None):
    argv = sys.argv[1:] if argv is None else argv
    from dore.config import Config
    from dore.memory.embed import FastEmbedder
    cfg = Config()
    emb = FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed"))
    if argv and argv[0] == "seeds":  # python -m dore.eval.stream seeds [n]: mean over seeds 1..n
        n = int(argv[1]) if len(argv) > 1 else 5
        rs = [run(scenario(sd), emb) for sd in range(1, n + 1)]
        avg = lambda f: statistics.mean(f(r) for r in rs)  # noqa: E731
        print(f"| Measure (mean of seeds 1-{n}) | Value |\n|---|---|")
        for w in range(WEEKS):
            print(f"| Week {w + 1}: correct / stale / leak | {avg(lambda r: r['weekly'][w]['correct']):.1f}/"
                  f"{rs[0]['weekly'][w]['questions']} / {avg(lambda r: r['weekly'][w]['stale']):.1f} / "
                  f"{avg(lambda r: r['weekly'][w]['leak']):.1f} |")
        print(f"| Repeat mistakes | {avg(lambda r: r['repeats']):.1f} |\n"
              f"| Junk messages stored | {avg(lambda r: len(r['junk_msgs'])):.1f} of ~"
              f"{avg(lambda r: r['messages'] - r['facts']):.0f} |\n"
              f"| Fact messages missed | {avg(lambda r: len(r['missed'])):.1f} of {avg(lambda r: r['facts']):.0f} |\n"
              f"| Notes in the 220-prompt session | {avg(lambda r: r['notes_long_session']):.1f} |\n"
              f"| Tokens per work prompt | {avg(lambda r: r['tokens_work']):.1f} |")
        for i, r in enumerate(rs, 1):
            for w in r["weekly"]:
                print(*(f"seed {i} week {w['week']} {m}" for m in w["misses"]), sep="\n") if w["misses"] else None
            for t in r["missed"]:
                print(f"seed {i} missed: {t!r}")
        return
    seed = int(argv[0]) if argv else 7
    print(report(run(scenario(seed), emb)))


if __name__ == "__main__":
    main()
