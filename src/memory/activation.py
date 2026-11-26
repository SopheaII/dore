"""How strongly a note is "in mind" (ACT-R base-level learning).

Each time the user says a note again or Claude uses it adds strength; strength fades as a power of the time since
(B = ln(sum of t_j^-d), d = 0.5: Anderson & Lebiere 1998; the power law of forgetting, Anderson & Schooler 1991).
A note repeated often fades slowly (the spacing effect). Stored per note: how many times (n), the first and the last
time; the times in between are taken as evenly spread (Petrov 2006's approximation), so no list of times is kept
and reading strength costs nothing. Nothing here deletes or hides a note from search: strength only decides what
comes to mind without a cue (the rules at a session start)."""

from __future__ import annotations

import math

DECAY = 0.5        # d: the usual ACT-R value
FADE_DAYS = 30.0   # in mind while at least as strong as one mention this many days ago
THRESHOLD = -DECAY * math.log(FADE_DAYS)
DAY = 86400.0


def strength(n: int, first: float, last: float, now: float) -> float:
    """Base-level activation of a note said or used `n` times, first at `first`, last at `last` (epoch seconds)."""
    n = max(1, n)
    t1 = max((now - last) / DAY, 1 / 24)  # days since the last time (at least an hour)
    tn = max((now - first) / DAY, t1)     # days since the first time
    s = t1 ** -DECAY
    if n > 1:
        if tn - t1 < 1e-9:  # all at once
            s += (n - 1) * t1 ** -DECAY
        else:  # the n-1 earlier times, evenly spread between first and last: their mean t^-d
            s += (n - 1) * (tn ** (1 - DECAY) - t1 ** (1 - DECAY)) / ((1 - DECAY) * (tn - t1))
    return math.log(s)


def in_mind(n: int, first: float, last: float, now: float) -> bool:
    return strength(n, first, last, now) >= THRESHOLD
