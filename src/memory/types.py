"""The memory record and the rules for which records search may return."""

from __future__ import annotations

from dataclasses import dataclass

TRUST_LEVELS = ("verified", "unverified", "wrong")

# Which rows belong in the vector index (keep in sync with `searchable`).
SEARCHABLE_SQL = ("archived=0 AND trust!='wrong' AND NOT (kind='answer' AND trust!='verified') "
                  "AND replaced_by IS NULL")


def searchable(kind: str, trust: str, archived: bool = False, replaced: bool = False) -> bool:
    """True if an item may be returned by search. The model's own answers only count
    once the user approves them, so made-up answers can't reinforce themselves. A fact
    replaced by a newer one (`replaced_by`) is kept but no longer returned."""
    return (not archived and not replaced and trust != "wrong"
            and not (kind == "answer" and trust != "verified"))


@dataclass
class Memory:
    id: int
    content: str
    kind: str
    source: str
    trust: str
    protected: bool
    archived: bool
    created: float
    last_used: float | None
    times_used: int
    times_seen: int
    feedback: int
    project: str = ""
    last_seen: float | None = None  # last time the same fact was stated again
    replaced_by: int | None = None   # newer memory that replaced this one (kept, not searched)
    valid_to: float | None = None    # when it was replaced
    tries: int = 0  # times shown while on trial (or a request) with Claude's reply checked after it
    uses: int = 0   # times Claude's reply clearly used it (`hooks.use_check`)
    rule_when: str | None = None  # a rule's situation and forbidden words, JSON lists (`learn.judge`)
    rule_not: str | None = None
    group_id: int | None = None  # the group note (a list's title) this note is an item of (`MemoryStore.add_group`)
    similarity: float = 0.0
    keyword: float = 0.0  # share of the query's keywords found in this memory
    rank: float = 0.0
    focus: float = 0.0  # similarity minus how much the note matches any question (hub correction)


_COLS = ("id, content, kind, source, trust, protected, archived, created, last_used, times_used, times_seen, "
         "feedback, project, last_seen, replaced_by, valid_to, tries, uses, rule_when, rule_not, group_id")


def _row(r) -> Memory:
    return Memory(
        id=r[0], content=r[1], kind=r[2], source=r[3], trust=r[4], protected=bool(r[5]),
        archived=bool(r[6]), created=r[7], last_used=r[8], times_used=r[9], times_seen=r[10], feedback=r[11],
        project=r[12], last_seen=r[13], replaced_by=r[14], valid_to=r[15], tries=r[16], uses=r[17], rule_when=r[18], rule_not=r[19],
        group_id=r[20],
    )


def on_trial(m: Memory) -> bool:
    """A chat-learned statement not yet proven (used by Claude, said again in another session, or protected)."""
    return (m.kind == "statement" and m.source == "user" and not m.protected
            and m.uses == 0 and m.times_seen < 2)
