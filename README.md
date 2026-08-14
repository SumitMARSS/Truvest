# SourceBrief — Stock Research Multi-Agent System

Planner → Workers → Critic multi-agent pipeline that turns an **NSE/BSE ticker or Indian company name** into a **sourced research brief**: multi-horizon price performance, fundamentals, news sentiment with impact, India filings/results highlights, and flagged risks — every claim linked to a source.

## Architecture (high level)

```
User (React + Vite :3000) → FastAPI (:8000) → job store (Redis or in-memory)
                      ↓ background task
              LangGraph State Machine
   ┌──────────────────────────────────────────────────┐
   │  resolve_ticker → planner                        │
   │       ↓ fan-out (parallel)                       │
   │  • market_data  (yfinance — 3y history)          │
   │  • news_sentiment (Tavily + OpenRouter LLM)      │
   │  • filings (India results via Tavily + calendar) │
   │       ↓ join → calc (SMA / YoY / P/E — no LLM)   │
   │  synthesizer → critic                            │
   │       ↓ fail? retry only failed workers          │
   │       ↓ pass? finalize brief                     │
   └──────────────────────────────────────────────────┘
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full state diagram and critic contract.

## Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Frontend | React 18 + Vite + TypeScript + Tailwind | SPA research UI, performance toggle + price chart |
| API | FastAPI + Pydantic v2 | Async, typed contracts, OpenAPI docs |
| Agents | LangGraph + LangChain | Explicit state machine, targeted retries |
| Jobs | Redis (optional) / in-memory fallback | Job status + brief TTL |
| Market data | `yfinance` (Alpha Vantage optional) | Free NSE/BSE quotes + fundamentals |
| News | Tavily Search API | Indian financial press, free tier |
| Filings | India results via Tavily + yfinance calendar | NSE/BSE — not SEC EDGAR |
| Calc | Pure Python (`code_exec.py`) | Real YoY / SMAs / price÷EPS — not LLM math |
| LLM (default) | **OpenRouter** free models | Hosted; no local GPU hang |
| LLM (optional) | Ollama / OpenAI / Anthropic | Swap via `LLM_PROVIDER` |

## Monorepo layout

```
Stock_Project/
├── backend/                 # FastAPI + LangGraph agents
│   ├── app/
│   │   ├── main.py
│   │   ├── api/             # HTTP routes
│   │   ├── agents/          # LangGraph graph, planner, critic, workers
│   │   ├── tools/           # yfinance, Tavily news, India filings, calc
│   │   ├── services/        # Redis, LLM factory, ticker resolve, job store
│   │   ├── models/          # Pydantic schemas
│   │   └── core/            # config, logging
│   ├── tests/
│   └── requirements.txt
├── frontend/                # React (Vite) research brief UI
├── eval/                    # Factual accuracy harness
├── docs/                    # ARCHITECTURE.md, TOOLS.md
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
- `redis`, `tavily-python`
- `pytest`, `pytest-asyncio`

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
| `market` / `news` / `filings` | Run **in parallel** (I/O workers) |
| `calc` | After join — SMA, YoY revenue, P/E from price÷EPS |
| `synthesizer` | Draft brief + price history + LLM analyst summary |
| `critic` | Consistency + citation + freshness checks |
| `finalize` | Persist brief, mark job done |

**Retry logic:** Critic returns `failed_subtask` per issue. Planner only re-queues those workers (max `MAX_CRITIC_RETRIES`). After exhaustion, brief is force-accepted with warnings.

**LLM calls (2 per job):** (1) batched news sentiment + near/far impact, (2) analyst summary. Failures fall back to heuristics / data-driven text — never raw API errors in the UI.

## Resume-ready eval

```bash
make eval
# or: cd backend && . .venv/bin/activate && python ../eval/run_eval.py
```

See `eval/tickers_testset.json` and `eval/run_eval.py`.

## API surface

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/research` | Start job `{ "query": "RELIANCE" }` |
| `GET` | `/api/v1/research/{job_id}` | Poll status + brief |
| `GET` | `/api/v1/health` | Health + `llm_provider` / `llm_model` |
| `GET` | `/docs` | OpenAPI (Swagger) |

## What to build next

1. LangGraph Redis checkpointer for durable job resume  
2. SSE progress events (replace frontend polling)  
3. NSE corporate-announcements API for filings (vs Tavily snippets)  
4. Run `eval/run_eval.py` and track factual accuracy %  

Search the codebase for `# UPDATE:` comments for smaller stubs.

## License

MIT — resume / portfolio project.
