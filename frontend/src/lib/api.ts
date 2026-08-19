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

export interface StockSuggestion {
  symbol: string;
  ticker: string;
  name: string;
  exchange: string;
  industry?: string | null;
  score: number;
  confidence: Confidence;
  match_reason: string;
  /** Which retrieval layers found this candidate: catalog | yahoo | llm */
  sources: string[];
}

export interface StockSearchResult {
  query: string;
  suggestions: StockSuggestion[];
  layers_used: string[];
  /** Set when the text reads as "A vs B" — lets the UI offer compare mode */
  compare_pair?: [string, string] | null;
}

/** One selectable LLM from GET /api/v1/models. */
export interface LlmModel {
  id: string;
  /** Display name, vendor prefix and "(free)" suffix already stripped. */
  name: string;
  vendor: string;
  context_length?: number | null;
  description: string;
  free: boolean;
  /** Spends hidden thinking tokens — slower, worth flagging before a run. */
  reasoning: boolean;
}

export interface ModelCatalog {
  provider: string;
  /** Server default — used when the user hasn't picked. */
  default: string;
  /** False on paid providers, where the model is fixed by server config. */
  selectable: boolean;
  /** False when the list is the offline fallback rather than a live fetch. */
  live: boolean;
  note: string;
  models: LlmModel[];
}

export interface ResearchJob {
  job_id: string;
  status: JobStatus;
  query: string;
  mode: "single" | "compare";
  /** The LLM this job actually ran on. */
  model?: string | null;
  progress?: string | null;
  brief?: ResearchBrief | null;
  compare_brief?: CompareBrief | null;
  error?: string | null;
  error_code?:
    | "ticker_not_found"
    | "data_provider_unavailable"
    | "timeout"
    | "internal_error"
    | null;
  /** Ranked "did you mean" options when a ticker could not be resolved */
  suggestions?: StockSuggestion[];
}

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

/**
 * Start a research job. `model` is optional — omitting it runs the server
 * default. The backend validates the id against its free-model allowlist and
 * answers 400 with a readable reason if it isn't selectable, so surface that
 * message rather than a bare status code.
 */
export async function startResearch(query: string, model?: string | null): Promise<ResearchJob> {
  const res = await fetch(`${API_URL}/api/v1/research`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(model ? { query, model } : { query }),
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .then((body) => (typeof body?.detail === "string" ? body.detail : null))
      .catch(() => null);
    throw new Error(detail || `Failed to start research (${res.status})`);
  }
  return res.json();
}

/**
 * The models the user may pick from. Returns null on failure — the picker then
 * hides itself and every run uses the server default, which is exactly how the
 * app behaved before model selection existed.
 */
export async function listModels(): Promise<ModelCatalog | null> {
  try {
    const res = await fetch(`${API_URL}/api/v1/models`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function getResearch(jobId: string): Promise<ResearchJob> {
  const res = await fetch(`${API_URL}/api/v1/research/${jobId}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch job (${res.status})`);
  }
  return res.json();
}

/**
 * Typeahead search. Runs on every (debounced) keystroke, so failures are
 * returned as an empty result rather than thrown — a flaky suggestion call
 * must never block the user from submitting what they typed.
 */
export async function searchStocks(
  query: string,
  limit = 5,
  signal?: AbortSignal,
): Promise<StockSearchResult> {
  const empty: StockSearchResult = { query, suggestions: [], layers_used: [], compare_pair: null };
  const q = query.trim();
  if (!q) return empty;
  const res = await fetch(
    `${API_URL}/api/v1/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    { signal },
  );
  if (!res.ok) return empty;
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
