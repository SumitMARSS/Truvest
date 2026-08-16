"""
SEBI-safe language pass — deterministic, rules-based, no LLM judgment call.

Why rules instead of "ask the LLM to make this compliant": an LLM's idea of
"compliant" drifts silently between calls, models, and prompt tweaks, and you
cannot produce an audit trail of *why* it changed something. A regex table
is boring, but every rewrite is reproducible and logged (input phrase ->
output phrase), which is the actual artifact a compliance reviewer would
ask for. This is intentionally the least "AI" module in the codebase.

Scope note: "buy"/"sell" are rewritten only in rating/recommendation
contexts ("buy rating", "we recommend buying"), not as bare words — blanket
substring-stripping "buy" would also mangle unrelated prose like "buyback"
or "buyers". That's a deliberate scoping decision, not an oversight.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RewriteRule:
    pattern: re.Pattern
    replacement: str
    reason: str


_RULES: list[RewriteRule] = [
    RewriteRule(
        re.compile(r"\bexpected to (?:lift|boost|drive up|push up) the stock\b", re.I),
        "historically associated with short-term price reaction",
        "forward-looking price-lift claim",
    ),
    RewriteRule(
        re.compile(r"\bexpected to (?:weigh on|drag down|hurt) the stock\b", re.I),
        "historically associated with short-term downward price reaction",
        "forward-looking price-drop claim",
    ),
    RewriteRule(
        re.compile(r"\btarget price(?:s)?\b", re.I),
        "historical price range",
        "'target price' is investment advice, not observation",
    ),
    RewriteRule(
        re.compile(r"\b(?:strong |initiate(?:s|d)? (?:a |an )?)?buy rating\b", re.I),
        "positive analyst coverage",
        "'buy rating' is a directive, not observation",
    ),
    RewriteRule(
        re.compile(r"\b(?:strong |initiate(?:s|d)? (?:a |an )?)?sell rating\b", re.I),
        "negative analyst coverage",
        "'sell rating' is a directive, not observation",
    ),
    RewriteRule(
        re.compile(r"\bwe recommend (buying|selling)\b", re.I),
        "historical patterns show",
        "direct buy/sell recommendation",
    ),
    RewriteRule(
        re.compile(r"\byou should (buy|sell|invest)\b", re.I),
        "historical patterns show",
        "direct investment directive to the reader",
    ),
    RewriteRule(
        re.compile(r"\bwill (?:rise|rally|surge|jump|climb|gain)\b", re.I),
        "has historically moved higher in similar situations",
        "future-tense price prediction",
    ),
    RewriteRule(
        re.compile(r"\bwill (?:fall|drop|decline|plunge|crash|slide)\b", re.I),
        "has historically moved lower in similar situations",
        "future-tense price prediction",
    ),
    RewriteRule(
        re.compile(r"\bis (?:likely|poised|set) to (?:rise|rally|surge|jump|gain|climb)\b", re.I),
        "has shown similar upward moves historically",
        "predictive framing",
    ),
    RewriteRule(
        re.compile(r"\bis (?:likely|poised|set) to (?:fall|drop|decline|plunge|slide)\b", re.I),
        "has shown similar downward moves historically",
        "predictive framing",
    ),
    RewriteRule(
        re.compile(r"\bguaranteed returns?\b", re.I),
        "no guaranteed outcome — past performance is not indicative of future results",
        "guarantee language is prohibited in investment commentary",
    ),
]

# (draft key, list of nested paths) — every free-text field that can carry
# LLM-authored prose and therefore needs the pass run over it.
_TEXT_FIELDS: tuple[str, ...] = ("analyst_summary",)


def rewrite_text(text: str, field: str) -> tuple[str, list[dict[str, Any]]]:
    """Apply every rule once to `text`. Returns (rewritten_text, log_entries)."""
    if not text:
        return text, []
    log: list[dict[str, Any]] = []
    out = text
    for rule in _RULES:
        def _sub(m: re.Match, rule: RewriteRule = rule) -> str:
            log.append(
                {
                    "field": field,
                    "input_phrase": m.group(0),
                    "output_phrase": rule.replacement,
                    "reason": rule.reason,
                }
            )
            return rule.replacement

        out = rule.pattern.sub(_sub, out)
    return out, log


def apply_compliance_filter(draft: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run the rewrite pass over every free-text field in a draft brief.
    Returns (new_draft, full_audit_log) — never mutates the input dict."""
    out = dict(draft)
    full_log: list[dict[str, Any]] = []

    for field in _TEXT_FIELDS:
        text = out.get(field) or ""
        rewritten, log = rewrite_text(text, field)
        out[field] = rewritten
        full_log.extend(log)

    new_news = []
    for i, n in enumerate(out.get("news") or []):
        n2 = dict(n)
        for sub_field in ("rationale", "impact"):
            rewritten, log = rewrite_text(n2.get(sub_field) or "", f"news[{i}].{sub_field}")
            n2[sub_field] = rewritten
            full_log.extend(log)
        new_news.append(n2)
    out["news"] = new_news

    new_risks = []
    for i, r in enumerate(out.get("risks") or []):
        r2 = dict(r)
        rewritten, log = rewrite_text(r2.get("detail") or "", f"risks[{i}].detail")
        r2["detail"] = rewritten
        full_log.extend(log)
        new_risks.append(r2)
    out["risks"] = new_risks

    return out, full_log
