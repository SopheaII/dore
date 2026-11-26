"""Rules check: standing rules ("never use tabs", "always answer short") in every case we could think of.

    python -m dore.eval.rules        # ~15 s, real embedder, throw-away stores, no LLM

Messages go through `hooks.on_prompt` exactly as in Claude Code: rules are learned from what the user types,
then each check opens new sessions and reads what the hook adds. Each case passes or fails; "known gap" cases
print what happens without failing. Then the token cost of rules per session, by number of proven rules
(the README promises "only the notes that match your message (usually none)", so rules must stay small).
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

HEADER = "dore memory (use if relevant; trust user code/instructions over it):\n"
WORK = ["rename the variable total in cart.py", "add a docstring to calc()", "fix the typo in the footer",
        "write a unit test for parse_date", "split utils.py into two files", "update the changelog"]
# Ordinary replies of a coding assistant (invented), so the word statistics are not empty. None of them may
# contain a rule's words: the checks read these statistics, and replies written to match the rules made them pass.
REPLIES = ["I renamed the variable and ran the tests; all pass.", "Fixed: the loop now stops at the last item.",
           "I added a unit test for parse_date and fixed the typo.", "The build is green after the rebase.",
           "I split utils.py into two modules and updated the imports.", "Done: the changelog lists the new endpoint.",
           "The query was slow because of a missing index; I added one.", "I moved the helper into its own file.",
           "I wrote the docstring for calc().", "The CSS grid now wraps on small screens."] * 3
# Distinct, realistic rules (and a question that matches each), for the over-budget cases.
MANY = ["never commit secrets, keep them in the vault", "always write tests for new endpoints",
        "never use print for logging, use the logger", "always pin dependency versions",
        "never use global variables in services", "always handle errors from the payment api",
        "never store passwords in plain text", "always add type hints to public functions",
        "never call the database from the view layer", "always use utc for timestamps",
        "never block the event loop with sync io", "always paginate list endpoints",
        "never return raw sql errors to clients", "always validate user input at the edge",
        "never hardcode urls, put them in config", "always keep functions under fifty lines",
        "never catch bare exceptions", "always use feature flags for risky changes",
        "never delete data, mark it archived", "always write commit messages in english"]
ASK = ["where should I keep secrets?", "do new endpoints need tests?", "can I use print for logging?",
       "should I pin dependency versions?", "can I use a global variable in this service?",
       "what do I do with errors from the payment api?", "how should passwords be stored?",
       "do public functions need type hints?", "can the view call the database directly?",
       "which timezone for timestamps?", "can I do sync io in the event loop?", "should list endpoints paginate?",
       "can I return the sql error to the client?", "where do we validate user input?",
       "can I hardcode this url?", "how long can a function be?", "can I catch a bare exception?",
       "do risky changes need a feature flag?", "can I delete this data?", "which language for commit messages?"]
# The old block's most: up to 6 rules in one message, 600 characters of lines plus the header line.
OLD_MAX_TOKENS = round((600 + len(HEADER)) / 4)


class World:
    """A throw-away store and sessions, as Claude Code would drive the hook."""

    def __init__(self, embedder):
        from dore.memory import MemoryStore
        self.dir = Path(tempfile.mkdtemp(prefix="dore-rules-"))
        self.store = MemoryStore(self.dir / "m.db", self.dir / "m.faiss", embedder)
        self.n = 0
        from dore.integrations.hooks import reply_words
        for r in REPLIES:  # Claude's earlier replies on this machine (word statistics, `hooks.about_work`)
            self.store.count_reply(reply_words(r))

    def session(self):
        from dore.integrations.hooks import _State
        self.n += 1
        return _State(self.dir, f"s{self.n}")

    def say(self, text, project="p", st=None, reply="", actions=""):
        """One message; `reply`/`actions`: Claude's text and what it did in its answer to the previous message
        of this session. Returns what the hook adds."""
        from dore.integrations.hooks import on_prompt
        st = st or self.session()
        out = on_prompt(self.store, text, project, st, reply=reply, actions=actions)
        st.save()
        return out

    def later(self, days):
        """Time passes: every note was said and used `days` earlier than it was."""
        d = days * 86400
        self.store.db.execute("UPDATE memories SET created=created-?, last_seen=last_seen-?, last_used=last_used-?",
                              (d, d, d))
        self.store.db.commit()

    def work(self, actions, project="p"):
        """A session where Claude's answer did `actions` (judged when the next message comes)."""
        st = self.session()
        self.say("next task please", project, st=st)
        self.say("thanks, one more", project, st=st, reply="Done.", actions=actions)

    def start(self, project="p", first=WORK[0]):
        """What a new session's first work message gets."""
        return self.say(first, project)

    def age(self, contains, days):
        """Pretend the note was said `days` ago (first and last time)."""
        t = time.time() - days * 86400
        self.store.db.execute("UPDATE memories SET created=?, last_seen=? WHERE content LIKE ?",
                              (t, t, f"%{contains}%"))
        self.store.db.commit()


def proven(w, text, project="p"):
    """The user says a rule in two different sessions."""
    w.say(text, project)
    w.say(text, project)


def cases(embedder):
    out = []

    def check(name, ok, detail="", gap=False):
        out.append((name, bool(ok), detail, gap))

    w = World(embedder)
    w.say("never use tabs in this repo, always 2 spaces")
    check("said once: not at a session start", "tabs" not in w.start())
    check("said once: shown when a question matches", "tabs" in w.say("should I use tabs or spaces here?"))
    w.say("never use tabs in this repo, always 2 spaces")
    check("said again in another session: starts sessions", "tabs" in w.start())

    w = World(embedder)
    st = w.session()
    w.say("never use tabs in this repo, always 2 spaces", st=st)
    w.say("ok and remember: never use tabs in this repo, always 2 spaces", st=st)
    check("said twice in one session: still on trial", "tabs" not in w.start(),
          "a repeat inside one session is the same moment, not lasting evidence")

    w = World(embedder)
    proven(w, "never use tabs in this repo, always 2 spaces")
    st = w.session()
    first = w.say(WORK[0], st=st)
    later = "".join(w.say(m, st=st) for m in WORK[1:])
    check("shown once per session, not on every message", "tabs" in first and "tabs" not in later)

    w = World(embedder)
    proven(w, "never use tabs in this repo, always 2 spaces")
    w.age("never use tabs", 200)
    check("not repeated for 200 days: fades from the session start", "tabs" not in w.start())
    check("faded: still found when a question matches", "tabs" in w.say("can I indent with tabs?"))

    w = World(embedder)
    for _ in range(5):
        w.say("never use tabs in this repo, always 2 spaces")
    w.age("never use tabs", 200)
    check("said 5 times, 200 days ago: still in mind (spacing effect)", "tabs" in w.start())

    w = World(embedder)
    proven(w, "always use 2 spaces for indentation")
    proven(w, "always use 4 spaces for indentation now")
    s = w.start()
    check("a changed rule: only the new one", "4 spaces" in s and "2 spaces" not in s, s.replace(HEADER, ""))

    w = World(embedder)
    proven(w, "in this repo never push straight to main", project="shop")
    proven(w, "here we always squash commits before merging", project="shop")
    proven(w, "I prefer short answers without emojis", project="shop")
    s = w.start(project="blog")
    check("a rule said for this repo stays in its project", "push straight" not in s and "squash" not in s,
          s.replace(HEADER, ""))
    check("a rule about the user reaches every project", "short answers" in s, s.replace(HEADER, ""))

    w = World(embedder)
    proven(w, "I don't like coffee in the morning")
    check("a personal 'don't' is not a work rule", "coffee" not in w.start())

    w = World(embedder)
    w.say("do not get error and reason from error this should be status yo sentry")
    check("a complaint shaped like a rule, said once: not at a session start", "sentry" not in w.start())

    w = World(embedder)
    long_rule = ("never change the public API of the billing module without a deprecation period of two releases, "
                 "and always keep the old endpoints working until every client has moved to the new ones")
    proven(w, long_rule)
    s = w.start()
    check("a long rule is shown whole, never cut", "every client has moved" in s and "…" not in s)

    w = World(embedder)
    proven(w, "never upload files over 10 MB")
    s = w.say("can I upload files over 10 MB?")
    check("a note that is also a rule is shown once", s.count("10 MB") == 1, s.replace(HEADER, ""))

    # Noise must never become a rule, however often it is said.
    w = World(embedder)
    for _ in range(5):
        st = w.session()
        for m in ("yes", "ok", "yes please", "ok do it", "thanks", "continue"):
            w.say(m, st=st)
    n = w.store.db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    check("'yes', 'ok', 'continue' said in every session: no note, no rule", n == 0 and w.start() == "", f"{n} notes")
    w = World(embedder)
    long_request = ("please review the pull request again and make sure the comments are fixed and do not touch the "
                    "formatting of the files that are not part of this change")
    w.say(long_request)
    w.say(long_request)  # said again in another session: a repeated request, still not a session-start rule
    check("a long request repeated in another session does not start sessions", "review the pull" not in w.start())
    w = World(embedder)
    for _ in range(3):
        w.say("please commit and push this for me")
    check("a request repeated in three sessions does not start sessions", "commit" not in w.start())
    w = World(embedder)
    proven(w, "I like jazz music")
    check("a taste said twice is not a rule", "jazz" not in w.start())
    w = World(embedder)
    proven(w, "we decided to keep the cart in redis")
    check("a fact said twice is not a rule (found when asked)", "redis" not in w.start()
          and "redis" in w.say("where do we keep the cart?"))
    w = World(embedder)
    proven(w, "never use tabs in this repo, always 2 spaces")
    st = w.session()
    outs = [w.say(f"{WORK[k % len(WORK)]} (step {k})", st=st) for k in range(60)]
    later = sum(len(o) for o in outs[1:])
    check("a 60-message session: rules come once, nothing added later", "tabs" in outs[0] and later == 0,
          f"{later} characters after the first message")

    w = World(embedder)
    w.say("the api runs on port 8080")
    for k in range(15):
        proven(w, f"never import the legacy module number {k} in new code")
    s = w.say("what port does the api use?")
    check("a note that answers the first message is not pushed out by rules", "8080" in s)

    w = World(embedder)
    for r in MANY:
        proven(w, r)
    proven(w, "never run database migrations on fridays")
    s = w.start(first="write a database migration for the users table")
    check("over budget: the rule closest to the first message wins", "fridays" in s)
    st = w.session()
    seen = "".join(w.say(m, st=st) for m in WORK).lower()
    left = [r for r in MANY if r.split(",")[0] not in seen]
    q = {r: a for r, a in zip(MANY, ASK)}
    found = [r for r in left[:5] if r.split(",")[0] in w.say(q[r], st=st).lower()]
    check("over budget: rules left out are still found when a message matches", left and len(found) == len(left[:5]),
          f"{len(found)} of {len(left[:5])} found")

    # Reinforced by practice: a habit grows by being done, not by being shown or repeated.
    for name, rule, acts, stays in [
            ("a rule Claude keeps practising stays without being repeated", "always use pnpm",
             "pnpm add lodash", True),
            ("the same rule, not practised: fades", "always use pnpm", "git status", False),
            ("a never-rule followed silently still fades (doing nothing leaves no trace)",
             "never use tabs in this repo", "def f():\n    return 1", False),
            ("breaking a rule is not practice", "never use print for logging, use the logger",
             "print('debug value')", False),
            ("following a never-rule's alternative is practice", "never use print for logging, use the logger",
             "logger.info('debug value')", True)]:
        w = World(embedder)
        proven(w, rule)
        w.later(110)                 # close to fading (said twice: ~120 days)
        w.work(acts)                 # one session where Claude did this
        w.later(100)                 # 100 more days without the user repeating it
        word = rule.split()[-1]
        check(name, (word in w.start()) == stays)

    w = World(embedder)
    w.say("the reader should count pages even when you go back to an old page")
    for _ in range(3):  # Claude implements the request over several sessions
        w.work("def count_pages(reader):\n    # count pages even when going back to an old page\n    ...")
    check("a request Claude implemented does not become a rule", "count pages" not in w.start().lower())

    w = World(embedder)
    proven(w, "always use pnpm")
    st = w.session()
    w.say("add lodash", st=st)
    for k in range(3):
        w.say(f"and package {k}", st=st, reply="Done.", actions=f"pnpm add pkg{k}")
    uses = w.store.db.execute("SELECT uses FROM memories WHERE content LIKE '%pnpm%'").fetchone()[0]
    check("practised many times in one session counts once", uses == 1, f"uses {uses}")

    w = World(embedder)
    w.say("you said 'never use tabs', why is that?")
    s = w.start()
    check("quoting a rule is not giving one", "tabs" not in s, "dore can't tell quoting from giving", gap=True)
    return out


def budget(embedder, counts=(3, 6, 10, 20, 40)):
    """Tokens rules add to one session of work messages, by number of proven rules."""
    rows = []
    for n in counts:
        w = World(embedder)
        for k in range(n):
            text = f"never import the legacy module number {k} in new code"
            i = w.store.add(text, kind="statement", source="user", trust="verified", project="p")
            w.store.db.execute("UPDATE memories SET times_seen=2 WHERE id=?", (i,))
            from dore.integrations.hooks import mark_instructions
            mark_instructions(w.store, [i])
        w.store.db.commit()
        st = w.session()
        outs = [w.say(m, st=st) for m in WORK * 3]
        rows.append((n, sum(len(o) for o in outs) / 4, sum(bool(o) for o in outs)))
    return rows


def main(argv: list[str] | None = None):
    from dore.config import Config
    from dore.memory.embed import FastEmbedder
    cfg = Config()
    emb = FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed"))
    t = time.time()
    res = cases(emb)
    print("| Case | Result |\n|---|---|")
    for name, ok, detail, gap in res:
        mark = ("known gap: " if gap else "") + ("pass" if ok else "FAIL")
        print(f"| {name} | {mark}{' (' + detail + ')' if detail and not ok else ''} |")
    scored = [r for r in res if not r[3]]
    print(f"\n{sum(r[1] for r in scored)}/{len(scored)} cases pass ({time.time() - t:.0f} s)\n")
    print(f"| Proven rules | Tokens per session from rules | Messages with rules | Within the old {OLD_MAX_TOKENS} |")
    print("|---|---|---|---|")
    for n, tokens, msgs in budget(emb):
        print(f"| {n} | {tokens:.0f} | {msgs} | {'yes' if tokens <= OLD_MAX_TOKENS else 'NO'} |")


if __name__ == "__main__":
    main(sys.argv[1:])
