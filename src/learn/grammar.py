"""Is a sentence a lasting fact? Decided by its spaCy parse (structure and small closed word classes), not topic lists. English only."""

from __future__ import annotations

import re

_NLP = None
_TRIED = False

SUBJ = {"nsubj", "nsubjpass", "expl", "csubj", "csubjpass"}
WH = {"WDT", "WP", "WP$", "WRB"}
DEICTIC = {"it", "this", "that", "these", "those", "they", "he", "she", "which", "what", "everything", "something"}
DEICTIC_DET = {"this", "that", "these", "those"}
FIRST = {"i", "we"}
VOLITION = {"want", "need", "wanna", "wish", "hope", "plan", "gon"}  # wanting = a request for now
# Belief, perception and attempt verbs (the whole cognition class, not words seen in one test):
# "I think/suspect/saw X" reports a passing state of mind, not a fact.
MENTAL = {"think", "guess", "feel", "believe", "suppose", "assume", "suspect", "reckon", "presume", "figure",
          "fear", "sense", "gather", "wonder", "doubt", "bet", "expect", "imagine", "understand", "mean", "see",
          "saw", "notice", "realize", "realise", "worry", "try", "get", "forget", "miss", "confuse", "know"}
UNSURE = {"sure", "certain", "confused", "lost", "worried", "afraid"}
PERCEPTION = {"look", "seem", "sound", "appear", "feel"}
STANDING = {"always", "never", "ever", "usually", "every"}  # "Always use spaces" is a rule, not a request
POLITE_WORDS = ("please", "pls", "plz", "kindly")


class _Polite:
    """Politeness markers, misspelt too ("pleaes", "plese", "pleasee"): by spelling closeness, not a list."""

    @staticmethod
    def match(word: str) -> bool:
        w = word.lower()
        if w in POLITE_WORDS:
            return True
        if not 5 <= len(w) <= 8 or w[0] != "p" or "l" not in w:
            return False
        from difflib import SequenceMatcher
        return SequenceMatcher(None, w, "please").ratio() >= 0.8


POLITE = _Polite()
CLAUSES = {"conj", "parataxis"}
REASON = {"since", "because", "as", "cause", "coz", "cuz", "bc"}  # "fix X since we host on Y": Y is background
UNCERTAIN = {"may", "might", "could"}  # possibility, not a fact
INTENT = {"can", "could", "will", "would", "'ll", "shall", "might", "may", "wo", "ca"}  # "I can push it later"
FUTURE = {"will", "would", "'ll", "shall", "wo"}  # "the card will have ..." describes what is wanted, not what is
PRONOUN_OBJ = {"it", "this", "that", "them", "these", "those"}
# "..., right" / "... or not" at the end: a question written as a statement.
TAG_QUESTION = re.compile(r"(?:,\s*(?:right|correct|yes|no|ok|okay)|\bor (?:not|no|what|nah))\s*[?.!]*\s*$", re.I)
# Where a polite request ends and a separate clause can start.
SEGMENT = re.compile(r"\s*[,;:](?!\d)\s*|\s+(?=(?:so|since|because|but|and|as)\s)", re.I)
CUT_AT = {"but", "so", "because", "since", "though", "although", "however"}
MAX_FACT_WORDS = 20  # lasting facts are short (longest in the test sets: 14); longer = a run-on
SUBORDINATE = {"because", "since", "after", "before", "when", "whenever", "while", "if", "unless", "although",
               "though", "until", "once", "so", "cause", "coz", "cuz", "bc"}
# Standing "don't" instructions are lasting preferences, polite or not ("please don't reformat existing
# code", "i don't want debug logs in commits", "do not touch the payment module"): found as repeated in real use.
STANDING_DONT = re.compile(r"^(?:(?:please|pls|plz|kindly)\s+)?(?:(?:i|we)\s+(?:really\s+)?(?:don'?t|do not|never)\s+"
                           r"(?:want|need|like)\b|(?:don'?t|dont|do not|never|no need to|stop)\s+\w+)", re.I)
# Tied to the moment: not a lasting rule ("I don't want to change the code right now").
MOMENT = re.compile(r"\b(?:right now|for now|now|yet|this time|today|tonight|anymore|at the moment|keep going)\b", re.I)
FIRST_PERSON_START = re.compile(r"^(?:i|i'm|we|we're|my|our)\b", re.I)
CONNECTIVE = re.compile(r"^(?:so|since|because|but|and|as)\s+", re.I)


class _Cached:
    """The parser with recent parses cached: several checks read the same sentence. Docs are read-only."""

    def __init__(self, pipeline, size: int = 256):
        from functools import lru_cache
        self._pipeline = pipeline
        self._parse = lru_cache(maxsize=size)(pipeline)

    def __call__(self, text: str):
        return self._parse(text)

    def __getattr__(self, name):
        return getattr(self._pipeline, name)


def nlp():
    """The parser, loaded once (~0.5 s); None if spaCy or its English model is not installed."""
    global _NLP, _TRIED
    if not _TRIED:
        _TRIED = True
        try:
            import spacy
            # md, not sm: sm read "The auth-web service runs on port 7710" as a noun phrase and lost
            # the fact (2026-11-25); md costs the same per sentence (~1 ms), ~0.6 s to load once.
            _NLP = _Cached(spacy.load("en_core_web_md", disable=["ner"]))
        except Exception:  # not installed: callers fall back to word rules
            _NLP = None
    return _NLP


def _detail(tokens, strong: bool = False) -> bool:
    """A concrete detail: a name, number, version, path or other identifier. `strong` leaves out
    words only unknown to the vocabulary (they may be typos: "readign")."""
    for t in tokens:
        w = t.text
        if t.pos_ in ("PROPN", "NUM") or t.like_num or any(c.isdigit() for c in w):
            return True
        # Not an English word the model knows: most likely a name ("vitest", "neovim", "pnpm").
        if not strong and t.is_alpha and len(w) > 3 and t.is_oov and t.has_vector is False:
            return True
        if re.search(r"\w[./:_@-]\w|^[/~.]\w", w) or (w.isupper() and len(w) > 1) or re.search(r"[a-z][A-Z]", w):
            return True
    return False


def _clause_tokens(head, skip_clauses: bool = True):
    """Tokens of the clause headed by `head`, without its own conj/parataxis sub-clauses."""
    out, stack = [], [head]
    while stack:
        t = stack.pop()
        out.append(t)
        stack += [c for c in t.children if not (skip_clauses and c.dep_ in CLAUSES and c.pos_ in ("VERB", "AUX"))]
    return sorted(out, key=lambda t: t.i)


def _close(word: str, vocab: set) -> bool:
    """`word` is in `vocab`, or a misspelling of one of its words (same first letter, similar spelling)."""
    if word in vocab:
        return True
    if len(word) < 4:
        return False
    from difflib import SequenceMatcher
    return any(v[0] == word[0] and abs(len(v) - len(word)) <= 1 and SequenceMatcher(None, word, v).ratio() >= 0.75
               for v in vocab if len(v) >= 4)


def _content(t) -> bool:
    """Misspellings are matched only for content words: "with" is not a misspelt "wish"."""
    return t.pos_ in ("VERB", "NOUN", "ADJ", "PROPN", "X", "INTJ", "ADV") and not t.is_stop


def _mental(t) -> bool:
    """A cognition verb, also misspelt or inflected ("understanding", "thinkin", "undrestand")."""
    w = t.lower_
    forms = {t.lemma_.lower(), w, w.removesuffix("ing"), w.removesuffix("ed")}
    return bool(forms & MENTAL) or (_content(t) and any(_close(x, MENTAL) for x in forms))


def _volition(t) -> bool:
    forms = {t.lemma_.lower(), t.lower_}
    return bool(forms & VOLITION) or (_content(t) and any(_close(x, VOLITION) for x in forms))


def _clause_is_fact(head, tokens) -> bool:
    words = [t for t in tokens if not t.is_punct]
    if not words:
        return False
    # Opens with "I think / I mean / I saw / I want ...", whatever the parser made the root.
    if len(words) > 1 and words[0].lower_ in FIRST and any(_mental(w) or _volition(w) for w in words[1:4]):
        return False
    lower = {t.lower_ for t in words}
    if any(POLITE.match(t.text) for t in words if t.i == head.i or t.head.i == head.i):
        return False
    # Leading fillers ("ok", "hmm", "and", "just", "also") don't change what the clause is.
    i = 0
    while i < len(words) - 1 and (words[i].pos_ in ("INTJ", "CCONJ")
                                  or (words[i].pos_ == "ADV" and words[i].lower_ not in STANDING)):
        i += 1
    first = words[i]
    # Questions, with or without "?".
    if first.tag_ in WH or any(t.tag_ in WH for t in words[i:i + 3] if t.i < head.i):
        return False
    if first.pos_ == "AUX" and first.i <= head.i and any(
            t.dep_ in SUBJ and t.i > first.i for t in words):  # "is this ...", "can you ...", "should we ..."
        return False
    if len(words) >= 2 and [w.lower_ for w in words[-2:]] == ["or", "not"]:
        return False
    subj = [c for c in head.children if c.dep_ in SUBJ]
    if not subj and head.tag_ in ("VBZ", "VBD"):
        # Parser slip: "Our API runs on ..." with "API" as a compound of "runs", not its subject.
        subj = [c for c in head.lefts if c.dep_ in ("compound", "npadvmod", "nmod") and c.pos_ in ("NOUN", "PROPN")][-1:]
    standing = bool(lower & STANDING)
    detail = _detail(tokens)  # all tokens: the parser tags some names and paths as punctuation
    strong_detail = _detail(tokens, strong=True)
    if not subj and head.pos_ in ("NOUN", "PROPN") and detail and any(
            c.dep_ == "acl" and c.tag_ in ("VBN", "VBG") for c in head.children) and any(
            c.dep_ in ("poss", "det", "compound") for c in head.children):
        return True  # "is" left out: "our api hosted in frankfurt region"
    if not subj:
        # A command (any verb in base form) is a request, unless it is a standing rule.
        if head.pos_ in ("VERB", "AUX") and head.tag_ in ("VB", "VBP") and standing:
            return True
        return False  # command, fragment, or a clause whose subject is in the conversation
    s = subj[0]
    s_low = s.lower_
    s_kids = list(s.children)
    if s_low in DEICTIC and not s_kids:
        return False
    first_person = s_low in FIRST or any(k.lower_ in ("my", "our") for k in s_kids if k.dep_ == "poss")
    lemma = head.lemma_.lower()
    if s_low in FIRST:
        if _volition(head) or (lemma == "like" and any(c.lower_ in ("would", "'d") for c in head.children)):
            return False
        if _mental(head):
            return False
        if any(c.dep_ == "acomp" and c.lemma_.lower() in UNSURE for c in head.children):
            return False
    # "you should ...", "can it ...": addressed to the assistant.
    if s_low == "you":
        return False
    modals = {c.lower_ for c in head.children if c.tag_ == "MD"}
    if modals & UNCERTAIN or modals & FUTURE or (s_low in FIRST and modals & INTENT) or (s_low == "i" and modals):
        return False
    # Evaluations of the current work: "the page looks weird", "card size are small".
    if lemma in PERCEPTION and not detail:
        return False
    modal = any(c.tag_ == "MD" for c in head.children)
    judged = head.pos_ == "ADJ" or (lemma == "be" and any(c.dep_ == "acomp" and c.pos_ == "ADJ"
                                                        for c in head.children))
    # "I'm colorblind" is about the user; "I hard to check" (no "am") is a complaint.
    copula = lemma == "be" or any(c.lemma_ == "be" for c in head.children)
    if judged and not modal and not detail and not (first_person and copula):
        return False
    # A bare event or state with no object and no detail: "the build passed", "the test still fails".
    if head.pos_ == "VERB" and not detail and not any(
            c.dep_ in ("dobj", "xcomp", "ccomp", "attr", "dative", "prep", "oprd") for c in head.children):
        return False
    # About something only the conversation shows: "I don't like this approach", "ok i like it".
    for t in words:
        if t.dep_ in ("dobj", "pobj") and t.lower_ in PRONOUN_OBJ and (
                t.head.i == head.i or (t.dep_ == "pobj" and t.head.head.i == head.i)) and not strong_detail:
            return False  # its meaning is in the conversation, unless a name or number says what
        if t.dep_ in ("dobj", "pobj") and any(c.lower_ in DEICTIC_DET and c.dep_ == "det" for c in t.children) \
                and not detail and t.head.i == head.i:
            return False
    return True


def fact_text(sentence: str) -> str | None:
    """The lasting fact in a sentence: the whole sentence when its main clause is one; else a
    joined clause that is one ("add a login form, the auth provider is Auth0" -> "the auth
    provider is Auth0"); "" when there is none. None when no parser is installed, or when the
    parse has no verb at all: then the parser misread the sentence ("Our staging server runs on
    port 8443" as one noun phrase) and the caller's word rules decide."""
    parser = nlp()
    if parser is None:
        return None
    if STANDING_DONT.match(sentence) and not MOMENT.search(sentence):
        rest = sentence[STANDING_DONT.match(sentence).end():].split()
        # A real object is needed: "please do not touch it" points at the conversation.
        if rest and rest[0].lower().strip(".,!") not in PRONOUN_OBJ and len(sentence.split()) <= MAX_FACT_WORDS:
            text = re.sub(r"^(?:please|pls|plz|kindly)\s+", "", sentence.strip(), flags=re.I)
            return text[:1].upper() + text[1:]
    if any(POLITE.match(w) for w in re.findall(r"[A-Za-z]+", sentence)):
        # A polite sentence is a request; only a separate part without the marker can hold a fact
        # ("we self-host sentry, so please check the dsn" -> "we self-host sentry").
        for part in SEGMENT.split(sentence):
            words_ = part.split()
            cut = next((i for i, w in enumerate(words_) if POLITE.match(re.sub(r"\W", "", w))), len(words_))
            part = CONNECTIVE.sub("", " ".join(words_[:cut])).strip(" ,;")
            if len(part.split()) < 3:
                continue
            got = fact_text(part)
            # Kept only with a strong detail, or when the user speaks about themselves or the team:
            # other parts of a polite request describe what is wanted ("the card will have ...").
            if got and (_detail(parser(got), strong=True) or FIRST_PERSON_START.match(got)):
                return got[:1].upper() + got[1:]
        return ""
    doc = parser(sentence)
    if not any(t.pos_ in ("VERB", "AUX") for t in doc):
        # Unreadable: let the word rules decide, but only for text that starts like a subject.
        first = next((t for t in doc if not t.is_punct), None)
        return None if first is not None and first.pos_ in ("DET", "PRON", "PROPN", "NOUN", "ADJ") else ""
    words = [t for t in doc if not t.is_punct]
    if len(words) > 1 and words[0].lower_ in FIRST and any(_mental(w) or _volition(w) for w in words[1:4]):
        return ""
    # A run-on or a question ("..., right", "... or not"): only a short separate clause can be kept.
    whole_ok = len(words) <= MAX_FACT_WORDS and not TAG_QUESTION.search(sentence)
    if words and words[0].lower_ in SUBORDINATE:
        return ""  # "Because ...", "After I click ...": hangs off something said before  # "I mean ...", "I think ...", "I want ...": whatever the parser made the root
    for sent in doc.sents:  # the caller already split sentences; spaCy may split further
        head = sent.root
        if whole_ok and _clause_is_fact(head, _clause_tokens(head)):
            return sentence
        # Joined clauses of the main verb, and reason clauses anywhere ("fix X since we host on Y").
        # A clause with its own subject before a command: "i don't like long answers, keep it simple".
        before = [c for c in head.lefts if c.dep_ == "ccomp"] if not any(c.dep_ in SUBJ for c in head.children) else []
        question = TAG_QUESTION.search(sentence) or sentence.rstrip().endswith("?")
        subs = ([] if question else before + [c for c in head.children if c.dep_ in CLAUSES]) + [
            t for t in sent if t.dep_ == "advcl" and any(m.dep_ == "mark" and m.lower_ in REASON for m in t.children)]
        for c in subs:
            if c.pos_ in ("VERB", "AUX") and _clause_is_fact(c, _clause_tokens(c)):
                start = min(t.i for t in c.subtree if not (t.dep_ == "mark" and t.head.i == c.i) and not t.is_punct)
                # Words before the clause's own "since/because" belong to the clause before it
                # ("... real printer right since my stockman gave me ...").
                start = max([start] + [m.i + 1 for m in c.children if m.dep_ == "mark" and m.i >= start])
                # A clause before the command ends where it ends; others run to the next connective
                # ("... because i use X, Y, Z... but is any ...") or the end (spaCy may cut "3am" in two).
                end = c.right_edge.i + 1 if c in before else next(
                    (t.i for t in doc[c.i + 1:] if t.lower_ in CUT_AT or t.text in ("...", "…")), len(doc))
                if sum(not t.is_punct for t in doc[start:end]) > MAX_FACT_WORDS or _inside_word(doc, start, end):
                    continue
                text = doc[start:end].text.strip(" ,;.")
                return text[:1].upper() + text[1:]
        break
    return ""


# Attitude verbs: how the user wants things done ("I prefer short answers", "I hate long meetings").
PREFER = {"prefer", "like", "love", "hate", "dislike", "enjoy"}


def instruction(text: str) -> bool:
    """An instruction about how to work, by the sentence's form (not its topic words): a command with "never",
    "always", "don't" ("never use tabs", "please don't reformat existing code"), or the user's own standing way
    ("I don't want summaries", "we always squash commits", "I prefer short answers"). Not: a description ("the
    upload limit is 10 MB"), an event ("we decided to keep the cart in redis"), a question, or a plain command,
    which is usually a request for now ("commit this"). Whether it lasts is left to evidence (repeats, practice)."""
    parser = nlp()
    if parser is None or text.rstrip().endswith("?"):
        return False
    first = re.match(r"\W*([A-Za-z']+)", text)
    if first and first.group(1).lower() in SUBORDINATE:  # "because I don't ...", "if we never ...": hangs off another
        return False
    label = re.match(r"^\s*\S+(?:\s+\S+){0,2}?\s*:\s+(\S.*)$", text, re.S)  # "Note: ...", "Rule 1: ..." (by shape)
    if label and len(label.group(1).split()) >= 2 and instruction(label.group(1)):
        return True
    for sent in parser(text).sents:
        # The main clause and clauses joined to it ("..., always 2 spaces"; "Rule 1: always keep ...": after a label
        # the parser hangs the sentence under it as "dep").
        joined = ("conj", "parataxis", "dep") + (() if _mental(sent.root) else ("ccomp",))  # "I think we never ...": a belief
        for h in [sent.root] + [c for c in sent.root.children if c.dep_ in joined]:
            if h.pos_ not in ("VERB", "AUX"):
                continue
            kids = list(h.children)
            subj = [c for c in kids if c.dep_ in SUBJ]
            standing = any(c.dep_ == "neg" for c in kids) or any(c.lower_ in STANDING for c in kids)
            # A command: no subject (the parser tags a sentence-first command VB or VBP: "always pin versions").
            if not subj and h.tag_ in ("VB", "VBP") and standing and not any(c.tag_ == "MD" for c in kids):
                return True
            # The user's own way; not a state of mind ("I don't think ...", "I don't know ..."; "don't assume" is a
            # command, above).
            # An attitude verb counts when it is about doing ("I like to use X", "I prefer X": a choice), not a taste
            # in things ("I like naval talk").
            attitude = h.lemma_.lower() in PREFER and (h.lemma_.lower() == "prefer" or any(
                c.dep_ in ("xcomp", "ccomp") and c.pos_ in ("VERB", "AUX") for c in kids))
            past = any(c.dep_ in ("aux", "auxpass") and c.tag_ == "VBD" for c in kids)  # "I didn't", "i saw not": events
            if subj and subj[0].lower_ in FIRST and h.tag_ in ("VB", "VBP") and not _mental(h) and not past \
                    and (standing or attitude):
                return True
    return False


_HELD_OUT = {"dobj", "attr", "prep", "pobj", "xcomp", "acomp", "oprd", "dative", "advcl", "ccomp", "npadvmod"}


def rule_parts(rule: str) -> tuple[list[str], list[str]]:
    """(wanted, forbidden) content words of a standing rule, by grammar: what a negated verb ("never", "don't",
    "not"), "without" or "no" applies to is forbidden ("never use print for logging, use the logger": forbidden
    print, logging; wanted logger). Closed classes only: negation, "without", "no"."""
    parser = nlp()
    if parser is None:
        return [], []
    doc = parser(rule)
    forbidden: set[int] = set()
    negated: set[int] = set()
    for t in doc:
        if t.dep_ == "neg":
            v = t.head
            negated.add(v.i)
            for c in v.children:
                if c.dep_ in _HELD_OUT:
                    forbidden |= {k.i for k in c.subtree}
        elif t.lower_ == "without" and t.dep_ == "prep":
            forbidden |= {k.i for k in t.subtree if k.i != t.i}
        elif t.lower_ == "no" and t.dep_ == "det":
            forbidden |= {k.i for k in t.head.subtree if k.i != t.i}
    content = [t for t in doc if t.pos_ in ("NOUN", "PROPN", "VERB", "ADJ", "NUM", "X") and not t.is_stop]
    wanted = [t.text for t in content if t.i not in forbidden and t.i not in negated and t.lower_ not in STANDING]
    return wanted, [t.text for t in content if t.i in forbidden]


def strip_lead(sentence: str) -> str:
    """Without a subjectless lead-in before the comma ("heads up, the db is postgres 16")."""
    parser = nlp()
    if parser is None or "," not in sentence:
        return sentence
    doc = parser(sentence)
    root = next(iter(doc.sents)).root
    subj = [c for c in root.children if c.dep_ in SUBJ]
    for c in root.lefts:
        if c.dep_ not in ("advcl", "npadvmod", "intj") or not subj:
            continue
        end = c.right_edge.i + 1
        if (end < len(doc) and doc[end].text == "," and end < subj[0].left_edge.i
                and not any(k.dep_ in SUBJ or k.dep_ in ("dobj", "attr", "acomp", "oprd", "ccomp", "xcomp", "prep")
                            for k in c.subtree if k.i != c.i)
                and not _detail(list(c.subtree))):  # "keep your answers short, ..." is an instruction: kept
            rest = doc[end + 1:].text.strip()
            return rest[:1].upper() + rest[1:] if rest else sentence
    return sentence


def split_clauses(sentence: str) -> list[tuple[str, str, str]]:
    """Split two clauses with their own subjects: [(text, verdict, gist)], verdict "fact" / "maybe" / "no"."""
    parser = nlp()
    if parser is None:
        return []
    doc = parser(sentence)
    sents = list(doc.sents)
    if len(sents) != 1:
        return []
    root = sents[0].root
    conj = [c for c in root.children if c.dep_ == "conj" and c.pos_ in ("VERB", "AUX")
            and any(k.dep_ in SUBJ and k.lower_ not in DEICTIC for k in c.children)]
    if len(conj) != 1 or not any(k.dep_ in SUBJ and k.lower_ not in DEICTIC for k in root.children):
        return []
    c = conj[0]
    inner = {t.i for t in c.subtree} | {t.i for t in root.children if t.dep_ == "cc" and t.i < c.i}
    main = [t for t in root.subtree if t.i not in inner]
    while main and (main[-1].dep_ == "cc" or main[-1].is_punct):  # "and" may hang on the object ("SQS and")
        main.pop()
    second = list(c.subtree)

    def part(head, tokens):
        text = "".join(t.text_with_ws for t in tokens).strip(" ,;.")
        if _clause_is_fact(head, tokens):
            verdict = "fact"
        elif any(k.dep_ == "acomp" and k.pos_ == "ADJ" for k in head.children):
            verdict = "maybe"
        else:
            verdict = "no"
        gist = " ".join(t.lower_ for t in tokens if t.pos_ in ("NOUN", "PROPN", "ADJ", "NUM", "X"))
        return text[:1].upper() + text[1:], verdict, gist

    return [part(root, main), part(c, second)]


OPENERS = "([{\"'“‘"
NOMINATIVE = {"i", "we", "he", "she", "they"}
DANGLING = {"DET", "ADP", "CCONJ", "SCONJ", "AUX", "PART"}  # word classes that need something after them


def _inside_word(doc, start: int, end: int) -> bool:
    """The span starts or ends in the middle of a written word ("11:05" cut to "05")."""
    if start > 0 and not doc[start - 1].whitespace_ and doc[start - 1].text not in OPENERS:
        return True
    return end < len(doc) and not doc[end - 1].whitespace_ and not (
        doc[end].is_punct and (end + 1 == len(doc) or doc[end].whitespace_))


def complete(text: str) -> bool:
    """A note reads as a whole statement: brackets and quotes closed, and it doesn't stop on a word
    that needs a continuation ("My purpose is that", "I don't need the parser i", "... and"). Decided
    by word class, so it holds for any wording. True without a parser."""
    if text.count("(") != text.count(")") or text.count('"') % 2 or text.count("“") != text.count("”"):
        return False
    parser = nlp()
    if parser is None:
        return True
    words = [t for t in parser(text) if not t.is_punct]
    if not words:
        return False
    last = words[-1]
    # "turn it off", "get it back" are fine; so is a preposition left at the end of a clause that
    # describes a noun ("the city I live in", "the thing I care most about"): its object is that noun.
    # On the main verb it is a cut-off piece ("I care about", "we should look into").
    if (last.pos_ in DANGLING and last.dep_ not in ("prt", "advmod")
            and not ((last.pos_ == "ADP" or last.dep_ == "prep")  # "to" with no full stop is tagged PART
                     and any(a.dep_ == "relcl" for a in last.ancestors))):
        return False
    if last.lower_ in NOMINATIVE:  # "I/we/he..." can't end a statement, whatever the parser says
        return False
    return not (last.pos_ == "PRON" and (last.dep_ in SUBJ or last.lower_ in DEICTIC)
                and last.dep_ not in ("dobj", "pobj"))


def about_user(sentence: str) -> bool | None:
    """True when a fact is about the user (general, all projects): its subject is "I" or "my ...",
    or it is a standing rule with no subject ("Always use spaces"). An action the user did to a
    thing ("I set the dev server to port 3001", past tense with an object) is about the project.
    None when no parser is installed."""
    parser = nlp()
    if parser is None:
        return None
    doc = parser(sentence)
    head = next(doc.sents).root
    if not any(t.pos_ in ("VERB", "AUX") for t in doc):
        # No verb ("my dog name Adam", "my hometown kampot"): the parser picks a different head
        # each time, so look at the noun phrase itself: the user's when it is "my ...".
        return any(t.lower_ == "my" and t.dep_ == "poss" for t in doc)
    subj = [c for c in head.children if c.dep_ in SUBJ]
    if not subj:
        return bool({t.lower_ for t in doc} & STANDING) and head.tag_ in ("VB", "VBP")
    s = subj[0]
    mine = s.lower_ in ("i", "me") or any(k.lower_ == "my" and k.dep_ == "poss" for k in s.children)
    if not mine:
        # "English is my second language": the subject's complement is the user's. "Security is the
        # thing I care most about" / "The town I grew up in is Kep": a clause describing the subject or
        # its complement says what the user does or likes.
        nouns = [s] + [c for c in head.children if c.dep_ == "attr"]
        return any(c.dep_ == "attr" and any(k.lower_ == "my" for k in c.children) for c in head.children) or any(
            r.dep_ == "relcl" and any(k.dep_ in SUBJ and k.lower_ in ("i", "me") for k in r.subtree)
            and not _past_action(r)  # "Render is the host I deployed the blog to": the project's
            for n in nouns for r in n.children)
    if s.lower_ == "i" and _past_action(head):
        return False
    return True


def _past_action(verb) -> bool:
    """A past action on a thing ("I set the dev server to port 3001"): about the project, not the user."""
    return verb.tag_ == "VBD" and any(c.dep_ == "dobj" and not any(k.lower_ == "my" for k in c.children)
                                      for c in verb.children)


def asks(sentence: str) -> bool:
    """A question anywhere in the sentence, with or without "?": an auxiliary or modal right before
    its own subject ("... should i add X or not", "so can we keep it"), or an "or not" tag."""
    if TAG_QUESTION.search(sentence):
        return True
    parser = nlp()
    if parser is None:
        return False
    doc = parser(sentence)
    return any(a.pos_ == "AUX" and a.i + 1 < len(doc) and doc[a.i + 1].dep_ in SUBJ
               and doc[a.i + 1].head == a.head and a.head.i > a.i for a in doc)


def tells(sentence: str) -> bool:
    """The sentence tells something rather than asks for something: its main verb has a subject, it
    has no politeness marker (a request, misspelt too) and asks nothing. Used for raw memory, which
    keeps every sentence: on the real replay, recalled requests ("ok please build it again")
    were nearly all noise. False without a parser."""
    parser = nlp()
    if parser is None:
        return False
    doc = parser(sentence)
    root = next(doc.sents).root
    return (any(c.dep_ in SUBJ for c in root.children) and not any(POLITE.match(t.text) for t in doc)
            and not asks(sentence))


def has_detail(text: str) -> bool:
    """`_detail` for a plain string (used when the parse can't be trusted)."""
    parser = nlp()
    return parser is not None and _detail(parser(text))


LEAVE_OUT = {"conj", "cc", "advcl", "parataxis", "ccomp", "relcl", "mark", "punct", "nsubj", "nsubjpass", "intj",
             "discourse", "appos"}
LIGHT = {"be", "do", "have", "get", "make", "go", "let"}


def rule_cores(text: str) -> list[str]:
    """The standing rules inside a long request: each negated verb phrase with its objects ("do not
    touch old code", "not invent new sentences", "don't want so much noise alert"). Found by the
    negation's place in the parse, so any verb and wording works. Left out: phrases tied to the
    moment ("right now"), questions, thoughts with nothing after them ("don't think"), and phrases
    with fewer than two content words ("are not", "don't want")."""
    parser = nlp()
    if parser is None:
        return []
    out = []
    for sent in parser(text).sents:
        s = sent.text.strip()
        if s.endswith("?") or TAG_QUESTION.search(s) or MOMENT.search(s):
            continue
        for t in sent:
            if not (t.dep_ == "neg" or t.lower_ == "never"):
                continue
            h = t.head
            # An action rule needs an action verb: "not look good", "are not valid" judge the current
            # work (a complaint about now), they don't set a rule.
            if h.pos_ != "VERB" or h.lemma_.lower() in PERCEPTION | {"be"}:
                continue
            if t.i > 0 and sent.doc[t.i - 1].lower_ == "or":  # "check it works or not": a question tag
                continue
            # "it not save on X", "the job does not run": a report about a thing, not a rule, unless
            # it says how things should be ("the bot should never send ...").
            subj = [c for c in h.children if c.dep_ in SUBJ]
            if subj and subj[0].lower_ not in FIRST | {"you"} and not any(
                    c.tag_ == "MD" for c in h.children):
                continue
            if _mental(h) and not any(c.dep_ in ("dobj", "xcomp", "ccomp") for c in h.children):
                continue
            toks, stack = set(), [h]
            while stack:
                x = stack.pop()
                toks.add(x)
                stack += [k for k in x.children if k.dep_ not in LEAVE_OUT]
            # "do not touch or format old code": verbs joined under one negation share it
            for k in h.children:
                if k.dep_ == "conj" and k.pos_ == "VERB" and not any(c.dep_ in SUBJ for c in k.children):
                    toks |= {y for y in k.subtree if y.dep_ not in LEAVE_OUT - {"conj", "cc"}} | {
                        c for c in h.children if c.dep_ == "cc"}
            words = [x for x in sorted(toks, key=lambda x: x.i) if not x.is_punct and not POLITE.match(x.text)]
            dropped = []
            while words and words[-1].pos_ in DANGLING | {"PRON", "CCONJ"} and words[-1].dep_ not in ("prt", "neg"):
                dropped.append(words.pop())
            # "don't want to touch it": the action's own object is only "it": points at now. Not "never
            # commit secrets to it" (the rule has its object; "to it" is extra).
            last = words[-1] if words else None
            after = sent.doc[last.i + 1] if last is not None and last.i + 1 < len(sent.doc) else None
            if any(x.lower_ in PRONOUN_OBJ and x.i > 0 and sent.doc[x.i - 1].pos_ != "ADP" for x in dropped) or (
                    last is not None and last.pos_ == "VERB" and after is not None and after.lower_ in PRONOUN_OBJ):
                continue
            content = [x for x in words if x.pos_ in ("NOUN", "PROPN", "VERB", "ADJ") and not x.is_stop
                       and x.lemma_.lower() not in LIGHT]
            if len(content) >= 2 and len(words) <= 12:
                core = " ".join(x.text for x in words)
                core = re.sub(r"\s+(n't|'s|'re|'m|'ll|'ve|'d)\b", r"\1", core)
                out.append(core[:1].upper() + core[1:])
    return list(dict.fromkeys(out))


def topic_key(text: str) -> str | None:
    """A note's topic label for search: its common nouns (not the value: names, numbers and words the
    vocabulary doesn't know are left out), put before the note ("answer, emoji: I prefer short answers
    without emojis."). A question names the topic, not the value, and the plain note scored below the
    hook's bar ("How long should your answers be?" 0.61 -> 0.74). Grammar only (part of speech), no
    word lists. None when the note has no such noun or no parser is installed."""
    parser = nlp()
    if parser is None:
        return None
    # Pieces of an identifier ("acct-files" -> "acct", "files") are part of a value, not the topic.
    ident = [m.span() for m in re.finditer(r"\S*\w[./:_@-]\w\S*", text)]
    doc = parser(text)
    nouns = list(dict.fromkeys(t.lemma_.lower() for t in doc if t.pos_ == "NOUN" and not _detail([t])
                               and not (t.text[0].isupper() and not t.is_sent_start)  # "... is Fish": a name
                               and not any(a <= t.idx < b for a, b in ident)))
    where = _where_question(doc)
    if not (nouns or where):
        return None
    return f"{where + ' ' if where else ''}{', '.join(nouns) + ': ' if nouns else ''}{text}"


PLACE_PREP = {"in", "at", "to", "from", "near"}  # closed class: prepositions that name where


def _where_question(doc) -> str | None:
    """The "Where …?" question a fact answers when its value is a place: a verb with a subject and
    "in/at/to/from/near" + a concrete name ("I live in Siem Reap" -> "Where do I live?", "We deploy to
    Netlify" -> "Where do we deploy?"). "Where do I live?" scored 0.63 against the plain note, below
    the hook's bar; with this key 0.72, while unrelated "where …" questions stay at 0.49-0.53."""
    for p in doc:
        v = p.head
        if p.dep_ != "prep" or p.lower_ not in PLACE_PREP or v.pos_ not in ("VERB", "AUX") or p.i < v.i:
            continue
        obj = [c for c in p.children if c.dep_ == "pobj"]
        subj = [c for c in v.children if c.dep_ in SUBJ]
        if not obj or not subj or not _detail(list(obj[0].subtree)):
            continue
        s = subj[0]
        who = " ".join("I" if x.lower_ == "i" else x.lower_ for x in s.subtree)
        if v.lemma_ == "be":
            return f"Where {v.lower_} {who}?"
        aux = [c for c in v.children if c.dep_ in ("aux", "auxpass") and c.lemma_ in ("be", "have")]
        if aux:  # "The servers are hosted in Frankfurt" -> "Where are the servers hosted?"
            return f"Where {aux[0].lower_} {who} {v.lower_}?"
        do = "do" if s.lower_ in ("i", "we", "you", "they") or s.tag_ in ("NNS", "NNPS") else "does"
        return f"Where {do} {who} {v.lemma_}?"
    return None
