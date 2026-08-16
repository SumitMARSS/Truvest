# SourceBrief — Stock Research Multi-Agent System

Planner → Workers → Critic multi-agent pipeline that turns an **NSE/BSE ticker or Indian company name** into a **sourced research brief**: multi-horizon price performance, fundamentals, valuation context (historical P/E band + sector average), promoter shareholding with QoQ delta, sector peer comparison, corroborated news sentiment, filings highlights, and flagged risks — every claim linked to a source **and tagged with a confidence level**.

## Architecture (high level)

```
User (React + Vite :3000) → FastAPI (:8000) → job store (Redis or in-memory)
                      ↓ compare-intent detection ("X vs Y")
                      ↓ background task
              LangGraph State Machine
   ┌────────────────────────────────────────────────────────┐
   │  resolve_ticker → planner                              │
   │       ↓ fan-out (5 workers in parallel)                │
   │  • market_data   (yfinance — 3y history + quarterly EPS)│
   │  • news_sentiment(RSS primary + Tavily + LLM)          │
   │  • filings       (India results via Tavily + calendar) │
   │  • peers         (curated NSE peer groups)             │
   │  • shareholding  (NSE disclosure via nsepython)        │
   │       ↓ join → calc (P/E band, sector P/E, SMA, YoY)   │
   │  synthesizer → critic                                  │
   │       ↓ confidence scoring + SEBI-safe rewrite         │
   │       ↓ fail? retry only failed workers                │
   │       ↓ pass? finalize brief                           │
   └────────────────────────────────────────────────────────┘
```

## What's new in this pass

| Capability | Data source | When the source fails |
|---|---|---|
| **Valuation context** — rolling TTM P/E band + sector average | yfinance quarterly EPS × price history; NSE sectoral-index P/E | Band → `partial history` label under 8 quarters, or an explicit reason; sector P/E → static fallback table, then honest "unavailable" |
| **Shareholding** — promoter % + QoQ delta | NSE shareholding-pattern endpoint via `nsepython` | "Shareholding data unavailable this cycle" — never blocks the brief |
| **Peer comparison** — sortable side-by-side table | Curated `backend/app/data/peer_groups.json` (from NSE sectoral index constituents) | "Peer comparison not available for this ticker yet"; a single failed peer is omitted, not faked |
| **Confidence scoring** — High/Medium/Low per claim | None (pure logic) | Cannot fail |
| **Upgraded news** — RSS-first + multi-source corroboration | ET / Moneycontrol / Livemint / Business Standard RSS; Tavily as supplement | Each feed degrades independently; **<2 independent sources ⇒ sentiment is forced to `insufficient_data`**, never bullish/bearish |
| **SEBI-safe language pass** — deterministic rewrite + audit log | None (pure logic) | Cannot fail |
| **Compare mode** — "RELIANCE vs TCS" | Reuses the whole pipeline, twice, concurrently | Either side failing surfaces as a normal job error |

**Two hard rules enforced in code, not prompts:** no LLM performs arithmetic, and no gap is ever filled with a plausible-looking guess — every unavailable section renders as unavailable and is listed in the brief's `data_gaps`.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full state diagram and critic contract.

## Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Frontend | React 18 + Vite + TypeScript + Tailwind | SPA research UI, performance toggle + price chart |
| API | FastAPI + Pydantic v2 | Async, typed contracts, OpenAPI docs |
| Agents | LangGraph + LangChain | Explicit state machine, targeted retries |
| Jobs | Redis (optional) / in-memory fallback | Job status + brief TTL |
| Market data | `yfinance` (Alpha Vantage optional) | Free NSE/BSE quotes + fundamentals |
| News | **RSS (ET/Moneycontrol/Livemint/BS)** + Tavily | Structured, free, higher signal than web-search snippets |
| Filings | India results via Tavily + yfinance calendar | NSE/BSE — not SEC EDGAR |
| Shareholding / sector P/E | `nsepython` (unofficial NSE endpoints) | Only free route to SEBI-disclosed promoter holdings — see caveat below |
| Calc | Pure Python (`code_exec.py`) | Real YoY / SMAs / price÷EPS / P/E bands — not LLM math |
| LLM (default) | **OpenRouter** free models | Hosted; no local GPU hang |
| LLM (optional) | Ollama / OpenAI / Anthropic | Swap via `LLM_PROVIDER` |

## Monorepo layout

```
Stock_Project/
├── backend/                 # FastAPI + LangGraph agents
│   ├── app/
│   │   ├── main.py
│   │   ├── api/             # HTTP routes
│   │   ├── agents/          # graph, planner, critic, workers, compare, runner
│   │   ├── tools/           # market_data, news_rss, news_search, india_filings,
│   │   │                    #   peer_data, shareholding, sector_pe, code_exec
│   │   ├── services/        # Redis, cache, LLM factory, ticker resolve,
│   │   │                    #   intent (compare detection), job store
│   │   ├── models/          # Pydantic schemas
│   │   ├── data/            # peer_groups.json (curated NSE peer groups)
│   │   └── core/            # config, logging, ticker, confidence,
│   │                        #   compliance_filter, dedup, text_quality
│   ├── tests/               # 86 tests
│   └── requirements.txt
├── frontend/                # React (Vite) research brief UI + 14 vitest tests
├── eval/                    # Factual accuracy + graceful-degradation harness
├── docs/                    # ARCHITECTURE.md, TOOLS.md, AUDIT.md
├── docker-compose.yml
└── .env.example
```

## Tools you need to install

### Required (local dev)

1. **Python 3.10+** — backend runtime  
2. **Node.js 20+ / npm** — frontend  
3. **Git**  
4. **Docker + Compose** (optional) — Redis only; app falls back to in-memory jobs without it  

Ollama is **not** required unless you set `LLM_PROVIDER=ollama`.

### API keys

| Service | Required? | Get it |
|---------|-----------|--------|
| OpenRouter | **Yes** (default LLM) | https://openrouter.ai/keys — use any `:free` model |
| Tavily | Recommended for live news/filings | https://tavily.com |
| Alpha Vantage | Optional market fallback | https://www.alphavantage.co |
| OpenAI / Anthropic | Optional | set `LLM_PROVIDER=openai` or `anthropic` |

### Python packages (see `backend/requirements.txt`)

- `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`
- `langgraph`, `langchain`, `langchain-openai`, `langchain-ollama`, `langchain-anthropic`
- `yfinance`, `httpx`, `pandas`, `numpy`
- `feedparser` (India financial-press RSS), `nsepython` (NSE shareholding + sector P/E)
- `redis`, `tavily-python`
- `pytest`, `pytest-asyncio`

**No new API keys are required by any of the seven new features.** RSS feeds and
the NSE endpoints are keyless; everything added in this pass runs on the free tier.

### ⚠️ Data-source caveat: unofficial NSE endpoints

Shareholding pattern (2.2) and sector-average P/E (2.1) are read from NSE's own
internal JSON endpoints via [`nsepython`](https://pypi.org/project/nsepython/),
which replays a browser-shaped session (headers + cookie handshake) — a plain
`requests.get` to `nseindia.com` is refused. These are **undocumented and
unsupported**: they can change shape or start blocking without notice, and
scraping them is a grey area under NSE's terms of use. That's acceptable for a
portfolio/demo project, not for production.

Both are therefore isolated behind clean interfaces — `tools/shareholding.py`
and `tools/sector_pe.py` are the **only** modules that import `nsepython` or
know the endpoint shape. Swapping in a licensed vendor means rewriting those two
files; nothing in the graph, workers, synthesizer, or UI needs to change.
Every call is wrapped, and failure degrades to a visible "unavailable" state.

### Frontend packages (see `frontend/package.json`)

- `react`, `react-dom`, `vite`, `typescript`, `tailwindcss`, `lucide-react`

## Quick start

```bash
# 1. Config
cp .env.example .env
# Set OPENROUTER_API_KEY (required) and TAVILY_API_KEY (recommended)

# Optional Redis
docker compose up redis -d

# 2. Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev

# 4. Open http://localhost:3000 — try RELIANCE, TCS, INFY
```

Or use Make: `make infra` → `make backend` → `make frontend`.  
Health: `curl localhost:8000/api/v1/health` (shows Redis status + active LLM model).

More setup detail: [`docs/TOOLS.md`](docs/TOOLS.md).

## LangGraph flow (nodes & edges)

| Node | Role |
|------|------|
| `resolve_ticker` | Map Indian company name / symbol → Yahoo ticker (`*.NS` / `*.BO`) |
| `planner` | Queue workers + targeted retry plan from critic |
| `market` / `news` / `filings` / `peers` / `shareholding` | Run **in parallel** (I/O workers) |
| `calc` | After join — SMA, YoY revenue, P/E from price÷EPS, **P/E band + sector P/E** |
| `synthesizer` | Draft brief + price history + data gaps + LLM analyst summary |
| `critic` | **Confidence scoring + SEBI-safe rewrite**, then consistency/citation/freshness gates |
| `finalize` | Persist brief, mark job done |

Peer comparison and shareholding are ordinary I/O workers using the **existing**
fan-out/join/retry pattern — no second orchestration style was introduced.

**Retry logic:** Critic returns `failed_subtask` per issue. Planner only re-queues those workers (max `MAX_CRITIC_RETRIES`). After exhaustion, brief is force-accepted with warnings.

**LLM calls (2 per job):** (1) batched news sentiment + near/far impact, (2) analyst summary. Failures fall back to heuristics / data-driven text — never raw API errors in the UI.

## Tests

```bash
make test                      # backend: 86 tests
cd frontend && npm test        # frontend: 14 tests (vitest)
cd frontend && npm run lint    # tsc --noEmit
```

Confidence scoring and the compliance filter are pure logic with no external
dependency, so both are fully unit-tested (`test_confidence.py`,
`test_compliance_filter.py`), as are the P/E band math, article clustering,
corroboration downgrade rule, peer degradation, and ticker resolution.

## Resume-ready eval

```bash
make eval
# or: cd backend && . .venv/bin/activate && python ../eval/run_eval.py
```

Extended in this pass beyond factual accuracy to also assert the
**graceful-degradation contract** — each new section must either carry real
data or say `available:false` *with a reason*; an honest "unavailable" is a
pass, so the metric can never be gamed by hiding gaps. Also checks: sector P/E
always carries an as-of date, every claim carries a confidence tag, no
directional sentiment survives with <2 sources, no banned advice language
reaches the summary, and the peer table always contains its subject row.

Reported separately from accuracy is `data_source_coverage_pct` — how often
each new source actually resolved live, so a quietly-degrading source shows up
as falling coverage rather than silently passing.

See `eval/tickers_testset.json` and `eval/run_eval.py`.

## API surface

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/research` | Start job `{ "query": "RELIANCE" }` or `{ "query": "TCS vs INFY" }` |
| `GET` | `/api/v1/research/{job_id}` | Poll status + `brief` (single) or `compare_brief` (compare) |
| `GET` | `/api/v1/health` | Health + `llm_provider` / `llm_model` |
| `GET` | `/docs` | OpenAPI (Swagger) |

Jobs carry `mode` (`single`\|`compare`) and, on failure, a machine-readable
`error_code` (`ticker_not_found` \| `timeout` \| `internal_error`) so the UI can
show a tailored message instead of one generic failure state.

## Code review findings

`docs/AUDIT.md` documents the full audit: severity-tagged findings across error
handling, hardcoded values, state-machine correctness, type safety, caching,
frontend, and tests — plus which technique caught each class of bug. All
High-severity items are fixed. Highlights:

- A yfinance outage crashed the **entire** job, discarding news/filings work
  that had already succeeded.
- `sources` accumulated duplicates across critic retries, so a retried worker's
  citations sat alongside the stale first attempt's under the same ids.
- The critic never checked filings for citations — `filings` was unreachable as
  a retry target.
- `*.NS`/`*.BO` tickers failed to resolve at all (dead code in the resolver),
  which meant **the eval harness had never been runnable**.
- Degenerate LLM output (`"? = is... is, isALG(?..………iqué…"`, captured live from
  the free model) was written into the brief verbatim, because every fallback
  guarded on "is the text empty?" rather than "is this actually prose?".
- Compare mode scrolled the whole page sideways on mobile (CSS-grid
  `min-width:auto`).

## What to build next

1. Full graph integration test with mocked tools — nothing yet proves the
   *wiring* (that a critic failure re-runs only the targeted worker)
2. LangGraph Redis checkpointer for durable job resume
3. SSE progress events (replace frontend polling)
4. NSE corporate-announcements API for filings (vs Tavily snippets)
5. FII/DII shareholding v2 (monthly NSDL depository data)

Search the codebase for `# UPDATE:` comments for smaller stubs.

## License

MIT — resume / portfolio project.
