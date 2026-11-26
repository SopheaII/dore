"""Text rules on memory notes (no model): duplicates, keywords, and when a new note is the
same fact as an old one with one detail changed (`same_frame`) or replaces it (`replaces`)."""

from __future__ import annotations

import re

STOPWORDS = frozenset("""a an the is are am was were be been being do does did i me my mine you your yours we our
he she it its they them their what which who whom whose where when why how this that these those of in on at to
for from by with about as and or not no yes can could will would should shall may might must have has had
there here please tell know any some""".split())

_WORD = re.compile(r"[a-z0-9]+(?:[.:/-][a-z0-9]+)*")


def _signature(text: str) -> frozenset[str]:
    """Set of words and numbers of a text, ignoring case and punctuation (keyword matching)."""
    return frozenset(_WORD.findall(text.lower()))


def _dup_key(text: str) -> tuple[str, ...]:
    """Words and numbers of a text IN ORDER, ignoring case and punctuation. Two texts are only
    merged as duplicates when these match: embeddings alone score "server IP 10.0.0.5" vs
    "10.0.0.6" at 0.985, and a word set alone merged "Alice reports to Bob" with "Bob reports
    to Alice" (probe 2026-11-25)."""
    return tuple(_WORD.findall(text.lower()))


_NEGATION = frozenset("not no never don t doesn didn isn aren wasn won do does".split())


# Time and emphasis words are not a detail: "Our server now runs on port 9443" updates "Our server
# runs on port 8443" (the extra "now" made them look like two changes; long-conversation test 2026-11-25).
FRAME_FILLER = frozenset("now currently still actually nowadays presently today anymore".split())
_FILLER_RE = re.compile(r"\s*\b(?:" + "|".join(sorted(FRAME_FILLER)) + r")\b", re.I)


def embed_text(text: str) -> str:
    """The text a note is embedded as: without time words ("My editor is Helix now" scored 0.638
    for "Which editor do I use?", below the hook's 0.65; without "now" 0.678). Stored text is unchanged."""
    return _FILLER_RE.sub("", text).strip() or text


# Who said it and why are not the fact: "Finance decided the max discount is 50% because ..." holds
# the same fact as "The max discount is 40%, finance changed it" with one detail changed.
LEAD_IN = re.compile(r"^(?:[\w'-]+\s+){0,3}?(?:decided|said|says|confirmed|agreed|announced|mentioned|"
                     r"told (?:me|us)|thinks?)\s+(?:that\s+)?", re.I)
CLAUSE_REST = re.compile(r"(?:\s*[,;(]|:\s|\s+(?:because|since|so|but|which|unless|although|though)\s).*$",
                         re.I | re.S)


def _main_clause(text: str) -> str:
    """The first clause of a sentence without a reporting lead-in ("X decided that ...")."""
    return LEAD_IN.sub("", CLAUSE_REST.sub("", text.strip(), count=1), count=1)


def _frame(old: str, new: str) -> tuple[tuple, tuple, tuple]:
    """(shared words, changed part of old, changed part of new): the words both texts share
    at the start and the end, and what differs in between (time words like "now" ignored)."""
    a = tuple(w for w in _dup_key(old) if w not in FRAME_FILLER)
    b = tuple(w for w in _dup_key(new) if w not in FRAME_FILLER)
    p = 0
    while p < min(len(a), len(b)) and a[p] == b[p]:
        p += 1
    q = 0
    while q < min(len(a), len(b)) - p and a[-1 - q] == b[-1 - q]:
        q += 1
    return a[:p] + a[len(a) - q:], a[p:len(a) - q], b[p:len(b) - q]


# A changed detail after these words replaces the old one ("I live in X" -> "I live in Y");
# after the MULTI ones both can be true at once ("I have a dog Buddy" + "I have a dog Max";
# Mem0's model deleted the first dog in exactly this case).
SINGLE_VALUE = frozenset("""is am are was were m s live lives living work works working moved move use uses
using prefer prefers runs run running called named name born""".split())
MULTI_VALUE = frozenset("""have has had got get like likes love loves enjoy also another and or visited know knows
friend friends kid kids child children brother brothers sister sisters cousin cousins colleague colleagues
pet pets""".split())


# Prepositions mark a role: "We use pytest for tests" and "We use ruff for linting" are two facts.
PREPOSITIONS = frozenset("for in on at to from with by of into onto about via per under over".split())
# "<someone> <verb> <the/my thing> to <value>": the thing's value changed, whatever the verb
# ("I switched my editor to Helix", "We moved the database to MySQL").
CHANGE_TO = re.compile(r"^\s*\S+\s+(?:\S+\s+)?\S+\s+((?:my|our|the|its|their)\s+[^,;]+?)\s+to\s+(?:an?\s+|the\s+)?"
                       r"([^,;]+?)[.!]?\s*$", re.I)


def _as_state(text: str) -> str:
    """"I switched my editor to Helix" -> "my editor is Helix"; other text unchanged."""
    m = CHANGE_TO.match(text)
    return f"{m.group(1)} is {m.group(2)}" if m else text


def _value_like(part: tuple, original: str) -> bool:
    """A changed part that is one concrete value: at most 2 words, no preposition, and a name,
    number or identifier ("Render", "35", "tf-state-eu"), not an ordinary word."""
    part = tuple(w for w in part if w not in ("a", "an", "the"))
    if not part or len(part) > 2 or set(part) & PREPOSITIONS:
        return False
    for w in part:
        if any(c.isdigit() for c in w) or any(c in ".:/-_" for c in w):
            continue
        # Written with a capital letter somewhere other than the start of the sentence = a name.
        if not any(m.start() > 0 and any(c.isupper() for c in m.group())
                   for m in re.finditer(r"\b" + re.escape(w) + r"\b", original, re.I)):
            return False
    return True


def replaces(old: str, new: str) -> bool:
    """True when `new` is an update of `old`: one detail changed (`same_frame`) in a sentence
    that can only hold one value at a time. Unclear cases return False: both are kept."""
    pair = _frame_pair(old, new)
    rewritten = pair is None
    if rewritten:
        pair = _frame_pair(_as_state(old), _as_state(new))
    if pair is None:
        return False
    shared, da, db = _frame(*pair)
    if rewritten and not (_value_like(da, pair[0]) and _value_like(db, pair[1])):
        return False  # "I sent the report to Dara" is not a new value of "The report is due on Friday"
    if set(shared) & MULTI_VALUE:
        return False
    # Different roles: "for tests" vs "for linting".
    pa = [i for i, w in enumerate(da) if w in PREPOSITIONS]
    pb = [i for i, w in enumerate(db) if w in PREPOSITIONS]
    if pa and pb and da[pa[0]:] != db[pb[0]:]:
        return False
    if (not da or not db) and set(da or db) <= _NEGATION:  # "Use tabs" -> "Do not use tabs"
        return bool(set(shared) & SINGLE_VALUE)
    # The changed detail must come after the verb ("I live in X" -> "I live in Y"). A change
    # before it is a different subject: "Sophal works on the mobile team" is not an update of
    # "Piseth works on the mobile team" (it replaced it; long-conversation test 2026-11-25).
    a = [w for w in _dup_key(pair[0]) if w not in FRAME_FILLER]
    b = [w for w in _dup_key(pair[1]) if w not in FRAME_FILLER]
    prefix = []
    for x, y in zip(a, b):
        if x != y:
            break
        prefix.append(x)
    if set(prefix) & SINGLE_VALUE:
        return True
    # Any other verb ("deploy to", "targets SDK", "resets every"): an update when what changed
    # is one concrete value on both sides, after a subject and verb that stayed the same.
    # Only states, not events: "We fixed bug 12" and "We fixed bug 13" are two facts (past tense
    # piles up), "Builds target Node 18" -> "Node 20" is one state that changed.
    if any(w.endswith("ed") for w in prefix):
        return False
    return len(prefix) >= 2 and _value_like(da, pair[0]) and _value_like(db, pair[1])


def _frame_pair(old: str, new: str, max_change: int = 3) -> tuple[str, str] | None:
    """The pair of texts that are the same frame: the whole sentences, else their main clauses
    (only the FIRST clause, so "We run Ubuntu 22, and we use Postgres 15" is not replaced as a
    whole by "We use Postgres 16"). None if neither matches."""
    if _same_frame(old, new, max_change):
        return old, new
    o, n = _main_clause(old), _main_clause(new)
    if (o, n) != (old.strip(), new.strip()) and _same_frame(o, n, max_change):
        return o, n
    return None


def same_frame(old: str, new: str, max_change: int = 3) -> bool:
    """True when `new` is `old` with one detail changed, comparing whole sentences or, failing
    that, their main clauses (see `_frame_pair`)."""
    return _frame_pair(old, new, max_change) is not None


def _same_frame(old: str, new: str, max_change: int = 3) -> bool:
    """True when `new` is `old` with one detail changed: same words before and after, and only
    a short part different ("My car is a Toyota" -> "My car is a Honda", "Use tabs" -> "Do not
    use tabs"). Used to decide which notes a correction replaces, so "I bought my car in 2020"
    is not marked wrong by "My car is a Honda". Limit: it can't tell kinds of detail apart
    ("My car is red" -> "My car is a Honda" also matches)."""
    shared, da, db = _frame(old, new)
    if not da and not db:
        return False  # same words: a repeat, not a change
    if len(da) > max_change or len(db) > max_change or len(shared) < 2:
        return False
    if not da or not db:  # one side only adds words: a change only if it is a negation
        return set(da or db) <= _NEGATION
    if any(c.isdigit() for c in "".join(da)) != any(c.isdigit() for c in "".join(db)):
        return False  # a number replaced by a word (or back) is a different detail
    return True


def _jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a or b else 1.0


def _query_terms(text: str) -> list[str]:
    """Words and identifiers of a query worth matching by keyword (no stopwords)."""
    return [t for t in dict.fromkeys(_WORD.findall(text.lower())) if t not in STOPWORDS and len(t) > 1]


def _is_identifier(term: str) -> bool:
    """Codes, IPs, versions, ports...: exact matches on these matter more than meaning."""
    return any(c.isdigit() for c in term) or any(c in ".:/-" for c in term)


# Words that say "this replaced that" (a closed class of change-of-state markers).
CHANGE_WORDS = frozenset("""now switched switch switching moved move migrated migrate changed change replaced
replace instead anymore longer upgraded upgrade downgraded actually""".split())
# Light verbs carry no topic: "Logins use Auth0" is about logins.
LIGHT_VERBS = frozenset("use uses used using run runs running go goes through via need needs requires".split())
# Self-references carry no topic: "This project needs Node 24" is about Node.
GENERIC = frozenset("project app application repo repository codebase here locally this".split())
_VERBISH = SINGLE_VALUE | LIGHT_VERBS | frozenset("is are was were".split())


def _topic(text: str) -> set[str]:
    """Topic words of a note (4-letter stems): no stopwords, prepositions, change or light words, values."""
    out = set()
    words = _WORD.findall(text.lower())
    # The subject is what comes before the first verb ("The API runs on ...": API is the topic; "We use
    # SQS for queues": SQS is a value). Without a known verb, the first three words.
    verb = next((i for i, w in enumerate(words) if w in _VERBISH), 3)
    # "We moved CI to Buildkite": what was changed (before "to") is the topic, after "to" the value.
    change = next((i for i, w in enumerate(words) if w in CHANGE_WORDS), None)
    if change is not None and "to" in words[change:]:
        verb = change + words[change:].index("to")
    for i, w in enumerate(words):
        if (w in STOPWORDS or w in PREPOSITIONS or w in CHANGE_WORDS or w in LIGHT_VERBS or w in FRAME_FILLER
                or w in GENERIC or len(w) < 2):
            continue
        if _value_like((w,), text) and (i >= verb or any(c.isdigit() for c in w)):
            continue
        # Identifiers are compared whole: "billing-api" and "billing-worker" are two services.
        out.add(w if any(c in ".:/-_" for c in w) or any(c.isdigit() for c in w) else w[:4])
    return out


def _values(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if _value_like((w,), text)}


# "instead of X", "off X", "from X", "rather than X": X is what was left (closed class of prepositions).
_LEFT = r"(?:instead of|rather than|away from|off|from)\s+(?:the |our |my |using )?"
# "from X" alone is often not a change of value ("I moved the meeting from Monday" is about the meeting,
# not "Standup is on Monday"): only "from X to Y" counts (`_names_old_value`).


def _names_old_value(old: str, new: str, topic_old: set) -> bool:
    """`new` says it left the old note's value ("i use helix now instead of neovim" after "My editor is
    Neovim"; "we moved off MongoDB" after "Our db are MongoDB"), with no other topic: at most one new
    topic word (the new value or a synonym of the old topic), two when the old topic is named again.
    "The nightly backup moved off Jenkins" names other things (nightly, backup): "We run CI on Jenkins"
    is kept."""
    for v in _values(old):
        m = re.search(r"\b" + _LEFT + re.escape(v) + r"\b", new, re.I)
        if m and m.group(0).lower().startswith("from") and not re.match(r"\s+to\b", new[m.end():], re.I):
            m = None
        if m:
            topic_new = _topic(new[:m.start()] + new[m.end():])  # without "off <old value>"
            return len(topic_new - topic_old) <= (2 if topic_old & topic_new else 1)
    return False


def changes(old: str, new: str) -> bool:
    """True when `new` says, in other words, that the value in `old` changed: it has a change word
    ("We switched the cache to Redis" after "We cache with Memcached"), covers every topic word of
    `old`, and both name a concrete value that differs. Multi-value verbs keep both. Only called for
    notes already close in meaning (`MemoryStore._supersede`)."""
    words = set(_WORD.findall(new.lower()))
    if not words & CHANGE_WORDS or words & MULTI_VALUE or set(_WORD.findall(old.lower())) & MULTI_VALUE:
        return False
    topic_old, topic_new = _topic(old), _topic(new)
    if _names_old_value(old, new, topic_old):
        return True
    # Most of the old topic must be named again ("dev server port" -> "dev port"; "API ... port" is not
    # covered by "dev server port").
    if not topic_old or len(topic_old & topic_new) / len(topic_old) < 0.6:
        return False
    if any(any(c in ".:/-_" or c.isdigit() for c in w) for w in topic_old - topic_new):
        return False  # a named thing ("search-api") must be the same thing
    va, vb = _values(old), _values(new)
    return bool(va) and bool(vb) and va != vb and not vb <= va
