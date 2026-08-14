# Stock Research Multi-Agent System

Planner → Worker → Critic multi-agent pipeline that turns a ticker or company name into a **sourced research brief**: price action, fundamentals, news sentiment, filings highlights, and flagged risks — every claim linked to a source.

## Architecture (high level)

```
User (React + Vite) → FastAPI → Redis job queue/status
                      ↓
              LangGraph State Machine
   ┌──────────────────────────────────────────┐
   │  resolve_ticker → planner → router       │
   │       ↓              ↑                   │
   │  workers (parallel fan-out)              │
   │   • market_data (yfinance)               │
   │   • news_sentiment (Tavily + LLM)        │
   │   • filings (SEC EDGAR)                  │
   │   • code_calc (sandbox math)             │
   │       ↓                                  │
   │  synthesizer → critic                    │
   │       ↓ fail? retry specific worker      │
   │       ↓ pass? finalize brief             │
   └──────────────────────────────────────────┘
```

## Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Frontend | React 18 + Vite + TypeScript + Tailwind | SPA research UI, fast HMR |
| API | FastAPI + Pydantic v2 | Async, typed contracts, OpenAPI docs |
| Agents | LangGraph + LangChain | Explicit state machine, retries, checkpointing |
| Cache / jobs | Redis | Job status, brief TTL cache, optional checkpointer |
| Market data | `yfinance` (Alpha Vantage optional) | Free, no key |
| News | Tavily Search API | Agent-friendly search, free tier |
| Filings | SEC EDGAR REST API | Free, no key (User-Agent required) |
| Calc | Restricted Python exec tool | Real YoY / MAs — not LLM math |
| LLM (dev) | Ollama + **nemotron3:33b** | Local GPU/CPU via Ollama |
| LLM (demo) | OpenAI / Anthropic | Swap via `LLM_PROVIDER` |

## Monorepo layout

```
Stock_Project/
├── backend/                 # FastAPI + LangGraph agents
│   ├── app/
│   │   ├── main.py
│   │   ├── api/             # HTTP routes
│   │   ├── agents/          # LangGraph graph, planner, critic, workers
│   │   ├── tools/           # yfinance, EDGAR, Tavily, code exec
│   │   ├── services/        # Redis, LLM factory, ticker resolve
│   │   ├── models/          # Pydantic schemas
│   │   └── core/            # config, logging
│   ├── tests/
│   └── requirements.txt
├── frontend/                # React (Vite) research brief UI
├── eval/                    # Factual accuracy harness (resume metric)
├── docker-compose.yml
└── .env.example
```

## Tools you need to install (end-to-end)

### Required (local dev)

1. **Python 3.11+** — backend runtime  
2. **Node.js 20+ / npm** — frontend  
3. **Docker + Docker Compose** — Redis (and optional Ollama)  
4. **Redis** — via `docker compose up redis`  
5. **Ollama** — [https://ollama.com](https://ollama.com) with `nemotron3:33b` already pulled (`ollama list`)  
6. **Git**

### API keys (free tiers)

| Service | Required? | Get it |
|---------|-----------|--------|
| Tavily | Yes for live news | https://tavily.com |
| OpenAI / Anthropic | Optional (demo polish) | swap from Ollama |
| Alpha Vantage | Optional fallback | https://www.alphavantage.co |
| SEC EDGAR | No key — set `SEC_USER_AGENT` with your email | https://www.sec.gov/os/accessing-edgar-data |

### Python packages (see `backend/requirements.txt`)

- `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`
- `langgraph`, `langchain`, `langchain-openai`, `langchain-ollama`, `langchain-anthropic`
- `yfinance`, `httpx`, `beautifulsoup4`, `pandas`, `numpy`
- `redis`, `tavily-python`
- `pytest`, `pytest-asyncio`

### Frontend packages (see `frontend/package.json`)

- `react`, `react-dom`, `vite`, `typescript`, `tailwindcss`, `lucide-react`

## Quick start

```bash
# 1. Infra
cp .env.example .env
# UPDATE .env: set TAVILY_API_KEY and SEC_USER_AGENT

docker compose up redis -d
# ensure: ollama list shows nemotron3:33b

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 3. Frontend — React + Vite (new terminal)
cd frontend
npm install
npm run dev

# 4. Open http://localhost:3000 — research AAPL
```

## LangGraph flow (nodes & edges)

| Node | Role |
|------|------|
| `resolve_ticker` | Map company name → ticker |
| `planner` | Decompose into subtasks + retry plan from critic |
| `router` | Fan-out to pending workers |
| `market_worker` / `news_worker` / `filings_worker` / `calc_worker` | Specialized tools |
| `synthesizer` | Draft structured brief with source citations |
| `critic` | Consistency + citation + freshness checks |
| `finalize` | Persist brief, mark job done |

**Retry logic:** Critic returns `failed_subtasks[]`. Planner only re-queues those workers (max `MAX_CRITIC_RETRIES`). No full restart.

## Resume-ready eval

```bash
cd backend && pytest ../eval -q
# Target bullet: "Achieved X% factual accuracy across 20 evaluated tickers"
```

See `eval/tickers_testset.json` and `eval/run_eval.py`.

## API surface

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/research` | Start research job `{ query: "AAPL" }` |
| `GET` | `/api/v1/research/{job_id}` | Poll status + brief |
| `GET` | `/api/v1/health` | Health check |
| `GET` | `/docs` | OpenAPI (Swagger) |

## What to UPDATE next (stubbed areas)

Search the codebase for `# UPDATE:` comments. High-priority:

1. Wire real Tavily key + sentiment LLM prompts  
2. Harden SEC EDGAR HTML/XBRL parsing for risk factors  
3. Replace naive code sandbox with RestrictedPython / Docker sandbox  
4. Enable LangGraph Redis checkpointer for durable retries  
5. Stream token/events to the frontend via SSE  
6. Swap `LLM_PROVIDER=openai` for demo day  

## License

MIT — resume / portfolio project.
