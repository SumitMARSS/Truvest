# Tools & setup checklist (end-to-end)

## Install on your machine

| Tool | Purpose | Install |
|------|---------|---------|
| Python 3.10+ | Backend runtime | `sudo apt install python3 python3-venv` |
| Node.js 20+ | React (Vite) frontend | https://nodejs.org or `nvm install 20` |
| Docker Engine + Compose | Redis (optional — in-memory fallback works without it) | https://docs.docker.com/engine/install/ |
| Git | Version control | preinstalled on most Linux |

Ollama is optional: the default LLM provider is **OpenRouter** (hosted, free
tier), so nothing heavy runs locally. Set `LLM_PROVIDER=ollama` only if you
want fully local inference.

## Free API accounts

| Service | Env var | Notes |
|---------|---------|-------|
| OpenRouter | `OPENROUTER_API_KEY` | **Default LLM.** Free key at https://openrouter.ai/keys; any `:free` model works (`OPENROUTER_MODEL`, default `openai/gpt-oss-20b:free`) |
| Tavily | `TAVILY_API_KEY` | News supplement + India filings search — free tier |
| Alpha Vantage (optional) | `ALPHA_VANTAGE_API_KEY` | Market-data fallback when yfinance has no price |
| OpenAI (optional) | `OPENAI_API_KEY` | Set `LLM_PROVIDER=openai` |
| Anthropic (optional) | `ANTHROPIC_API_KEY` | Set `LLM_PROVIDER=anthropic` |

yfinance needs no key. SEC EDGAR is no longer used (India filings replaced it).

**Keyless data sources (no signup at all):**

| Source | Used for | Notes |
|--------|----------|-------|
| ET / Moneycontrol / Livemint / Business Standard RSS | Primary news feed | Business Standard 403s without a browser-shaped User-Agent — already handled in `tools/news_rss.py` |
| NSE shareholding-pattern endpoint (via `nsepython`) | Promoter % + QoQ delta | Unofficial/undocumented — see the caveat in README |
| NSE `allIndices` endpoint (via `nsepython`) | Sector-average P/E | Same caveat; falls back to a static table |

## Python libs (backend)

See `backend/requirements.txt`. Core: FastAPI, LangGraph, LangChain
(langchain-openai for OpenRouter), yfinance, httpx, redis, tavily-python, pandas.

## Node libs (frontend)

See `frontend/package.json`. Core: React 18, Vite, TypeScript, Tailwind, lucide-react.

## One-command infra

```bash
cp .env.example .env
# edit OPENROUTER_API_KEY (required) + TAVILY_API_KEY (recommended)

make infra          # redis via docker (optional)
make backend        # uvicorn on :8000
make frontend       # vite (React) on :3000
```

Health check: `curl localhost:8000/api/v1/health` shows Redis status and the
active LLM model.

## IDE / quality (recommended)

- VS Code / Cursor + Python + ESLint extensions
- `ruff` for Python lint (optional)
- `pytest` for agent unit tests (`make test`)
