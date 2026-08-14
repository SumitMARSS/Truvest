export type JobStatus = "pending" | "running" | "completed" | "failed";

export type Sentiment = "bullish" | "bearish" | "neutral";

export interface SourceRef {
  id: string;
  title: string;
  url?: string | null;
  provider: string;
  retrieved_at?: string;
}

export interface ResearchBrief {
  ticker: string;
  company_name?: string | null;
  as_of: string;
  price_action: {
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
  };
  price_history: Array<{ date: string; close: number }>;
  fundamentals: {
    market_cap?: number | null;
    pe_ratio?: number | null;
    eps_ttm?: number | null;
    revenue_ttm?: number | null;
    profit_margin?: number | null;
    source_ids: string[];
  };
  news: Array<{
    title: string;
    url?: string | null;
    published?: string | null;
    sentiment: Sentiment;
    rationale?: string;
    impact?: string;
    source_ids: string[];
  }>;
  overall_news_sentiment?: Sentiment | null;
  filings: Array<{
    form: string;
    filed_at?: string | null;
    url?: string | null;
    risk_factors: string[];
    mda_highlights: string[];
    source_ids: string[];
  }>;
  calculations: {
    pe_from_price_eps?: number | null;
    yoy_revenue_growth?: number | null;
    sma_20?: number | null;
    sma_50?: number | null;
    notes: string[];
    source_ids: string[];
  };
  analyst_summary: string;
  risks: Array<{
    severity: string;
    title: string;
    detail: string;
    source_ids: string[];
  }>;
  sources: SourceRef[];
  critic_passed: boolean;
  critic_notes: string[];
}

export interface ResearchJob {
  job_id: string;
  status: JobStatus;
  query: string;
  progress?: string | null;
  brief?: ResearchBrief | null;
  error?: string | null;
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
