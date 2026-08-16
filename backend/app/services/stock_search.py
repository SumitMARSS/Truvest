"""
Advanced stock search — turns whatever a user types into a ranked, scored
shortlist of NSE/BSE listings instead of a single all-or-nothing resolution.

Why this exists
---------------
Before this pass the only entry point was `resolve_ticker()`: one query in,
one ticker out, `TickerResolutionError` otherwise. That is the wrong shape for
a search box. "tata motor", "the maggi company", "largest private bank" and a
plain typo all failed identically, with no way for the user to recover except
guessing again. Search is inherently ambiguous, so the API should return
*candidates with confidence*, exactly like every other claim in this codebase
(core/confidence.py) — and let the user pick.

Retrieval layers, cheapest first — each one only runs if the layers above it
didn't already produce a confident answer:

  1. Local catalog (app/data/nse_universe.json, ~2.4k NSE symbols) + curated
     alias/brand overlay (stock_aliases.json). Zero network, sub-10ms, and the
     only layer that knows "HUL" is HINDUNILVR or "maggi" is NESTLEIND.
     Lexical retrieval over symbol / name / alias / brand-keyword / industry,
     with a char-trigram inverted index for typo tolerance ("relaince").
  2. Yahoo Finance search API — official-ish, free, no key. Covers what the
     bundled catalog can't: BSE-only listings, symbols listed after the last
     catalog rebuild. Also acts as *corroboration*: a name both layers agree on
     scores higher than one only the catalog guessed at.
  3. LLM interpretation — last resort, only for natural-language questions the
     lexical layers scored poorly ("which company makes jaguar cars"). Same
     gating philosophy as services/intent.py: never on the common path, and its
     output is not trusted directly — every company name it returns is resolved
     back through layer 1, so the LLM can suggest but never invent a ticker.

Scores are calibrated so the label means something: HIGH = we'd run this
without asking, MEDIUM = plausible, confirm it, LOW = weak, shown only because
there was nothing better.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

import httpx

from app.core.config import settings
from app.services.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
UNIVERSE_PATH = DATA_DIR / "nse_universe.json"
ALIASES_PATH = DATA_DIR / "stock_aliases.json"

YAHOO_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
_INDIA_EXCHANGES = {"NSI", "BSE", "BOM"}

# Score thresholds. Deliberately explicit constants rather than magic numbers
# sprinkled through the scorer, so the calibration is reviewable in one place.
HIGH_CONFIDENCE = 0.85
MEDIUM_CONFIDENCE = 0.62
# Below this, the lexical layers admit they're guessing — bring in the network.
YAHOO_TRIGGER = 0.90
# Below this AND multi-word: the query probably describes a company rather
# than naming it, which is the only case worth an LLM call.
LLM_TRIGGER = 0.55
# Results scoring below this fraction of the top hit are dropped as noise.
RELATIVE_FLOOR = 0.58

_PUNCT = re.compile(r"[^A-Z0-9&]+")
_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
# Trailing corporate suffixes: never part of how anyone searches.
_SUFFIX_TOKENS = {"LIMITED", "LTD", "PVT", "PRIVATE", "INC", "PLC"}
# Words that carry no identifying signal in a stock query.
_QUERY_STOPWORDS = {
    "SHARE", "SHARES", "STOCK", "STOCKS", "PRICE", "QUOTE", "TICKER", "SYMBOL",
    "NSE", "BSE", "INDIA", "INDIAN", "COMPANY", "COMPANIES", "CORP", "CORPORATION",
    "RESEARCH", "ANALYSE", "ANALYZE", "ANALYSIS", "REPORT", "BRIEF", "ABOUT",
    "SHOW", "ME", "TELL", "WHAT", "WHICH", "WHO", "IS", "ARE", "THE", "OF", "FOR",
    "A", "AN", "PLEASE", "GIVE", "FIND", "LOOK", "UP", "ON", "IN", "TO",
}
# Tokens skipped when deriving a company's initials, so "State Bank of India"
# yields SBI (what people type) rather than SBOI.
_ACRONYM_SKIP = {"OF", "AND", "THE", "&"}
# Words that turn a query into a sector browse rather than a name lookup.
# They're stopwords for matching, but they still carry intent.
_SECTOR_CUES = {"COMPANIES", "STOCKS", "SHARES", "SECTOR", "FIRMS", "PLAYERS", "NAMES"}

# Plain-language sector words → the industry labels NSE actually publishes.
_INDUSTRY_SYNONYMS = {
    "IT": "Information Technology",
    "TECH": "Information Technology",
    "TECHNOLOGY": "Information Technology",
    "SOFTWARE": "Information Technology",
    "BANK": "Financial Services",
    "BANKS": "Financial Services",
    "BANKING": "Financial Services",
    "NBFC": "Financial Services",
    "FINANCE": "Financial Services",
    "FINANCIAL": "Financial Services",
    "INSURANCE": "Financial Services",
    "PHARMA": "Healthcare",
    "PHARMACEUTICAL": "Healthcare",
    "PHARMACEUTICALS": "Healthcare",
    "HOSPITAL": "Healthcare",
    "HOSPITALS": "Healthcare",
    "HEALTHCARE": "Healthcare",
    "AUTO": "Automobile and Auto Components",
    "AUTOMOBILE": "Automobile and Auto Components",
    "CAR": "Automobile and Auto Components",
    "CARS": "Automobile and Auto Components",
    "FMCG": "Fast Moving Consumer Goods",
    "CONSUMER": "Fast Moving Consumer Goods",
    "CHEMICAL": "Chemicals",
    "CHEMICALS": "Chemicals",
    "METAL": "Metals & Mining",
    "METALS": "Metals & Mining",
    "STEEL": "Metals & Mining",
    "MINING": "Metals & Mining",
    "OIL": "Oil Gas & Consumable Fuels",
    "GAS": "Oil Gas & Consumable Fuels",
    "ENERGY": "Oil Gas & Consumable Fuels",
    "POWER": "Power",
    "ELECTRICITY": "Power",
    "REALTY": "Realty",
    "REAL ESTATE": "Realty",
    "TELECOM": "Telecommunication",
    "TELECOMMUNICATION": "Telecommunication",
    "CEMENT": "Construction Materials",
    "INFRA": "Construction",
    "INFRASTRUCTURE": "Construction",
    "MEDIA": "Media Entertainment & Publication",
    "TEXTILE": "Textiles",
    "TEXTILES": "Textiles",
    "DEFENCE": "Capital Goods",
    "CAPITAL GOODS": "Capital Goods",
}

# Compare-mode phrasing, detected here (regex only — no LLM in a keystroke
# path) so the UI can offer to switch modes while the user is still typing.
_VS_PATTERN = re.compile(r"^\s*(.+?)\s+(?:vs\.?|versus)\s+(.+?)\s*$", re.I)
_COMPARE_PATTERN = re.compile(
    r"^\s*compare\s+(.+?)\s+(?:and|with|vs\.?|versus)\s+(.+?)\s*$", re.I
)


@dataclass
class StockSuggestion:
    symbol: str  # bare NSE symbol, e.g. "RELIANCE"
    ticker: str  # yfinance-style, e.g. "RELIANCE.NS" — what the pipeline wants
    name: str
    exchange: str = "NSE"
    industry: Optional[str] = None
    score: float = 0.0
    confidence: str = "low"  # high | medium | low
    match_reason: str = ""
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# Catalog loading / indexing
# --------------------------------------------------------------------------


def _norm(text: str) -> str:
    """'Bajaj Auto Ltd.' -> 'BAJAJ AUTO LTD' (punctuation collapsed, & kept)."""
    return re.sub(r"\s+", " ", _PUNCT.sub(" ", text.upper())).strip()


def _compact(text: str) -> str:
    """'BAJAJ AUTO' -> 'BAJAJAUTO'; 'M&M' -> 'MM'. Symbol-space comparison."""
    return _NON_ALNUM.sub("", text.upper())


def _strip_suffixes(tokens: list[str]) -> list[str]:
    out = list(tokens)
    while out and out[-1] in _SUFFIX_TOKENS:
        out.pop()
    return out or list(tokens)


def _trigrams(text: str) -> set[str]:
    padded = f"  {text} "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


@dataclass
class _Entry:
    symbol: str
    name: str
    tier: int
    industry: Optional[str]
    sym_compact: str
    name_norm: str
    name_tokens: list[str]
    acronym: str
    aliases_norm: list[tuple[str, str]]  # (normalized, original) for reasons
    keywords: list[str]
    # Kept per-field, not merged: Jaccard against a merged symbol+name set is
    # dominated by whichever field is longer, so "relaince" scored no better
    # against RELIANCE than against unrelated names.
    sym_trigrams: set[str]
    name_trigrams: set[str]

    @property
    def trigrams(self) -> set[str]:
        return self.sym_trigrams | self.name_trigrams


@lru_cache(maxsize=1)
def _catalog() -> tuple[list[_Entry], dict[str, list[int]]]:
    """Returns (entries, trigram -> entry indices).

    Built once per process and memoised; ~2.4k entries load in a few ms.
    """
    try:
        universe = json.loads(UNIVERSE_PATH.read_text())
    except Exception as exc:  # pragma: no cover - packaging error, not runtime
        logger.error("stock universe missing/unreadable at %s: %s", UNIVERSE_PATH, exc)
        universe = {"stocks": []}

    try:
        overlay = json.loads(ALIASES_PATH.read_text()).get("entries", {})
    except Exception as exc:
        logger.warning("stock alias overlay unreadable (%s) — search degrades to names only", exc)
        overlay = {}

    entries: list[_Entry] = []
    trigram_index: dict[str, list[int]] = {}

    for stock in universe.get("stocks", []):
        symbol = stock["symbol"]
        name = stock["name"]
        name_norm = _norm(name)
        tokens = _strip_suffixes(name_norm.split())
        curated = overlay.get(symbol, {})
        aliases = [(_norm(a), a) for a in curated.get("aliases", []) if a]
        keywords = [k.upper() for k in curated.get("keywords", []) if k]

        entry = _Entry(
            symbol=symbol,
            name=name,
            tier=int(stock.get("tier", 1000)),
            industry=stock.get("industry"),
            sym_compact=_compact(symbol),
            name_norm=" ".join(tokens),
            name_tokens=tokens,
            acronym="".join(t[0] for t in tokens if t not in _ACRONYM_SKIP),
            aliases_norm=aliases,
            keywords=keywords,
            sym_trigrams=_trigrams(_compact(symbol)),
            name_trigrams=_trigrams(" ".join(tokens)),
        )
        idx = len(entries)
        entries.append(entry)
        for gram in entry.trigrams:
            trigram_index.setdefault(gram, []).append(idx)

    logger.info("stock search catalog loaded: %d symbols", len(entries))
    return entries, trigram_index


# --------------------------------------------------------------------------
# Query preparation + scoring
# --------------------------------------------------------------------------


@dataclass
class _Query:
    raw: str
    norm: str  # stopwords removed
    compact: str
    tokens: list[str]
    trigrams: set[str]
    word_count: int
    # "IT companies", "pharma stocks" — the user is browsing a sector, not
    # naming one company, so sector hits should outrank incidental name hits.
    sector_intent: bool
    industry: Optional[str]  # industry this query maps to, if any


def _prepare(query: str) -> _Query:
    norm_all = _norm(query)
    tokens_all = _strip_suffixes(norm_all.split())
    # "RELIANCE.NS" normalises to "RELIANCE NS" — drop the exchange suffix so
    # a yfinance-style ticker searches as well as a bare symbol does.
    if len(tokens_all) > 1 and tokens_all[-1] in {"NS", "BO"}:
        tokens_all = tokens_all[:-1]
    tokens = [t for t in tokens_all if t not in _QUERY_STOPWORDS]
    # Every token was noise ("show me the stock") — fall back to the raw tokens
    # rather than searching an empty string.
    if not tokens:
        tokens = tokens_all
    norm = " ".join(tokens)
    industry = _INDUSTRY_SYNONYMS.get(norm)
    if industry is None and len(tokens) <= 3:
        for token in tokens:
            industry = _INDUSTRY_SYNONYMS.get(token)
            if industry:
                break
    return _Query(
        raw=query,
        norm=norm,
        compact=_compact(norm),
        tokens=tokens,
        trigrams=_trigrams(norm) | _trigrams(_compact(norm)),
        word_count=len(tokens),
        sector_intent=bool(_SECTOR_CUES & set(tokens_all)),
        industry=industry,
    )


def _tier_boost(tier: int) -> float:
    """Popularity prior. Small on purpose: it breaks ties between comparable
    matches ("TATA" → TATASTEEL before TATAINVEST) without ever letting a
    large-cap outrank a genuinely better match on a small-cap."""
    if tier <= 50:
        return 0.07
    if tier <= 100:
        return 0.05
    if tier <= 500:
        return 0.025
    return 0.0


def _prefix_score(base: float, span: float, query_len: int, target_len: int) -> float:
    """Prefix matches get better as the typed prefix covers more of the target,
    so "REL" ranks RELIANCE above RELAXO only once enough characters agree."""
    if target_len <= 0:
        return base
    return base + span * min(1.0, query_len / target_len)


def _token_hits(token: str, name_tokens: list[str]) -> bool:
    """Does a typed word match a word of the company name?

    The reverse direction (a name word being a prefix of the typed word) is
    deliberately restricted: without a floor, single-letter name tokens like
    the "R" in "R R Kabel" matched *every* query starting with R, and a bare
    4-letter floor still matched "Info Edge" against "Infosys". A name word
    must be 4+ characters AND cover most of the typed word.
    """
    for nt in name_tokens:
        if len(token) >= 2 and nt.startswith(token):
            return True
        if len(nt) >= 4 and len(nt) >= 0.6 * len(token) and token.startswith(nt):
            return True
    return False


def _phrase_in(needle: str, haystack: str) -> bool:
    """Whole-word containment. Plain `in` matched the "EV" keyword inside
    "FEVICOL" and pulled a carmaker into an adhesives search."""
    if not needle or not haystack:
        return False
    return re.search(rf"(?:^|\s){re.escape(needle)}(?:\s|$)", haystack) is not None


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _score_entry(q: _Query, e: _Entry) -> tuple[float, str]:
    """Best (score, human-readable reason) across every match signal."""
    best = 0.0
    reason = ""

    def consider(score: float, why: str) -> None:
        nonlocal best, reason
        if score > best:
            best, reason = score, why

    # --- symbol -----------------------------------------------------------
    if q.compact and q.compact == e.sym_compact:
        consider(1.0, "Exact NSE symbol")
    elif q.compact and len(q.compact) >= 2 and e.sym_compact.startswith(q.compact):
        consider(
            _prefix_score(0.70, 0.22, len(q.compact), len(e.sym_compact)),
            f"Symbol starts with “{q.norm}”",
        )

    # --- curated aliases (RIL, HUL, ZOMATO, VODAFONE IDEA) ----------------
    for alias_norm, alias_raw in e.aliases_norm:
        if not alias_norm:
            continue
        if q.norm == alias_norm or q.compact == _compact(alias_norm):
            consider(0.96, f"Commonly searched as “{alias_raw}”")
        elif len(q.compact) >= 3 and alias_norm.startswith(q.norm):
            consider(
                _prefix_score(0.66, 0.22, len(q.norm), len(alias_norm)),
                f"Matches “{alias_raw}”",
            )

    # --- company name -----------------------------------------------------
    if q.norm and q.norm == e.name_norm:
        consider(0.97, "Exact company name")
    elif q.norm and e.name_norm.startswith(q.norm):
        consider(
            _prefix_score(0.68, 0.24, len(q.norm), len(e.name_norm)),
            "Company name starts with your text",
        )
    elif q.norm and len(q.norm) >= 4 and q.norm in e.name_norm:
        consider(0.58, "Your text appears in the company name")

    # --- initials (SBI, TCS, LT) -----------------------------------------
    if q.compact and len(q.compact) >= 2 and q.compact == e.acronym:
        consider(0.88, f"Initials of {e.name}")

    # --- every typed word matches a word of the name ----------------------
    if q.tokens:
        matched = sum(1 for t in q.tokens if _token_hits(t, e.name_tokens))
        coverage = matched / len(q.tokens)
        if coverage == 1.0:
            # Reward tighter names: "TATA STEEL" over "TATA STEEL LONG PRODUCTS".
            tightness = len(q.tokens) / max(len(e.name_tokens), 1)
            consider(0.72 + 0.12 * tightness, "Matches every word you typed")
        elif matched:
            consider(0.34 * coverage + 0.18, "Partial company-name match")

    # --- brand / product / plain-language keywords ------------------------
    # Two brands of the same company hitting one query ("jaguar cars") is much
    # stronger evidence than one, so distinct hits accumulate a small bonus.
    keyword_hits: list[str] = []
    keyword_base = 0.0
    for keyword in e.keywords:
        if q.norm == keyword:
            keyword_base = max(keyword_base, 0.80)
        elif _phrase_in(keyword, q.norm) or (len(q.norm) >= 4 and _phrase_in(q.norm, keyword)):
            keyword_base = max(keyword_base, 0.68)
        else:
            continue
        keyword_hits.append(keyword)
    if keyword_hits:
        consider(
            keyword_base + min(0.08, 0.04 * (len(keyword_hits) - 1)),
            "Known for " + ", ".join(f"“{k.title()}”" for k in keyword_hits[:2]),
        )

    # --- sector / industry ------------------------------------------------
    sector_hit = bool(e.industry) and q.industry == e.industry
    if sector_hit:
        consider(0.44, f"{e.industry} sector")

    # --- fuzzy (typos) ----------------------------------------------------
    # Only worth computing when nothing above landed cleanly.
    if best < 0.72 and len(q.compact) >= 4:
        similarity = max(
            _jaccard(q.trigrams, e.sym_trigrams), _jaccard(q.trigrams, e.name_trigrams)
        )
        if similarity >= 0.34:
            consider(0.28 + 0.52 * similarity, "Closest match to your spelling")

    # --- sector browse overrides -----------------------------------------
    # "IT companies" is a request for a sector, not for whichever symbol
    # happens to start with "IT". Unless the query also lands an outright
    # identity match, sector membership decides: members rank by prominence,
    # non-members are demoted rather than dropped (the user may still have
    # meant that one odd name).
    if q.sector_intent and q.industry and best < 0.95:
        if sector_hit:
            best, reason = 0.66, f"{e.industry} sector"
        else:
            best = min(best, 0.55)

    if best <= 0:
        return 0.0, ""
    return min(0.999, best + _tier_boost(e.tier)) if best < 1.0 else 1.0, reason


def _label(score: float) -> str:
    if score >= HIGH_CONFIDENCE:
        return "high"
    if score >= MEDIUM_CONFIDENCE:
        return "medium"
    return "low"


def _to_suggestion(e: _Entry, score: float, reason: str, sources: list[str]) -> StockSuggestion:
    return StockSuggestion(
        symbol=e.symbol,
        ticker=f"{e.symbol}.NS",
        name=e.name,
        exchange="NSE",
        industry=e.industry,
        score=round(score, 4),
        confidence=_label(score),
        match_reason=reason,
        sources=sources,
    )


# --------------------------------------------------------------------------
# Layer 1 — local catalog
# --------------------------------------------------------------------------


def local_suggestions(query: str, limit: int = 5, min_score: float = 0.30) -> list[StockSuggestion]:
    """Offline, sync, network-free ranking. Safe to call from worker threads
    (ticker_resolve uses it for did-you-mean on failure)."""
    q = _prepare(query)
    if not q.compact:
        return []

    entries, trigram_index = _catalog()

    # Cheap signals run over the whole catalog (2.4k entries is nothing);
    # the trigram index exists so the *fuzzy* branch only sees entries that
    # share at least some character shape with the query.
    fuzzy_candidates: set[int] = set()
    for gram in q.trigrams:
        for idx in trigram_index.get(gram, ()):
            fuzzy_candidates.add(idx)

    scored: list[tuple[float, str, _Entry]] = []
    for idx, entry in enumerate(entries):
        score, reason = _score_entry(q, entry)
        if score < min_score:
            continue
        if reason == "Closest match to your spelling" and idx not in fuzzy_candidates:
            continue
        scored.append((score, reason, entry))

    if not scored:
        return []
    scored.sort(key=lambda row: (-row[0], row[2].tier, row[2].symbol))

    # Relative floor: once there's a clear winner, padding the list out to
    # `limit` with far weaker names is worse than showing fewer options — a
    # short confident list is the whole point of scoring them.
    floor = max(min_score, RELATIVE_FLOOR * scored[0][0])
    return [
        _to_suggestion(e, s, r, ["catalog"]) for s, r, e in scored[:limit] if s >= floor
    ]


def catalog_exact(query: str) -> Optional[StockSuggestion]:
    """High-confidence offline resolution (symbol / exact name / curated alias)
    — used by ticker_resolve to skip a network round-trip."""
    hits = local_suggestions(query, limit=1)
    if hits and hits[0].score >= HIGH_CONFIDENCE:
        return hits[0]
    return None


# --------------------------------------------------------------------------
# Layer 2 — Yahoo Finance search
# --------------------------------------------------------------------------


async def _yahoo_suggestions(query: str, limit: int) -> list[StockSuggestion]:
    """Live listings from Yahoo, restricted to Indian equities. Best-effort:
    any failure returns [] and the local layer stands on its own."""
    try:
        async with httpx.AsyncClient(
            timeout=4.0, headers={"User-Agent": "Mozilla/5.0 (sourcebrief-search)"}
        ) as client:
            resp = await client.get(
                YAHOO_SEARCH_URL, params={"q": query, "quotesCount": 10, "newsCount": 0}
            )
            resp.raise_for_status()
            quotes = resp.json().get("quotes") or []
    except Exception as exc:
        logger.info("yahoo search unavailable for %r: %s", query, exc)
        return []

    q = _prepare(query)
    out: list[StockSuggestion] = []
    for quote in quotes:
        symbol = str(quote.get("symbol") or "")
        exch = str(quote.get("exchange") or "")
        if (quote.get("quoteType") or "").upper() != "EQUITY":
            continue
        if not (exch in _INDIA_EXCHANGES or symbol.endswith((".NS", ".BO"))):
            continue
        name = quote.get("longname") or quote.get("shortname") or symbol
        bare = symbol.replace(".NS", "").replace(".BO", "")
        # Score Yahoo hits with the same scorer, against a synthetic entry, so
        # a catalog result and a Yahoo result are directly comparable.
        pseudo = _Entry(
            symbol=bare,
            name=name,
            tier=1000,
            industry=None,
            sym_compact=_compact(bare),
            name_norm=" ".join(_strip_suffixes(_norm(name).split())),
            name_tokens=_strip_suffixes(_norm(name).split()),
            acronym="",
            aliases_norm=[],
            keywords=[],
            sym_trigrams=_trigrams(_compact(bare)),
            name_trigrams=_trigrams(_norm(name)),
        )
        score, reason = _score_entry(q, pseudo)
        if score <= 0:
            continue
        out.append(
            StockSuggestion(
                symbol=bare,
                ticker=symbol,
                name=name,
                exchange="BSE" if symbol.upper().endswith(".BO") else "NSE",
                score=round(min(score, 0.93), 4),
                confidence=_label(min(score, 0.93)),
                match_reason=reason or "Listed on Yahoo Finance",
                sources=["yahoo"],
            )
        )
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------
# Layer 3 — LLM interpretation of a natural-language question
# --------------------------------------------------------------------------

_LLM_PROMPT = (
    "A user is searching an Indian (NSE/BSE) stock research tool. Their query "
    "may describe a company instead of naming it.\n"
    "List up to 4 Indian LISTED companies the query most likely refers to, best "
    'first. Respond ONLY with JSON: {"companies": ["...", "..."]}. '
    'If nothing plausible, respond with {"companies": []}. '
    "Use each company's registered listed name.\n\n"
    "Query: "
)


def _llm_company_guesses(query: str) -> list[str]:
    from app.services.llm import get_chat_model  # local import: keeps startup light

    llm = get_chat_model(temperature=0)
    msg = llm.invoke(_LLM_PROMPT + query)
    text = getattr(msg, "content", str(msg)).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return []
    data = json.loads(text[start : end + 1])
    return [str(c).strip() for c in (data.get("companies") or []) if str(c).strip()][:4]


async def _llm_suggestions(query: str, limit: int) -> list[StockSuggestion]:
    """Interpret a descriptive query, then resolve each guess back through the
    catalog. The LLM never produces a ticker — it only proposes names, which
    keeps a hallucinated symbol structurally impossible."""
    if not settings.search_llm_fallback:
        return []
    try:
        names = await asyncio.wait_for(
            asyncio.to_thread(_llm_company_guesses, query), timeout=settings.search_llm_timeout_seconds
        )
    except Exception as exc:
        logger.info("search LLM fallback failed for %r: %s", query, exc)
        return []

    out: list[StockSuggestion] = []
    seen: set[str] = set()
    for name in names:
        for hit in local_suggestions(name, limit=1, min_score=0.55):
            if hit.symbol in seen:
                continue
            seen.add(hit.symbol)
            # Capped: an interpreted match is never "just run it" confident,
            # however cleanly the name resolved.
            hit.score = round(min(hit.score, 0.70), 4)
            hit.confidence = _label(hit.score)
            hit.match_reason = f"Interpreted from your question — “{name}”"
            hit.sources = ["llm", "catalog"]
            out.append(hit)
    return out[:limit]


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def detect_compare_pair(query: str) -> Optional[tuple[str, str]]:
    """Regex-only compare detection for the typeahead (the LLM-backed version
    in services/intent.py stays on the submit path)."""
    for pattern in (_VS_PATTERN, _COMPARE_PATTERN):
        m = pattern.match(query.strip())
        if m:
            a, b = m.group(1).strip(), m.group(2).strip()
            if a and b:
                return a, b
    return None


def _merge(primary: Iterable[StockSuggestion], extra: Iterable[StockSuggestion]) -> list[StockSuggestion]:
    """Union by symbol. A symbol both layers found is corroborated — the same
    logic the news pipeline applies to headlines — so it gets a small bump and
    keeps the better-scoring layer's reason."""
    merged: dict[str, StockSuggestion] = {s.symbol: s for s in primary}
    for candidate in extra:
        existing = merged.get(candidate.symbol)
        if existing is None:
            merged[candidate.symbol] = candidate
            continue
        if candidate.score > existing.score and candidate.match_reason:
            existing.match_reason = candidate.match_reason
        for src in candidate.sources:
            if src not in existing.sources:
                existing.sources.append(src)
        base = max(existing.score, candidate.score)
        existing.score = round(min(0.999, base + 0.05) if len(existing.sources) > 1 else base, 4)
        existing.confidence = _label(existing.score)
    return sorted(merged.values(), key=lambda s: (-s.score, s.symbol))


async def search_stocks(query: str, limit: int = 5) -> dict[str, Any]:
    """Full search: catalog → (maybe) Yahoo → (maybe) LLM, cached by query.

    Returns a JSON-ready dict: suggestions + how it was answered, so the UI can
    explain itself ("interpreted your question") instead of showing an
    unexplained list.
    """
    query = (query or "").strip()
    limit = max(1, min(limit, 10))
    if len(query) < 1:
        return {"query": query, "suggestions": [], "layers_used": [], "compare_pair": None}

    cache_key = f"{query.lower()}|{limit}"
    cached = await cache_get("stock_search", cache_key)
    if cached is not None:
        return cached

    layers = ["catalog"]
    # Over-fetch locally: the merge below can drop/reorder, and we want a full
    # `limit` list even after Yahoo duplicates collapse into catalog hits.
    suggestions = local_suggestions(query, limit=limit + 3)
    best = suggestions[0].score if suggestions else 0.0

    if best < YAHOO_TRIGGER:
        yahoo = await _yahoo_suggestions(query, limit=limit)
        if yahoo:
            layers.append("yahoo")
            suggestions = _merge(suggestions, yahoo)
            best = suggestions[0].score if suggestions else 0.0

    if best < LLM_TRIGGER and len(query.split()) >= 2:
        llm = await _llm_suggestions(query, limit=limit)
        if llm:
            layers.append("llm")
            suggestions = _merge(suggestions, llm)

    pair = detect_compare_pair(query)
    payload = {
        "query": query,
        "suggestions": [s.to_dict() for s in suggestions[:limit]],
        "layers_used": layers,
        "compare_pair": list(pair) if pair else None,
    }
    await cache_set("stock_search", cache_key, payload, settings.search_cache_ttl_seconds)
    return payload
