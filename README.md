# Truvest — Stock Research Multi-Agent System

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
| **Advanced search** — ranked suggestions with a match score, before you submit | Bundled NSE listing catalog (~2.4k symbols) + curated brand/alias overlay, Yahoo Finance search, LLM only for descriptive questions | Each layer is independent: no network ⇒ local catalog still answers; no LLM key ⇒ everything except "describe it" queries still works |

**Two hard rules enforced in code, not prompts:** no LLM performs arithmetic, and no gap is ever filled with a plausible-looking guess — every unavailable section renders as unavailable and is listed in the brief's `data_gaps`.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full state diagram and critic contract.

## Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Frontend | React 18 + Vite + TypeScript + Tailwind | Truvest SPA: ranked stock search, performance toggle + price chart |
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
│   │   │                    #   stock_search (advanced search), intent
│   │   │                    #   (compare detection), job store
│   │   ├── models/          # Pydantic schemas
│   │   ├── data/            # peer_groups.json (curated NSE peer groups),
│   │   │                    #   nse_universe.json (generated search catalog),
│   │   │                    #   stock_aliases.json (curated brand/alias overlay)
│   │   └── core/            # config, logging, ticker, confidence,
│   │                        #   compliance_filter, dedup, text_quality
│   ├── scripts/             # build_stock_universe.py (rebuilds the catalog)
│   ├── tests/               # 133 tests, no network, ~2s
│   └── requirements.txt
├── frontend/                # Truvest UI (React + Vite) + 55 vitest tests
│   ├── src/components/      # ResearchStudio · StockSearchInput · ModelPicker ·
│   │                        #   PipelineStatus · BriefView · CompareView ·
│   │                        #   ValuationPanel · PeerTable · ShareholdingCard ·
│   │                        #   ConfidenceBadge · TrendIndicator · DataGapBanner ·
│   │                        #   Skeleton · BriefSkeleton · ErrorBoundary ·
│   │                        #   ThemeToggle · BrandMark
│   ├── src/lib/             # api.ts (typed client) · theme.ts
│   └── src/index.css        # theme tokens; tailwind.config.js maps them to
│                            #   paper / surface / elevated / line / ink / secondary /
│                            #   muted / accent / success / warn / danger / primary
├── eval/                    # Factual accuracy + graceful-degradation harness
├── docs/                    # ARCHITECTURE.md, TOOLS.md, AUDIT.md, INTERVIEW_QA.md
├── docker-compose.yml
└── .env.example
```

### Bundled data (no key, no network at runtime)

| File | Contents |
|---|---|
| `nse_universe.json` | 2,378 NSE symbols with industry + Nifty-50/100/500 tier, generated from NSE archives |
| `stock_aliases.json` | 161 hand-curated entries — short forms ("HUL", "RIL") and brand keywords ("maggi", "jaguar") |
| `peer_groups.json` | 57 tickers → peer group + sector label, plus 12 sector → NSE-index mappings shared with the sector-P/E lookup |

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

## Execution model

A brief takes tens of seconds to minutes, so nothing about it is synchronous.

| Layer | Mechanism | Why |
|---|---|---|
| HTTP | `BackgroundTasks` + immediate `job_id` | No proxy holds a multi-minute request open |
| Job wrapper | `asyncio.wait_for(asyncio.to_thread(...), 420s)` | `graph.stream()` is sync and blocking — running it inline would freeze the event loop |
| Progress | `asyncio.run_coroutine_threadsafe` | The callback fires on the worker thread; job-store writes belong to the loop |
| Graph | LangGraph superstep fan-out | 5 I/O workers in one superstep; wall-clock is the slowest, not the sum |
| Inside workers | `ThreadPoolExecutor` — 4 RSS feeds, ≤5 peer rows, 2 compare sides | Blocking HTTP inside sync graph nodes |
| Model choice | `ContextVar`, set **inside** the worker thread | A module global would let two concurrent jobs overwrite each other's model |
| Frontend | 2s poll with an `inFlight` guard + 10-min ceiling | No stacked requests, no runaway loop |

One caveat stated plainly: `asyncio.wait_for` cancels the *await*, not the
thread. A timed-out job is marked failed for the client while its worker thread
runs to completion and discards its result — Python threads can't be
force-killed, and process isolation is the real fix.

## Tests

```bash
make test                      # backend: 133 tests, ~2s, zero network
cd frontend && npm test        # frontend: 55 tests across 8 files (vitest + jsdom)
cd frontend && npm run lint    # tsc --noEmit
```

The architecture is what makes this fast: every load-bearing decision lives in a
pure function, so nothing worth testing needs a network call.

| Area | Tests | What it pins down |
|---|---|---|
| `test_stock_search.py` | 27 | Scoring calibration, trigram fuzzy, sector intent, alias/brand matching, layer merge |
| `test_model_catalog.py` | 20 | Zero-price filter, text-only-output filter, allowlist validation, fallback roster |
| `test_confidence.py` | 10 | The full High/Medium/Low rule table, idempotence, no-mutation |
| `test_calc.py` | 9 | P/E, YoY, SMAs — the "no LLM does math" claim |
| `test_intent.py` | 8 | Compare-intent regex + when the LLM fallback may fire |
| `test_compliance_filter.py` / `test_text_quality.py` | 7 each | SEBI rewrites + audit log; the captured degenerate-output string |
| `test_ticker_resolve.py` | 6 | Suffix cleaning, alias fast path, `.NS`/`.BO`, suggestions on failure |
| `test_valuation.py` / `test_peer_data.py` / `test_sector_pe.py` / `test_critic_planner.py` | 5 each | P/E band partial history; peer degradation; sector fallback; targeted retry |
| `test_dedup.py` / `test_shareholding.py` / `test_ticker_helpers.py` | 4 each | Outlet-level corroboration counting; QoQ delta; ticker helpers |
| `test_news_rss.py` / `test_compare.py` | 3 / 2 | Per-feed independence; metrics table + fallback narrative |
| `test_market_worker_degrades.py` / `test_news_worker_corroboration.py` | 1 each | The two hard contracts: a dead source degrades, `<2` sources can't be directional |

Frontend: `StockSearchInput` 19, `ModelPicker` 14, `ResearchStudio` model wiring
6, `ThemeToggle` 4, `TrendIndicator` 4, `PeerTable` 4, `ConfidenceBadge` 3,
`DataGapBanner` 3.

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
| `POST` | `/api/v1/research` | Start job `{ "query": "RELIANCE" }` or `{ "query": "TCS vs INFY" }`; optional `"model"` picks the LLM |
| `GET` | `/api/v1/research/{job_id}` | Poll status + `brief` (single) or `compare_brief` (compare) |
| `GET` | `/api/v1/search?q=&limit=` | Ranked stock suggestions with confidence — typeahead, never 404s on a miss |
| `GET` | `/api/v1/models` | Selectable LLMs, default first (`?refresh=true` bypasses the cache) |
| `GET` | `/api/v1/health` | Health + `llm_provider` / `llm_model` (the server default) |
| `GET` | `/docs` | OpenAPI (Swagger) |

Jobs carry `mode` (`single`\|`compare`), the `model` that ran them, and, on
failure, a machine-readable `error_code` (`ticker_not_found` \| `timeout` \|
`internal_error`) so the UI can show a tailored message instead of one generic
failure state. A `ticker_not_found` job also carries `suggestions` — the same
ranked candidates the search endpoint returns — so a dead end is one click from
a rerun.

### Choosing the model

The brief is written by whichever LLM the user picks in the header of the search
card; `OPENROUTER_MODEL` is only the default. `GET /api/v1/models` fetches
OpenRouter's live roster and keeps the **zero-priced** entries, so the list stays
current as free models come and go instead of being pinned at deploy time.

Two filters matter. Free-but-unusable models are dropped: zero-priced music
models declare `text` among their outputs (`text+image->text+audio`), and
guardrail/embedding endpoints are chat-shaped but can't write a summary — a
naive price filter offers both. And because the OpenRouter key is the
*server's*, `POST /research` refuses any model outside the free allowlist with a
`400` rather than letting a request body spend it; OpenRouter's `:free` suffix
guarantees zero cost, so an id newer than our cache is still accepted.

On Ollama the picker lists locally installed models instead. On the paid
providers (`openai`, `anthropic`) the catalog reports `selectable: false` and the
UI renders a plain label — picking a model isn't the caller's decision there.

### Search: how a query becomes candidates

```
"maggi" / "hul" / "relaince" / "IT companies" / "who makes jaguar cars"
        ↓
1. local NSE catalog      symbol · company name · curated alias · brand keyword
   (offline, ~5ms)        · initials · sector · char-trigram fuzzy for typos
        ↓ still unsure (top score < 0.90)?
2. Yahoo Finance search   BSE-only + newly listed names; agreement with layer 1
                          raises confidence (corroboration, as with news)
        ↓ still unsure (top score < 0.55) and the query reads like a question?
3. LLM interpretation     proposes company NAMES only — each is resolved back
                          through layer 1, so it can never invent a ticker
```

Every candidate comes back with `score` (0-1), `confidence`
(`high`\|`medium`\|`low`), `match_reason` ("Known for 'Maggi'", "Closest match
to your spelling") and the `sources` that found it. Results are cached, so the
network/LLM layers stay off the hot path for repeat queries.

Rebuild the catalog after NSE listings change:

```bash
python backend/scripts/build_stock_universe.py   # rewrites app/data/nse_universe.json
```

Curated aliases and brand keywords live in `app/data/stock_aliases.json` and are
never touched by that script.

### Look and feel

Truvest ships a **dark theme by default** with a fully designed light theme
behind a header toggle. Both are driven by one set of CSS variables in
[`frontend/src/index.css`](frontend/src/index.css), surfaced to components as
Tailwind tokens in `tailwind.config.js`:

| Token | Role |
|---|---|
| `paper` / `surface` / `elevated` | page · cards · inner fills, hover, list rows |
| `line` | hairline borders |
| `ink` / `secondary` / `muted` | primary text · supporting copy · labels and captions |
| `accent` · `success` · `warn` · `danger` | brand teal · positive · caution · negative |
| `primary` / `onprimary` | primary action surface and its label |

No component hardcodes a colour, so the whole product re-skins from that block.
The dark palette is `:root`, and light is the opt-in override — a late or
blocked stylesheet lands on dark rather than flashing white. An inline script in
`index.html` applies the stored theme **before first paint**, and the choice
persists in `localStorage`.

Two safeguards exist because a browser holding an **outdated stylesheet** was
the single worst failure we hit (a dark page wearing light components, with
unreadable text): the pre-paint background is a plain `<style>` rule rather
than a scripted inline style, so any stylesheet that loads simply overrides it;
and every token carries its dark value as a CSS fallback. A stale bundle now
degrades to an out-of-date *look*, never an unreadable page — and the console
says so. **Tailwind config changes need a dev-server restart, not just a
reload.**

Contrast is verified, not assumed: every rendered text node in both themes
clears WCAG AA for its size (the muted tier is its own token precisely because
an opacity-mixed grey measured 3.8–4.5:1 on light).

### Search in the UI

The search box (`frontend/src/components/StockSearchInput.tsx`) is a debounced
combobox: matches appear as you type, each with its confidence, score and the
reason it matched, and arrow keys / Enter / Escape work as expected.

The results panel is a **normal block in the document flow**, not a floating
overlay: it renders between the input row and the example chips, so opening it
grows the card and pushes the content below it down. It cannot overlap the
chips or the disclaimer, cannot escape the card, and needs no `z-index`. A long
list scrolls inside its own panel.

Two more rules keep it out of the way:

- **It never opens by itself.** A prefilled value, a value written by a
  suggestion click, or a remount when you switch tabs is not a question, so it
  isn't answered with a dropdown. Only typing — or clicking a **Try a search**
  example — starts a lookup.
- **It closes while a job is running**, so the list can never hang over the
  pipeline view.

The **Try a search** chips are examples, not shortcuts: clicking one fills the
box and shows the ranked matches; picking a match is what starts the research
job. A job takes minutes, so it is always an explicit choice.

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

## Docs

| Doc | What's in it |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Full state diagram, reducer semantics, critic retry contract, worker→tool map, cache table, file map |
| [`docs/TOOLS.md`](docs/TOOLS.md) | Setup checklist: what to install, which keys, which sources are keyless |
| [`docs/AUDIT.md`](docs/AUDIT.md) | Severity-tagged code audit — every finding, what was fixed, and which technique caught it |
| [`docs/INTERVIEW_QA.md`](docs/INTERVIEW_QA.md) | ~200 Q&A across all 24 areas of the system, frontend and backend, grounded in the actual code |

## License

MIT — resume / portfolio project.
