"""What to learn from a user's message (rules only, no model): facts, scope, questions, corrections."""

from __future__ import annotations

import re

PERSONAL = re.compile(r"\b(my|me|mine|i|i'm|am i|do i)\b", re.I)

QUESTION_START = re.compile(
    r"^(what|who|whom|whose|where|when|why|how|which|is|are|am|do|does|did|can|could|will|would|should|"
    r"tell me|please|explain|write|show|give|list)\b", re.I)
# "Please remember that X" / "Can you note: X" / "FYI X" -> X is a statement to store.
MEMORY_LEAD_IN = re.compile(
    r"^(?:(?:can|could|would|will) you\s+)?(?:please\s+)?(?:remember|note|keep in mind|don'?t forget|"
    r"do not forget|save)(?:\s+that)?\s*[:,]?\s+|^(?:fyi|just so you know|for your information|btw|by the way)"
    r"\s*[:,]?\s+", re.I)
# Small talk is not a fact about the user.
SMALL_TALK = re.compile(
    r"^(hi|hello|hey|thanks|thank you|thx|ok|okay|sorry|bye|goodbye|good (morning|afternoon|evening|night))\b", re.I)
# Not facts: system text ("[Request interrupted by user]"), commands ("/teach ..."), markup, and
# hypotheticals or play ("If I were rich...", "Pretend my name is Bob"), seen stored as verified
# in a probe (2026-11-25).
NOT_A_FACT = re.compile(
    r"^[\[/<{]|^(?:if (?:i|we) (?:were|was|had|could)|imagine|pretend|suppose|what if|let'?s say|say that|"
    r"hypothetically|just kidding|jk|lol|haha)\b", re.I)
# "No, it's a Honda" / "Actually, I live in Siem Reap" / "That's wrong: ...": a correction of the
# last notes in plain words. The rest of the message is the fix.
CORRECTION_LEAD = re.compile(
    r"^(?:no+|nope|nah|wrong|incorrect|not quite|not really|actually|in fact|"
    r"that'?s (?:not (?:right|true|correct)|wrong|incorrect)|that is (?:not (?:right|true|correct)|wrong|incorrect)|"
    r"you'?re wrong|you are wrong)\b[\s,.!:;-]*", re.I)

# Feedback weight for what dore guesses from behaviour.
IMPLICIT_FEEDBACK = 1   # asked again (-), moved on (+)
# Asked the same thing again = the last answer didn't help. Measured (bge-small, 2026-11-25):
# re-asks 0.79-0.97 ("Where do I live?" / "Which city do I live in?" 0.90); different questions
# 0.53-0.84, the high ones being one-detail changes (dog/cat 0.82, api/database port 0.84),
# which `same_frame` excludes. "What is my job?" / "What do I do for work?" (0.79) is missed.
REASK_SIMILARITY = 0.8

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

# A longer message is a paste (an article, a log), not statements about the user's work:
# 11 sentences of a pasted report were stored as verified user facts (real DB, 2026-11-25).
MAX_MSG_CHARS = 3000
MAX_MSG_FACTS = 20

# Facts about the organisation rather than one project ("our production server ...").
ORG = re.compile(r"\ball our \w+|\b(our) (production|prod|staging|server|servers|team|company|infra|infrastructure|"
                 r"ci|cluster|database server)\b|\ball (our )?projects\b|\bevery project\b|\bwe (always|never)\b",
                 re.I)

# Coding instructions are requests, not facts ("add tests", "fix the bug ...").
IMPERATIVE = re.compile(
    r"^(add|create|make|fix|write|implement|update|remove|delete|rename|refactor|change|move|run|test|check|"
    r"build|install|deploy|start|stop|set|put|show|explain|give|list|try|help|let'?s|please|can|could|would|"
    r"look|find|search|open|read|replace|convert|generate|split|merge|clean|format|debug|print|return|call|"
    r"push|commit|review|summari[sz]e|translate|describe|compare|continue|go|do|see|tell|reply|answer|respond|say|output|answer)\b", re.I)
# "I need a helper that ..." is a request; "It will run on ..." only makes sense in its conversation.
WANT = re.compile(r"^(i|we)\s*('d| would| will)?\s*(need|want|like|wanna|have to|must have)\b", re.I)
VAGUE = re.compile(r"^(it|this|that|these|those|they|he|she|which)\b", re.I)
FILLER = re.compile(r"^(also|and|so|but|then|ok(ay)?|hey|hi|well|btw|yes|yeah|yep|sure)\b[,:]?\s*", re.I)
# "If not please remove", "Plesae remove the note": a request anywhere in the sentence, typos too.
PLEASE = re.compile(r"\b(please|pleas|plese|plesae|pleae|pls|plz)\b", re.I)
# Shapes of pasted output, code and lists (not words): bullets, numbered steps, headings, quotes,
# shell prompts, indented lines, stack frames, file:line references, column layouts, status symbols.
STRUCTURED = re.compile(
    r"^\s*(?:[-*•●◦▪>#|]|\d+[.)]\s|\$\s|-->)|^\s{2,}\S|\*\*|\bFile \"|^\s*at \S+[.(]|"
    r"\w+\.\w{1,5}:\d+|\S\s{3,}\S+\s{3,}\S|[\u2700-\u27bf\u2600-\u26ff\U0001F300-\U0001FAFF]")
# <pasted_content id=..>...</pasted_content id=..>, <task-notification>...</task-notification>, ...
TAG_BLOCK = re.compile(r"<([a-z][\w-]*)\b[^>]*>.*?</\1\b[^>]*>", re.S | re.I)
COMPACT_SUMMARY = re.compile(r"^This session is being continued from a previous conversation", re.I)
# The user pasting dore's own output back ("From dore memory: ...") is not a new fact.
ECHO = re.compile(r"\bdore memory\b|^#\d+ \(", re.I)


PARALLEL = 0.6


def user_facts(text: str, similar=None) -> list[str]:
    """Durable statements in a coding prompt: no requests, questions, small talk or code.
    With the parser installed, `grammar.fact_text` decides by sentence structure (any wording);
    otherwise the word rules below are used. Two clauses with their own subjects become one fact each.
    `similar(a, b)`: meaning similarity, to keep a clause that parallels a fact."""
    from dore.learn.grammar import complete, fact_text, has_detail, nlp, split_clauses, strip_lead
    out = []
    for sent in SENTENCE_SPLIT.split(text.strip()):
        sent = sent.strip()
        if structured_line(sent):
            continue
        while FILLER.match(sent):
            sent = FILLER.sub("", sent, count=1).strip()
        fix = CORRECTION_LEAD.match(sent)  # "No, the API uses port 9090" -> "The API uses port 9090"
        if fix and sent[fix.end():].strip():
            sent = sent[fix.end():].strip()
        sent = strip_lead(sent)
        parts = [] if sent.endswith("?") else split_clauses(sent)
        if parts and any(v == "fact" for _, v, _ in parts):
            fact = next(g for _, v, g in parts if v == "fact")
            out += [t for t, v, g in parts
                    if (v == "fact" or (v == "maybe" and similar is not None and similar(g, fact) >= PARALLEL))
                    and complete(t) and not ECHO.search(t) and not NOT_A_FACT.match(t)]
            continue
        lead = MEMORY_LEAD_IN.match(sent)
        if lead:
            sent = sent[lead.end():].rstrip("?").strip()
        elif sent.endswith("?"):
            continue
        else:
            parsed = fact_text(sent)
            if parsed is not None:
                if not parsed:
                    continue
                sent = parsed
            elif nlp() is not None and not has_detail(sent):
                continue  # the parser couldn't read it: keep it only if it names something concrete
            elif (QUESTION_START.match(sent) or SMALL_TALK.match(sent) or IMPERATIVE.match(sent)
                  or WANT.match(sent) or VAGUE.match(sent) or PLEASE.search(sent)):
                continue
        if ECHO.search(sent):
            continue
        if NOT_A_FACT.match(sent) or not complete(sent):
            continue
        n = len(sent.split())
        # 3 words are enough when one names something concrete ("tests use vitest", "my name dara").
        if n > 60 or n < 3 or (n == 3 and not (has_detail(sent) or any(c.isdigit() for c in sent)
                                                 or re.search(r"\b[A-Z][a-z]+\b", sent[1:]))) \
                or (n == 3 and nlp() is None) or "```" in sent or sent.count("(") > 2:
            continue
        out.append(sent[:1].upper() + sent[1:])
    return out


def scope_for(text: str, project: str) -> str:
    """"" (general) for facts about the user or the whole organisation, else the project.
    With the parser: by the sentence's subject (`grammar.about_user`), so "I set the dev server
    to port 3001" stays in the project; without it: any "I/my/me" makes it general."""
    from dore.learn.grammar import about_user
    from dore.memory.rules import codebase_place, local_value
    mine = about_user(text)
    if mine is None:
        mine = bool(PERSONAL.search(text))
    # Said for this place only: "in this repo ...", or "here we ..." when it is not about the user ("I live here in
    # Phnom Penh" is the user's, in every project).
    if codebase_place(text) or (local_value(text) and not mine):
        return project
    if ORG.search(text):
        return ""
    return "" if mine else project


def structured_line(line: str) -> bool:
    """A line shaped like output, code or a list rather than typed chat (any language)."""
    t = line.rstrip()
    if not t.strip():
        return False
    if STRUCTURED.search(t) or len(re.findall(r"`[^`]+`", t)) >= 2 or len(re.findall(r"\w+=\S+", t)) >= 2:
        return True
    if len(re.findall(r"\b[A-Z]{2,}\b", t)) >= 3:  # SQL, log levels, headings
        return True
    if "&&" in t or "||" in t or " | " in t or re.match(r"^\s*[\w./-]+: [\w./ -]+: ", t):  # shell, "bash: x: not found"
        return True
    if re.search(r"[·▎│┃•►▶\u2500-\u257f\u25a0-\u25ff]", t):  # UI separators, box drawing, shapes
        return True
    symbols = sum(t.count(c) for c in "{}[]();=<>$|\\")
    return symbols / len(t) > 0.08


def message_facts(msg: str, similar=None) -> list[str]:
    """Facts in one user message; none for a paste (an article, a log, the assistant's output).
    Tagged blocks (<pasted_content>, <task-notification>, ...) are not the user's words; a message
    of 3+ lines is a paste, whatever its words."""
    if len(msg) > MAX_MSG_CHARS:
        return []
    text = TAG_BLOCK.sub(" ", msg).strip()
    if text.startswith("<") or COMPACT_SUMMARY.match(text):
        return []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 3 or (len(lines) == 2 and any(structured_line(ln) for ln in lines)):
        return []
    found = user_facts("\n".join(ln for ln in lines if not structured_line(ln)), similar)
    return found if len(found) <= MAX_MSG_FACTS else []


PASTE = re.compile(r"<pasted_content\b[^>]*>(.*?)</pasted_content\b[^>]*>", re.S | re.I)
BULLET = re.compile(r"^\s*(?:[-*•●◦▪]|\d+[.)])\s+")
LEAD_WORDS = 15
ITEM_CHARS = 300


def message_parts(msg: str) -> tuple[str, list[str]]:
    """The words the user typed, and the blocks they pasted. Other tagged blocks (system text) are neither."""
    pasted = [m.group(1).strip() for m in PASTE.finditer(msg)]
    return TAG_BLOCK.sub(" ", msg).strip(), [p for p in pasted if p]


def entry(line: str) -> str:
    return BULLET.sub("", line).strip()[:ITEM_CHARS]


def _code_like(line: str) -> bool:
    return sum(line.count(c) for c in "{}[]();=<>$\\") / max(1, len(line)) > 0.08


def _heading(text: str) -> bool:
    """A title without a verb ("My friends", "Our servers")."""
    from dore.learn.grammar import nlp
    parser = nlp()
    return parser is not None and not any(t.pos_ in ("VERB", "AUX") for t in parser(text))


def list_group(msg: str) -> tuple[str, list[str]] | None:
    """A list the user typed under their own lead line ("Here are my friends:" then one entry per line): (title,
    entries). By shape and grammar: the lead ends with a colon and tells or names something (not a request or a
    question); no entry is a request, a question or code. Pasted lists are judged by Haiku (`learn.consolidate`)."""
    typed, _ = message_parts(msg)
    raw = [ln for ln in typed.splitlines() if ln.strip()]
    lines = [ln.strip() for ln in raw]
    if len(lines) < 3 or typed.startswith("<") or COMPACT_SUMMARY.match(typed) or ECHO.search(typed):
        return None
    if any(re.match(r"\s{2,}|\t", ln) for ln in raw[1:]):  # indented: code or config
        return None
    lead = lines[0].lstrip("#").strip()
    title = lead.rstrip(":").strip()
    if not lead.endswith(":") or not title or len(title.split()) > LEAD_WORDS:
        return None
    from dore.learn.grammar import tells
    if not (tells(title) or _heading(title)):
        return None
    items = [entry(ln) for ln in lines[1:]]
    if any(t.endswith("?") or IMPERATIVE.match(t) or PLEASE.search(t) or _code_like(t) for t in items):
        return None
    items = [t for t in items if len(t.split()) >= 2]
    return (title, items) if len(items) >= 2 else None


# A question by its first word (question words and auxiliaries: closed classes), with or without "?".
ASKS_START = re.compile(r"^(what|who|whom|whose|where|when|why|how|which|is|are|am|do|does|did|can|could|will|"
                        r"would|should|shall)\b", re.I)


def _words(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower()))


def episode_sentences(msg: str, facts: list[str]) -> list[str]:
    """The user's own sentences in a typed message that no rule stored as a note, kept as raw memory
    (`memory.episodes`) so that nothing the user says is lost. Same message checks as `message_facts`
    (no pastes, logs, code or system text); questions are left out (they ask, they don't tell)."""
    if len(msg) > MAX_MSG_CHARS:
        return []
    text = TAG_BLOCK.sub(" ", msg).strip()
    if text.startswith("<") or COMPACT_SUMMARY.match(text):
        return []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 3 or (len(lines) == 2 and any(structured_line(ln) for ln in lines)):
        return []
    from dore.learn.grammar import asks
    learned = [_words(f) for f in facts]
    sents = SENTENCE_SPLIT.split("\n".join(ln for ln in lines if not structured_line(ln)))
    if len(sents) > MAX_MSG_FACTS:  # a long paste on one line (an article): never judged sentence by sentence later
        return []
    out = []
    for sent in sents:
        sent = sent.strip()
        if not 3 <= len(sent.split()) <= 60 or sent.endswith("?") or ASKS_START.match(sent) \
                or NOT_A_FACT.match(sent) or ECHO.search(sent) or asks(sent):
            continue
        if any(f and f in _words(sent) for f in learned):  # it already taught a note
            continue
        out.append(sent)
    return out


# ---- Requirements: long instructions keep their gist (low trust; stronger when said again) ----
# A long request that sets a constraint ("summarize, but not too short, and don't invent sentences") is
# lasting knowledge even though it is not a short fact. Decided by structure: length, not a question,
# and constraint grammar (negation, modality, "only", "keep", "make sure", "without", "instead").
CONSTRAINT = re.compile(r"(?i)\b(not|n't|never|always|keep|make sure|without|only|must|should|instead|avoid|"
                        r"no need|don'?t|dont)\b")
REQ_QUESTION = re.compile(r"(?i)^(?:what|who|whom|whose|why|how|which|where|when|is|are|am|do|does|did|can|could|will|would)\b")
REQ_MIN_WORDS = 15
REQ_MAX_CHARS = 240
PATH_OR_URL = re.compile(r"(?:https?://\S+|(?:~|/)[\w./ \\-]*\.\w+|/Users/\S+)")


def requirement_text(msg: str) -> str:
    """The gist of a long instruction ("" if the message is not one): its sentences that set a
    constraint, without paths, links or pasted blocks, at most REQ_MAX_CHARS."""
    text = TAG_BLOCK.sub(" ", msg).strip()
    if not text or text.startswith("<") or COMPACT_SUMMARY.match(text) or len(text) > MAX_MSG_CHARS:
        return ""
    lines = [ln for ln in text.splitlines() if ln.strip() and not structured_line(ln)]
    text = PATH_OR_URL.sub(" ", " ".join(lines))
    words = text.split()
    if len(words) < REQ_MIN_WORDS or text.rstrip().endswith("?") or REQ_QUESTION.match(text.strip()):
        return ""
    parts = [p.strip(" ,;") for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    from dore.learn.grammar import asks
    keep = [p for p in parts if CONSTRAINT.search(p) and not p.rstrip().endswith("?") and len(p.split()) >= 4
            and not asks(p)]
    if not keep:
        return ""
    gist = " ".join(dict.fromkeys(keep))
    gist = re.sub(r"\s+", " ", gist).strip()
    if len(gist) > REQ_MAX_CHARS:
        gist = gist[:REQ_MAX_CHARS].rsplit(" ", 1)[0] + "…"
    return gist[:1].upper() + gist[1:]
