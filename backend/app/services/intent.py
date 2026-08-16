"""
Comparative-query intent detection — spec 2.7.

Regex first: cheap, deterministic, and covers the large majority of real
phrasing ("X vs Y", "X versus Y", "compare X and Y") with zero latency or
cost. The LLM fallback only fires when the query contains a comparison-ish
word ("compare"/"vs"/"versus") but the regex couldn't cleanly split it into
two names — covering unanticipated phrasing without paying an extra LLM
call on every single-ticker request, which is the overwhelming common case.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from app.services.llm import get_chat_model

logger = logging.getLogger(__name__)

_VS_PATTERN = re.compile(r"^\s*(.+?)\s+(?:vs\.?|versus)\s+(.+?)\s*$", re.I)
_COMPARE_PATTERN = re.compile(r"^\s*compare\s+(.+?)\s+(?:and|with|vs\.?|versus)\s+(.+?)\s*$", re.I)
_COMPARISON_HINT = re.compile(r"\b(vs\.?|versus|compare)\b", re.I)


def detect_compare_intent(query: str) -> Optional[tuple[str, str]]:
    """Returns (ticker_a, ticker_b) queries if this looks like a two-way
    comparison request, else None (the caller runs the normal single-ticker
    pipeline)."""
    q = query.strip()
    for pattern in (_VS_PATTERN, _COMPARE_PATTERN):
        m = pattern.match(q)
        if m:
            a, b = m.group(1).strip(), m.group(2).strip()
            if a and b:
                return a, b

    if _COMPARISON_HINT.search(q):
        return _llm_fallback(q)
    return None


def _llm_fallback(query: str) -> Optional[tuple[str, str]]:
    prompt = (
        "The following is a user query that may be asking to compare two "
        "Indian (NSE/BSE) stocks. If it clearly names exactly two "
        'companies/tickers to compare, respond ONLY with JSON: {"a": "...", '
        '"b": "..."}. If it does NOT clearly ask for a two-way stock '
        "comparison, respond with exactly the word: null\n\n"
        f"Query: {query}"
    )
    try:
        llm = get_chat_model(temperature=0)
        msg = llm.invoke(prompt)
        text = getattr(msg, "content", str(msg)).strip()
        if text.lower().strip(".") == "null":
            return None
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        data = json.loads(text[start : end + 1])
        a, b = str(data.get("a") or "").strip(), str(data.get("b") or "").strip()
        if a and b:
            return a, b
    except Exception as exc:
        logger.warning("compare-intent LLM fallback failed: %s", exc)
    return None
