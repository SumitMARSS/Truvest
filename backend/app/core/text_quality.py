"""
Guard against degenerate LLM output reaching the user.

Why this exists: free/small models occasionally return non-empty but
meaningless text — observed live from `openai/gpt-oss-20b:free` on the
compare prompt:

    "? = is... is, isALG(?.. is?.....com.... ...………iqué………i…....…..…"

The existing fallbacks only fired when the model returned an EMPTY string,
so this sailed straight into the brief. Garbage prose in a research tool is
worse than an honest deterministic summary: it looks like the system is
broken *and* it's unreadable. This is a deterministic, testable gate — no
second LLM call to judge the first one.

Deliberately permissive: it's a garbage detector, not a quality grader. It
should reject word-salad and pass any genuinely-written paragraph, including
ones with Indian company names, ₹ amounts, and percentages.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z]{3,}")
# Characters we'd expect in ordinary English financial prose.
_EXPECTED_CHARS = re.compile(r"[A-Za-z0-9\s.,;:%()/'\"’\-+₹&$]")

MIN_LENGTH = 80
MIN_WORDS = 20
MIN_EXPECTED_CHAR_RATIO = 0.85


def looks_like_prose(text: str) -> bool:
    """True if `text` plausibly reads as written English prose."""
    if not text:
        return False
    stripped = text.strip()
    if len(stripped) < MIN_LENGTH:
        return False

    words = _WORD.findall(stripped)
    if len(words) < MIN_WORDS:
        return False

    expected = len(_EXPECTED_CHARS.findall(stripped))
    if expected / len(stripped) < MIN_EXPECTED_CHAR_RATIO:
        return False

    # Degenerate output tends to repeat one token over and over
    # ("is... is, is..."). Real prose has a varied vocabulary.
    lowered = [w.lower() for w in words]
    if len(set(lowered)) / len(lowered) < 0.35:
        return False

    return True
