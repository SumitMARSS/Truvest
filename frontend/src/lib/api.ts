export type JobStatus = "pending" | "running" | "completed" | "failed";

export type Sentiment = "bullish" | "bearish" | "neutral" | "insufficient_data";

export type Confidence = "high" | "medium" | "low";

export interface SourceRef {
  id: string;
  title: string;
  url?: string | null;
  provider: string;
  retrieved_at?: string;
}

export interface ConfidenceFields {
  confidence?: Confidence | null;
  confidence_reason?: string | null;
}

export interface PriceAction extends ConfidenceFields {
  last_price?: number | null;
  currency?: string | null;
  change_1d_pct?: number | null;
  change_1w_pct?: number | null;
  change_1m_pct?: number | null;
  change_3m_pct?: number | null;
  change_6m_pct?: number | null;
  change_1y_pct?: number | null;
  change_3y_pct?: number | null;
  volume?: number | null;
  source_ids: string[];
}

export interface Fundamentals extends ConfidenceFields {
  market_cap?: number | null;
  pe_ratio?: number | null;
  eps_ttm?: number | null;
  revenue_ttm?: number | null;
  profit_margin?: number | null;
  source_ids: string[];
}

export interface NewsItem extends ConfidenceFields {
  title: string;
  url?: string | null;
  published?: string | null;
  sentiment: Sentiment;
  rationale?: string;
  impact?: string;
  source_ids: string[];
  corroboration_count: number;
}

export interface FilingHighlight extends ConfidenceFields {
  form: string;
  filed_at?: string | null;
  url?: string | null;
  risk_factors: string[];
  mda_highlights: string[];
  source_ids: string[];
}

export interface CalcMetrics extends ConfidenceFields {
  pe_from_price_eps?: number | null;
  yoy_revenue_growth?: number | null;
  sma_20?: number | null;
  sma_50?: number | null;
  notes: string[];
  source_ids: string[];
}

export interface RiskFlag extends ConfidenceFields {
  severity: string;
  title: string;
  detail: string;
  source_ids: string[];
}

export interface PeBandPoint {
  date: string;
  pe: number;
}

export interface PeBand {
  available: boolean;
  reason?: string | null;
  series: PeBandPoint[];
  band_min?: number | null;
  band_max?: number | null;
  band_avg?: number | null;
  partial_history: boolean;
  quarters_used?: number | null;
}

export interface SectorPe {
  available: boolean;
  reason?: string | null;
  sector?: string | null;
  index?: string | null;
  pe?: number | null;
  as_of?: string | null;
  source?: string | null;
}

export interface ValuationContext {
  pe_band: PeBand;
  sector_pe: SectorPe;
  source_ids: string[];
}

export interface PeerRow {
  ticker: string;
  company_name?: string | null;
  last_price?: number | null;
  currency?: string | null;
  change_1y_pct?: number | null;
  pe_ratio?: number | null;
  market_cap?: number | null;
  profit_margin?: number | null;
  yoy_revenue_growth?: number | null;
  is_subject: boolean;
}

export interface PeerComparison {
  available: boolean;
  reason?: string | null;
  sector?: string | null;
  rows: PeerRow[];
}

export interface Shareholding {
  available: boolean;
  reason?: string | null;
  as_of?: string | null;
  promoter_pct?: number | null;
  promoter_qoq_delta?: number | null;
  prior_quarter_date?: string | null;
  public_pct?: number | null;
  provider?: string | null;
  quarters_available?: number | null;
}

export interface ComplianceLogEntry {
  field: string;
  input_phrase: string;
  output_phrase: string;
  reason: string;
}

export interface ResearchBrief {
  ticker: string;
  company_name?: string | null;
  as_of: string;
  price_action: PriceAction;
  price_history: Array<{ date: string; close: number }>;
  fundamentals: Fundamentals;
  news: NewsItem[];
  overall_news_sentiment?: Sentiment | null;
  filings: FilingHighlight[];
  calculations: CalcMetrics;
  valuation: ValuationContext;
  peer_comparison: PeerComparison;
  shareholding: Shareholding;
  analyst_summary: string;
  risks: RiskFlag[];
  sources: SourceRef[];
  data_gaps: string[];
  critic_passed: boolean;
  critic_notes: string[];
  compliance_log: ComplianceLogEntry[];
  metadata: Record<string, unknown>;
}

export interface CompareBrief {
  tickers: string[];
  briefs: ResearchBrief[];
  metrics_table: Array<Record<string, unknown>>;
  comparison_summary: string;
  as_of: string;
}

export interface ResearchJob {
  job_id: string;
  status: JobStatus;
  query: string;
  mode: "single" | "compare";
  progress?: string | null;
  brief?: ResearchBrief | null;
  compare_brief?: CompareBrief | null;
  error?: string | null;
  error_code?: "ticker_not_found" | "timeout" | "internal_error" | null;
}

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function startResearch(query: string): Promise<ResearchJob> {
  const res = await fetch(`${API_URL}/api/v1/research`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) {
    throw new Error(`Failed to start research (${res.status})`);
  }
  return res.json();
}

export async function getResearch(jobId: string): Promise<ResearchJob> {
  const res = await fetch(`${API_URL}/api/v1/research/${jobId}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch job (${res.status})`);
  }
  return res.json();
}

export interface HealthInfo {
  status: string;
  llm_provider: string;
  llm_model: string;
}

export async function getHealth(): Promise<HealthInfo | null> {
  try {
    const res = await fetch(`${API_URL}/api/v1/health`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

// UPDATE: add subscribeResearchEvents(jobId) using EventSource for SSE live progress
