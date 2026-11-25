"""Is a sentence a lasting fact? Decided by its grammar (spaCy parse), not by lists of topic or
action words, so it works for any verb, any subject and many writing styles (measured on held-out
sets in `dore.eval.learning`).

Rules use only:
- sentence structure: questions (question word, inverted auxiliary, "... or not"), commands
  (a base-form verb with no subject, whatever the verb), fragments (no subject), a subject that
  is only "it/this/that" (its meaning is in the conversation, not in the note);
- small closed word classes (grammatical categories that don't grow with new topics): wanting
  (want, need, would like...), thinking/perceiving (think, guess, feel, saw...), appearance
  (look, seem...), always/never (a standing rule), politeness markers (please, pls, kindly);
- whether the sentence names a concrete detail (a name, number or identifier): an evaluation
  ("the page looks weird") or a one-off event ("the build passed this time") without one is not
  worth remembering.

English only (the parser and `bge-small-en`). Without spaCy, `is_fact` returns None and the old
word rules in `statements.py` are used.
"""

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
          "saw", "notice", "realize", "realise", "worry", "try", "get", "forget", "miss", "confuse"}
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
SEGMENT = re.compile(r"\s*[,;:]\s*|\s+(?=(?:so|since|because|but|and|as)\s)", re.I)
CUT_AT = {"but", "so", "because", "since", "though", "although", "however"}
MAX_FACT_WORDS = 20  # lasting facts are short (longest in the test sets: 14); longer = a run-on
SUBORDINATE = {"because", "since", "after", "before", "when", "whenever", "while", "if", "unless", "although",
               "though", "until", "once", "so", "cause", "coz", "cuz", "bc"}
FIRST_PERSON_START = re.compile(r"^(?:i|i'm|we|we're|my|our)\b", re.I)
CONNECTIVE = re.compile(r"^(?:so|since|because|but|and|as)\s+", re.I)


def nlp():
    """The parser, loaded once (~0.5 s); None if spaCy or its English model is not installed."""
    global _NLP, _TRIED
    if not _TRIED:
        _TRIED = True
        try:
            import spacy
            # md, not sm: sm read "The auth-web service runs on port 7710" as a noun phrase and lost
            # the fact (2026-11-25); md costs the same per sentence (~1 ms), ~0.6 s to load once.
            _NLP = spacy.load("en_core_web_md", disable=["ner"])
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
                # A clause before the command ends where it ends; others run to the next connective
                # ("... because i use X, Y, Z... but is any ...") or the end (spaCy may cut "3am" in two).
                end = c.right_edge.i + 1 if c in before else next(
                    (t.i for t in doc[c.i + 1:] if t.lower_ in CUT_AT or t.text in ("...", "…")), len(doc))
                if sum(not t.is_punct for t in doc[start:end]) > MAX_FACT_WORDS:
                    continue
                text = doc[start:end].text.strip(" ,;.")
                return text[:1].upper() + text[1:]
        break
    return ""


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
    subj = [c for c in head.children if c.dep_ in SUBJ]
    if not subj:
        return bool({t.lower_ for t in doc} & STANDING) and head.tag_ in ("VB", "VBP")
    s = subj[0]
    mine = s.lower_ in ("i", "me") or any(k.lower_ == "my" and k.dep_ == "poss" for k in s.children)
    if not mine:  # "English is my second language": the subject's complement is the user's
        return any(c.dep_ == "attr" and any(k.lower_ == "my" for k in c.children) for c in head.children)
    if s.lower_ == "i" and head.tag_ == "VBD" and any(
            c.dep_ == "dobj" and not any(k.lower_ == "my" for k in c.children) for c in head.children):
        return False
    return True


def has_detail(text: str) -> bool:
    """`_detail` for a plain string (used when the parse can't be trusted)."""
    parser = nlp()
    return parser is not None and _detail(parser(text))
