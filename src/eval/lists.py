"""Long messages: lists and pastes are learned whole, noise is not; a later question gets the matching entry only.

    python -m dore.eval.lists            # word rules, and Haiku from recorded answers (0 tokens)
    python -m dore.eval.lists --live     # also asks Haiku for answers not recorded yet
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ANSWERS = Path(__file__).with_name("lists_answers.json")  # made-up messages only: safe to commit

NAMES = ["Sokha", "Dara", "Vanna", "Rithy", "Bopha", "Nimol", "Sophal", "Chenda", "Pisey", "Visal", "Kosal", "Maly",
         "Sreyleak", "Thida", "Borey", "Kanha", "Leakena", "Sambath", "Vuthy", "Navy", "Socheata", "Panha", "Rachana",
         "Seyha", "Mony", "Kunthea", "Vibol", "Sitha", "Ratana", "Dalin", "Bunthoeun", "Chantrea", "Darany", "Kimsour",
         "Leap", "Makara", "Narith", "Oudom", "Piseth", "Reaksmey", "Sopheak", "Thearith", "Udom", "Vannak", "Kolab",
         "Sreymom", "Chamroeun", "Dina", "Heng", "Linda"]
JOBS = ["nurse", "teacher", "pilot", "chef", "lawyer", "farmer", "doctor", "engineer", "dentist", "driver"]
CITIES = ["Battambang", "Kampot", "Siem Reap", "Kep", "Takeo", "Pursat", "Kratie", "Kampong Cham", "Prey Veng",
          "Koh Kong"]


def people(n: int) -> list[tuple[str, str, str]]:
    return [(NAMES[i], JOBS[i % 10], CITIES[(i * 3) % 10]) for i in range(n)]


def pasted(body: str, typed: str = "") -> str:
    return f'<pasted_content id="p1">\n{body}\n</pasted_content id="p1">' + (f"\n{typed}" if typed else "")


def _where(ps, picks):
    return [(f"Where does {ps[i][0]} live?", ps[i][2]) for i in picks]


P10, P25, P50 = people(10), people(25), people(50)
TEAM = [("Rithy", "backend lead", "rithy@example.com"), ("Bopha", "designer", "bopha@example.com"),
        ("Nimol", "QA engineer", "nimol@example.com"), ("Sophal", "mobile developer", "sophal@example.com")]
SECRET = "sk_live_51HxQbZ2eZvKYlo2C8x9TqW"

# (name, message, [(question in a later session, text the answer needs)])
LISTS = [
    ("typed bullets under a lead line, 10", "Here are my friends:\n" + "\n".join(
        f"- {n}: {j}, lives in {c}" for n, j, c in P10), _where(P10, [0, 4, 9])),
    ("typed lines, no lead line, 10", "\n".join(
        f"My friend {n} is a {j} and lives in {c}." for n, j, c in P10), _where(P10, [0, 4, 9])),
    ("one paragraph, 25 people", " ".join(
        f"My friend {n} is a {j} and lives in {c}." for n, j, c in P25), _where(P25, [0, 12, 24])),
    ("typed numbered list, 50 (over 3,000 chars)", "These are the students in my evening class:\n" + "\n".join(
        f"{k}. {n}, works as a {j}, comes from {c}, joined in {2015 + k % 9}" for k, (n, j, c) in enumerate(P50, 1)),
     _where(P50, [0, 20, 37, 49])),
    ("pasted table + what it is", pasted("\n".join(f"{n} | {r} | {e}" for n, r, e in TEAM),
                                         "these are my team members"),
     [("What is Bopha's email?", "bopha@example.com"), ("Who is the backend lead on my team?", "Rithy")]),
    ("pasted config + what it is, with a secret", pasted(
        f"DATABASE_URL=postgres://localhost:5432/shop\nREDIS_URL=redis://localhost:6379\nPORT=8080\n"
        f"STRIPE_SECRET_KEY={SECRET}", "this is the dev config of this app"),
     [("Which port does the dev server use?", "8080")]),
]

NOISE = [
    ("traceback + why", pasted(
        'Traceback (most recent call last):\n  File "app/main.py", line 42, in <module>\n    run()\n'
        '  File "app/server.py", line 17, in run\n    db.connect(timeout=5)\n'
        "sqlalchemy.exc.OperationalError: could not connect to server: Connection refused", "why does this fail?")),
    ("npm log + fix", pasted(
        "npm ERR! code ERESOLVE\nnpm ERR! ERESOLVE unable to resolve dependency tree\nnpm ERR! Found: react@18.2.0\n"
        'npm ERR! Could not resolve dependency: peer react@"^17.0.0" from some-lib@2.1.0', "fix this")),
    ("code + refactor", pasted(
        "export function total(items: Item[]): number {\n  let sum = 0;\n  for (const i of items) {\n"
        "    if (i.active) sum += i.price * i.qty;\n  }\n  return sum;\n}", "refactor this to use reduce")),
    ("typed task list", "Fix the login page:\n- make the button bigger\n- change the color to blue\n"
                        "- add a loading spinner"),
    ("typed bug list", "Bugs I found today:\n- the cart total is wrong after a refund\n- login fails on Safari\n"
                       "- the footer overlaps the menu on mobile"),
    ("pasted article + summarize", pasted(
        "Coffee is one of the most traded goods in the world.\nIt grows best in tropical highlands.\n"
        "Most beans come from two species, arabica and robusta.\nArabica is grown at higher altitudes.",
        "summarize this in two lines")),
    ("pasted summary of changes", pasted(
        "## Summary\n- Added retry with backoff to the uploader.\n- Moved config to settings.toml.\n- All tests pass.",
        "looks good")),
    ("typed story of a failed build", "The build failed again this morning.\nIt timed out after ten minutes on the "
                                      "test step.\nI restarted the runner and it passed the second time."),
]


# Work prompts with the lists' words that ask nothing about them: list text here is noise.
SIMILAR = ["add a job title field to the profile page", "the nurse role needs a new permission in the admin panel",
           "write a seed script that creates 10 fake friends", "rename the city column to town in the users table",
           "send a welcome email to new team members when they sign up", "configure the redis url for the test suite",
           "how do I validate an email address in C#?", "list all users in the database", "who is logged in right now?",
           "add a students table with name and year joined", "the teacher dashboard is slow",
           "make the designer page responsive"]


def _store(embedder):
    from dore.memory import MemoryStore
    d = Path(tempfile.mkdtemp(prefix="dore-lists-"))
    return MemoryStore(d / "m.db", None, embedder), d


def _learn(store, d, msg, mode, ask, usage):
    from dore.integrations import hooks, learner
    hooks.on_prompt(store, msg, "proj", hooks._State(d, "s1"), learn=mode)
    if mode == "haiku":
        store.db.execute("UPDATE episodes SET created=1.0")  # a session end a day later: a batch is due
        while (st := learner.run_once(store, ask=ask, ended=True)) is not None:
            u = st.get("usage") or {}
            usage["tokens"] += u.get("input", 0) + u.get("output", 0)
            usage["out"] += u.get("output", 0)
            usage["calls"] += u.get("calls", 0)


def _notes(store) -> list[tuple[int, str, str, int | None]]:
    from dore.memory import SEARCHABLE_SQL
    return store.db.execute(f"SELECT id, content, kind, group_id FROM memories WHERE {SEARCHABLE_SQL}").fetchall()


def run(mode: str, embedder, ask=None) -> dict:
    from dore.integrations import hooks
    r = {"similar": 0, "similar_asked": 0, "found": 0, "asked": 0, "chars": 0, "answered": 0, "entries": 0, "want_entries": 0, "noise": 0,
         "secret": 0, "recall_ok": 0, "groups": 0, "fails": []}
    usage = {"tokens": 0, "calls": 0, "out": 0}
    for name, msg, questions in LISTS:
        store, d = _store(embedder)
        _learn(store, d, msg, mode, ask, usage)
        notes = _notes(store)
        r["secret"] += sum(SECRET in c for _, c, _, _ in notes)
        heads = [i for i, _, k, _ in notes if k == "group"]
        r["groups"] += len(heads)
        for k, (q, want) in enumerate(questions):
            text = hooks.on_prompt(store, q, "proj", hooks._State(d, f"q{k}"), learn=mode)
            r["asked"] += 1
            if want.lower() in text.lower():
                r["found"] += 1
                r["chars"] += len(text)
                r["answered"] += 1
            else:
                r["fails"].append(f"{mode} {name}: {q} (want {want})")
        for k, q in enumerate(SIMILAR):
            r["similar_asked"] += 1
            if hooks.on_prompt(store, q, "proj", hooks._State(d, f"w{k}"), learn=mode):
                r["similar"] += 1
                r["fails"].append(f"{mode} {name}: list text for '{q}'")
        if name.startswith("typed numbered list"):
            r["want_entries"] += len(P50)
            out = hooks.recall_text(store, heads)
            got = sum(f"{n}," in out for n, _, _ in P50) if heads else 0
            r["entries"] += got
            r["recall_ok"] += got == len(P50)
        store.close()
    for name, msg in NOISE:
        store, d = _store(embedder)
        _learn(store, d, msg, mode, ask, usage)
        kept = _notes(store)
        r["noise"] += len(kept)
        r["fails"] += [f"{mode} noise kept ({name}): {c[:70]}" for _, c, _, _ in kept]
        store.close()
    r.update(usage)
    return r


def main(argv: list[str] | None = None):
    argv = sys.argv[1:] if argv is None else argv
    from dore.config import Config
    from dore.learn.judge import ClaudeCLI, Recorded
    from dore.memory.embed import FastEmbedder
    cfg = Config()
    embedder = FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed"))
    ask = Recorded(ANSWERS, ClaudeCLI() if "--live" in argv else None)
    rows = [("word rules", run("rules", embedder))]
    try:
        rows.append(("Haiku", run("haiku", embedder, ask)))
    except Exception as e:  # no recorded answer: run with --live once
        print(f"Haiku: {e}")
    n_list = sum(len(q) for _, _, q in LISTS)
    print("| Learner | Entries found by a later question | Tokens per answer | 50-entry list via recall | "
          "Noise notes stored | Secrets stored | Similar-word work prompts given list text | Haiku tokens (calls) |")
    print("|---|---|---|---|---|---|---|---|")
    for label, r in rows:
        tok = r["chars"] / 4 / max(1, r["answered"])
        print(f"| {label} | {r['found']}/{n_list} | ~{tok:.0f} | {r['entries']}/{r['want_entries']} | "
              f"{r['noise']} (of {len(NOISE)} messages) | {r['secret']} | {r['similar']}/{r['similar_asked']} | "
              f"{r['tokens']} ({r['calls']}) |")
    for label, r in rows:
        if r["tokens"]:
            print(f"{label}: {r['tokens'] / r['calls']:.0f} tokens per call, {r['out'] / r['calls']:.0f} of them output")
    for _, r in rows:
        for f in r["fails"]:
            print("  " + f)


if __name__ == "__main__":
    main()
