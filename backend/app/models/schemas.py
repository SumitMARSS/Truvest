"""Pydantic API + domain schemas for research briefs."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class SentimentLabel(str, Enum):
    bullish = "bullish"
    bearish = "bearish"
    neutral = "neutral"
    # Fewer than 2 independent corroborating sources — the schema forbids a
    # directional label in that case rather than let one headline read as
    # a confident call (docs spec 2.5 / core/confidence.py).
    insufficient_data = "insufficient_data"


class ConfidenceLevel(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class SourceRef(BaseModel):
    """Every claim in the brief must cite one of these."""

    id: str
    title: str
    url: Optional[str] = None
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    provider: str  # yfinance | tavily | tavily_india | alpha_vantage | calc


class ResearchRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="NSE/BSE ticker or Indian company name (e.g. RELIANCE, TCS.NS)",
    )
    # Which LLM writes this brief. Omit to use the server default. Validated
    # against the free-model allowlist in services/model_catalog.py before the
    # job starts — an arbitrary id here must never reach the provider, since
    # the API key is the server's.
    model: Optional[str] = Field(
        None,
        max_length=120,
        description="LLM id from GET /api/v1/models (e.g. openai/gpt-oss-20b:free)",
    )
    # India-only market mode — US tickers are not supported
    # UPDATE: add force_refresh, depth (quick|standard|deep)


class LlmModelInfo(BaseModel):
    """One selectable model in the picker."""

    id: str = Field(..., description="Provider-qualified id passed back on /research")
    name: str = Field(..., description="Display name, vendor prefix stripped")
    vendor: str = "Other"
    context_length: Optional[int] = None
    description: str = ""
    free: bool = True
    # Reasoning models are slower and burn output budget on hidden thinking —
    # worth flagging in the UI so a slow run isn't a surprise.
    reasoning: bool = False


class ModelCatalogResponse(BaseModel):
    provider: str
    default: str
    # False for paid providers (openai/anthropic) — the UI renders read-only.
    selectable: bool = True
    # False when the list is the offline fallback rather than a live fetch.
    live: bool = True
    note: str = ""
    models: list[LlmModelInfo] = Field(default_factory=list)


class StockSuggestion(BaseModel):
    """One ranked candidate from the advanced search (services/stock_search.py).

    `score`/`confidence` are the same trust vocabulary the brief itself uses:
    high = safe to run without asking, medium = plausible, low = weak.
    """

    symbol: str = Field(..., description="Bare NSE symbol, e.g. RELIANCE")
    ticker: str = Field(..., description="yfinance-style ticker, e.g. RELIANCE.NS")
    name: str
    exchange: str = "NSE"
    industry: Optional[str] = None
    score: float = Field(..., ge=0.0, le=1.0)
    confidence: ConfidenceLevel = ConfidenceLevel.low
    match_reason: str = ""
    # catalog | yahoo | llm — which retrieval layers found this candidate
    sources: list[str] = Field(default_factory=list)


class StockSearchResponse(BaseModel):
    query: str
    suggestions: list[StockSuggestion] = Field(default_factory=list)
    # Which layers actually ran, so the UI can say how the answer was produced
    layers_used: list[str] = Field(default_factory=list)
    # Set when the query reads as "A vs B" — lets the UI offer compare mode
    compare_pair: Optional[list[str]] = None


class PriceAction(BaseModel):
    last_price: Optional[float] = None
    currency: Optional[str] = None
    change_1d_pct: Optional[float] = None
    change_1w_pct: Optional[float] = None
    change_1m_pct: Optional[float] = None
    change_3m_pct: Optional[float] = None
    change_6m_pct: Optional[float] = None
    change_1y_pct: Optional[float] = None
    change_3y_pct: Optional[float] = None
    volume: Optional[float] = None
    avg_volume: Optional[float] = None
    source_ids: list[str] = Field(default_factory=list)
    confidence: Optional[ConfidenceLevel] = None
    confidence_reason: Optional[str] = None


class Fundamentals(BaseModel):
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    eps_ttm: Optional[float] = None
    revenue_ttm: Optional[float] = None
    profit_margin: Optional[float] = None
    # UPDATE: add debt/equity, free cash flow, sector/industry
    source_ids: list[str] = Field(default_factory=list)
    confidence: Optional[ConfidenceLevel] = None
    confidence_reason: Optional[str] = None


class NewsItem(BaseModel):
    title: str
    url: Optional[str] = None
    published: Optional[str] = None
    sentiment: SentimentLabel = SentimentLabel.neutral
    rationale: str = ""
    # Expected impact and horizon, e.g. "Likely positive in the near term"
    impact: str = ""
    source_ids: list[str] = Field(default_factory=list)
    # How many independent sources (RSS feeds + Tavily) report this story
    corroboration_count: int = 1
    confidence: Optional[ConfidenceLevel] = None
    confidence_reason: Optional[str] = None


class FilingHighlight(BaseModel):
    form: str  # INDIA_RESULTS | EARNINGS_CALENDAR | RESULTS_STUB
    filed_at: Optional[str] = None
    accession: Optional[str] = None
    risk_factors: list[str] = Field(default_factory=list)
    mda_highlights: list[str] = Field(default_factory=list)
    url: Optional[str] = None
    source_ids: list[str] = Field(default_factory=list)
    confidence: Optional[ConfidenceLevel] = None
    confidence_reason: Optional[str] = None


class CalcMetrics(BaseModel):
    pe_from_price_eps: Optional[float] = None
    yoy_revenue_growth: Optional[float] = None
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    # UPDATE: add RSI, drawdown, volatility
    notes: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    confidence: Optional[ConfidenceLevel] = None
    confidence_reason: Optional[str] = None


class RiskFlag(BaseModel):
    severity: str  # low | medium | high
    title: str
    detail: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: Optional[ConfidenceLevel] = None
    confidence_reason: Optional[str] = None


class PricePoint(BaseModel):
    """Downsampled close for the frontend price chart."""

    date: str
    close: float


class PeBandPoint(BaseModel):
    date: str
    pe: float


class PeBand(BaseModel):
    """Rolling TTM P/E band from historical price x EPS (spec 2.1)."""

    available: bool = False
    reason: Optional[str] = None
    series: list[PeBandPoint] = Field(default_factory=list)
    band_min: Optional[float] = None
    band_max: Optional[float] = None
    band_avg: Optional[float] = None
    partial_history: bool = False
    quarters_used: Optional[int] = None


class SectorPe(BaseModel):
    available: bool = False
    reason: Optional[str] = None
    sector: Optional[str] = None
    index: Optional[str] = None
    pe: Optional[float] = None
    as_of: Optional[str] = None
    source: Optional[str] = None  # nse_live | static_fallback


class ValuationContext(BaseModel):
    pe_band: PeBand = Field(default_factory=PeBand)
    sector_pe: SectorPe = Field(default_factory=SectorPe)
    source_ids: list[str] = Field(default_factory=list)


class PeerRow(BaseModel):
    ticker: str
    company_name: Optional[str] = None
    last_price: Optional[float] = None
    currency: Optional[str] = None
    change_1y_pct: Optional[float] = None
    pe_ratio: Optional[float] = None
    market_cap: Optional[float] = None
    profit_margin: Optional[float] = None
    yoy_revenue_growth: Optional[float] = None
    is_subject: bool = False


class PeerComparison(BaseModel):
    """Spec 2.3 — reuses market+calc across a static, curated peer group."""

    available: bool = False
    reason: Optional[str] = None
    sector: Optional[str] = None
    rows: list[PeerRow] = Field(default_factory=list)


class Shareholding(BaseModel):
    """Spec 2.2 — promoter holding % + QoQ delta only in v1."""

    available: bool = False
    reason: Optional[str] = None
    as_of: Optional[str] = None
    promoter_pct: Optional[float] = None
    promoter_qoq_delta: Optional[float] = None
    prior_quarter_date: Optional[str] = None
    public_pct: Optional[float] = None
    provider: Optional[str] = None
    quarters_available: Optional[int] = None


class ResearchBrief(BaseModel):
    ticker: str
    company_name: Optional[str] = None
    as_of: datetime = Field(default_factory=datetime.utcnow)
    price_action: PriceAction = Field(default_factory=PriceAction)
    price_history: list[PricePoint] = Field(default_factory=list)
    fundamentals: Fundamentals = Field(default_factory=Fundamentals)
    news: list[NewsItem] = Field(default_factory=list)
    overall_news_sentiment: Optional[SentimentLabel] = None
    filings: list[FilingHighlight] = Field(default_factory=list)
    calculations: CalcMetrics = Field(default_factory=CalcMetrics)
    valuation: ValuationContext = Field(default_factory=ValuationContext)
    peer_comparison: PeerComparison = Field(default_factory=PeerComparison)
    shareholding: Shareholding = Field(default_factory=Shareholding)
    analyst_summary: str = ""
    risks: list[RiskFlag] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    # Honest, user-visible record of any section that degraded gracefully
    # instead of crashing the brief (e.g. "market data unavailable this run").
    # Never fabricate data to fill a gap — always list it here instead.
    data_gaps: list[str] = Field(default_factory=list)
    critic_passed: bool = False
    critic_notes: list[str] = Field(default_factory=list)
    # Audit trail for the SEBI-safe language pass — every rewrite the
    # deterministic compliance filter made, input phrase -> output phrase.
    compliance_log: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompareBrief(BaseModel):
    """Spec 2.7 — joins two independently-produced ResearchBriefs. Each one
    went through the FULL single-ticker pipeline (planner/workers/critic/
    retry) on its own; this only adds a metrics table + narrative on top."""

    tickers: list[str]
    briefs: list[ResearchBrief]
    metrics_table: list[dict[str, Any]] = Field(default_factory=list)
    comparison_summary: str = ""
    as_of: datetime = Field(default_factory=datetime.utcnow)


class ResearchJobResponse(BaseModel):
    job_id: str
    status: JobStatus
    query: str
    progress: Optional[str] = None
    # single | compare — tells the frontend which of brief/compare_brief to render
    mode: str = "single"
    # The LLM that actually ran this job (resolved default, or the user's pick),
    # so a finished brief can say which model wrote it.
    model: Optional[str] = None
    brief: Optional[ResearchBrief] = None
    compare_brief: Optional[CompareBrief] = None
    error: Optional[str] = None
    # ticker_not_found | timeout | internal_error — lets the frontend show a
    # tailored message instead of one generic failure state (docs/AUDIT.md #1.3)
    error_code: Optional[str] = None
    # Populated on error_code=ticker_not_found: ranked "did you mean" options
    # so a failed lookup is recoverable in one click instead of a retype.
    suggestions: list[StockSuggestion] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
