"""
Pure-regex deadline extraction: the no-LLM baseline.

It finds "<number> <time unit>" and picks the candidate closest to a bounding phrase
("within", "no later than", "below", ...). It cannot do arithmetic, spelled-out
numbers, or tell an overall deadline from a sub-budget; that is what the LLM is for.
"""
import re

_UNIT_MS = {"ms": 1.0, "msec": 1.0, "millisecond": 1.0, "milliseconds": 1.0,
            "s": 1000.0, "sec": 1000.0, "second": 1000.0, "seconds": 1000.0}
_NUMBER_UNIT = re.compile(
    r"(?<![\w/])(\d+(?:\.\d+)?(?:e-?\d+)?)\s*(ms|msec|milliseconds?|sec|seconds?|s)\b(?!\w)", re.I)
_BOUND = re.compile(r"(within|no later than|below|under|less than|at most|not exceed|<=?|timeout|limit|max)", re.I)


def regex_deadline(text: str):
    """Deadline in ms, or None when no '<number> <unit>' appears."""
    candidates = []
    for m in _NUMBER_UNIT.finditer(text):
        value = float(m.group(1)) * _UNIT_MS[m.group(2).lower()]
        before = text[max(0, m.start() - 30): m.start()]
        candidates.append((0 if _BOUND.search(before) else 1, m.start(), value))
    if not candidates:
        return None
    return sorted(candidates)[0][2]
