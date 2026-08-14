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
    # India-only market mode — US tickers are not supported
    # UPDATE: add force_refresh, depth (quick|standard|deep)


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


class Fundamentals(BaseModel):
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    eps_ttm: Optional[float] = None
    revenue_ttm: Optional[float] = None
    profit_margin: Optional[float] = None
    # UPDATE: add debt/equity, free cash flow, sector/industry
    source_ids: list[str] = Field(default_factory=list)


class NewsItem(BaseModel):
    title: str
    url: Optional[str] = None
    published: Optional[str] = None
    sentiment: SentimentLabel = SentimentLabel.neutral
    rationale: str = ""
    # Expected impact and horizon, e.g. "Likely positive in the near term"
    impact: str = ""
    source_ids: list[str] = Field(default_factory=list)


class FilingHighlight(BaseModel):
    form: str  # INDIA_RESULTS | EARNINGS_CALENDAR | RESULTS_STUB
    filed_at: Optional[str] = None
    accession: Optional[str] = None
    risk_factors: list[str] = Field(default_factory=list)
    mda_highlights: list[str] = Field(default_factory=list)
    url: Optional[str] = None
    source_ids: list[str] = Field(default_factory=list)


class CalcMetrics(BaseModel):
    pe_from_price_eps: Optional[float] = None
    yoy_revenue_growth: Optional[float] = None
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    # UPDATE: add RSI, drawdown, volatility
    notes: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class RiskFlag(BaseModel):
    severity: str  # low | medium | high
    title: str
    detail: str
    source_ids: list[str] = Field(default_factory=list)


class PricePoint(BaseModel):
    """Downsampled close for the frontend price chart."""

    date: str
    close: float


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
    analyst_summary: str = ""
    risks: list[RiskFlag] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    critic_passed: bool = False
    critic_notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchJobResponse(BaseModel):
    job_id: str
    status: JobStatus
    query: str
    progress: Optional[str] = None
    brief: Optional[ResearchBrief] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
