# Truvest — Interview Question Bank

Every question an interviewer can realistically ask about this project, with the
answer grounded in the actual code. Organised so you can revise a single area
(LangGraph, FastAPI, React, search, safety) or read end-to-end.

**Repo facts to have memorised:**

| Fact | Value |
|---|---|
| Backend tests | **136** (`pytest -q`, ~4s, zero network) |
| Frontend tests | **55** across 8 files (`vitest run`, jsdom) |
| Graph nodes | 12 (`resolve_ticker`, `planner`, 5 I/O workers, `join_workers`, `calc`, `synthesizer`, `critic`, `finalize`) |
| Parallel I/O workers | 5 (market, news, filings, peers, shareholding) |
| LLM calls per single-ticker job | **2** (batched news sentiment, analyst summary) |
| Search catalog | 2,378 NSE symbols + 161 curated alias/brand entries |
| Peer groups | 57 tickers mapped, 12 NSE sector→index mappings |
| Critic retry cap | `MAX_CRITIC_RETRIES=2` → critic runs at most 3 times |
| Job timeout | 420s hard cap |
| Frontend poll | 2s interval, 10-minute client-side ceiling |
| Search debounce | 220ms |
| Error codes | 4 (`ticker_not_found`, `data_provider_unavailable`, `timeout`, `internal_error`) |

---

## Table of contents

1. [Project overview & framing](#1-project-overview--framing)
2. [System design & architecture](#2-system-design--architecture)
3. [LangGraph & agent orchestration](#3-langgraph--agent-orchestration)
4. [Planner, workers, calc](#4-planner-workers-calc)
5. [Synthesizer & critic](#5-synthesizer--critic)
6. [Compare mode](#6-compare-mode)
7. [Concurrency, threading & async](#7-concurrency-threading--async)
8. [FastAPI & the API layer](#8-fastapi--the-api-layer)
9. [Data sources & the tools layer](#9-data-sources--the-tools-layer)
10. [Advanced search subsystem](#10-advanced-search-subsystem)
11. [LLM integration & model selection](#11-llm-integration--model-selection)
12. [Trust, safety & compliance](#12-trust-safety--compliance)
13. [Caching & performance](#13-caching--performance)
14. [Data modelling & type safety](#14-data-modelling--type-safety)
15. [Testing & evaluation](#15-testing--evaluation)
16. [Frontend architecture](#16-frontend-architecture)
17. [Frontend components, one by one](#17-frontend-components-one-by-one)
18. [Theming, design system & accessibility](#18-theming-design-system--accessibility)
19. [DevOps, config & deployment](#19-devops-config--deployment)
20. [Bugs found & debugging war stories](#20-bugs-found--debugging-war-stories)
21. [Trade-offs, scale & "what would you change"](#21-trade-offs-scale--what-would-you-change)
22. [Rapid-fire one-liners](#22-rapid-fire-one-liners)
23. [Live-coding / whiteboard prompts](#23-live-coding--whiteboard-prompts)
24. [Behavioural questions with this project as evidence](#24-behavioural-questions-with-this-project-as-evidence)

---

## 1. Project overview & framing

**Q1.1 — Give me the 60-second pitch.**
Truvest turns an NSE/BSE ticker or an Indian company name into a sourced equity
research brief. A LangGraph state machine runs a planner, five parallel I/O
workers (market data, news, filings, peers, shareholding), a deterministic calc
node, a synthesizer and a critic. The output is a structured brief — multi-horizon
price performance, fundamentals, a historical P/E band vs the sector average,
promoter shareholding with its quarter-on-quarter delta, a peer comparison table,
corroborated news sentiment, filing highlights and flagged risks — where every
claim carries citation IDs and a High/Medium/Low confidence tag. Two rules are
enforced in code rather than in prompts: **no LLM performs arithmetic**, and
**no data gap is ever filled with a plausible guess** — an unavailable section
renders as unavailable and is listed in the brief's `data_gaps`.

**Q1.2 — Why this project? What problem does it actually solve?**
Retail equity research in India is either a paywalled PDF or an unsourced blog
post. The interesting engineering problem isn't "call an LLM about a stock" —
it's making a multi-source, partly-unreliable data pipeline produce output a
user can *trust*: knowing which number came from the exchange and which came
from one unconfirmed headline, and never being lied to when a source is down.

**Q1.3 — Why "agents"? Couldn't one LLM call do this?**
No, and deliberately so. Three reasons:
1. **Parallelism** — five independent I/O calls with different latencies and
   failure modes. Wall-clock is the slowest worker, not the sum.
2. **Targeted retry** — when the critic finds a P/E inconsistency it re-runs
   *only* the market worker, not the whole job.
3. **Separation of judgement from computation** — the LLM classifies sentiment
   and writes prose. Every number is computed in Python. A single prompt would
   blur that line and the model would start doing arithmetic.

**Q1.4 — What's the hardest part of the project?**
Graceful degradation without dishonesty. It's easy to make a demo that works
when every source responds. Making six independent sources fail *independently*,
having the brief still render, and having the UI say exactly what's missing and
why — that's the part that touches every layer from the tool module to the
`data_gaps` banner.

**Q1.5 — Who is the user and what's the actual output?**
A retail investor or analyst researching an Indian listed company. Output is a
JSON `ResearchBrief` rendered as an interactive page: analyst summary, valuation
panel, performance chart with horizon toggle, fundamentals, peer table,
shareholding card, sentiment-tagged news, filings, risks, and a numbered source
list every claim links back to.

---

## 2. System design & architecture

**Q2.1 — Walk me through a request end to end.**
1. User types in the search box → debounced `GET /api/v1/search?q=` → ranked
   candidates with a score, confidence and a human-readable match reason.
2. User picks one → `POST /api/v1/research {query, model?}`.
3. The route validates the model id against a free-model allowlist, runs
   regex compare-intent detection ("TCS vs INFY"), creates a job record
   (Redis or in-memory) with `status=pending, mode=single|compare`, and returns
   the `job_id` immediately — HTTP is never held open for a multi-minute job.
4. A FastAPI `BackgroundTask` runs the pipeline under `asyncio.wait_for(...,
   420s)` wrapping `asyncio.to_thread(run_research_pipeline, ...)`.
5. `graph.stream(initial, stream_mode="updates")` walks the state machine;
   each node's `status_message` is pushed back to the job record via a progress
   callback that hops threads with `asyncio.run_coroutine_threadsafe`.
6. The final state is validated through `ResearchBrief.model_validate` and
   stored on the job.
7. The browser polls `GET /api/v1/research/{job_id}` every 2s and renders the
   pipeline step tracker, then the brief.

**Q2.2 — Why a job/polling model instead of a synchronous response?**
A single brief takes tens of seconds to minutes: five network round-trips, two
LLM calls, and up to two critic retries. A synchronous request would hit every
proxy and load-balancer idle timeout in existence, and the client would have no
progress signal. The job model gives a `job_id` in milliseconds and streams
progress through polls.

**Q2.3 — Why polling and not WebSockets/SSE?**
Polling at 2s is honest engineering for this scale: no connection state, works
through any proxy, trivially resumable if the tab is reloaded, and the pipeline
emits perhaps 12 progress events over the whole run — the event rate doesn't
justify a persistent connection. SSE is the documented next step
(`GET /research/{job_id}/events`), and the frontend has the seam for it
(`subscribeResearchEvents` is stubbed in `lib/api.ts`).

**Q2.4 — Draw the architecture.**
```
React + Vite (:3000)
  ├─ GET  /api/v1/search      typeahead: catalog → Yahoo → LLM  (cached 6h)
  ├─ GET  /api/v1/models      free-model roster                  (cached 1h)
  ├─ POST /api/v1/research    → job_id
  └─ GET  /api/v1/research/{id}  poll every 2s
                    │
FastAPI (:8000) ── job store: Redis if up, in-memory dict otherwise
                    │ BackgroundTask + asyncio.to_thread + 420s cap
                    ▼
        LangGraph StateGraph
   resolve_ticker → planner
        ↓ conditional fan-out (parallel)
   market · news · filings · peers · shareholding
        ↓ join_workers (barrier)
   calc (needs market_data)
        ↓
   synthesizer → critic ─pass→ finalize
                    └─fail→ planner (targeted retry, max 2)
```

**Q2.5 — Why is the layering the way it is?**
- `api/routes/` — HTTP only. No business logic.
- `agents/` — orchestration only. Nodes read state, call tools, write state.
- `tools/` — pure I/O and pure math. No graph awareness, so each is unit-testable
  and swappable.
- `services/` — cross-cutting infrastructure: Redis, cache, LLM factory, job
  store, ticker resolution, search, intent.
- `core/` — dependency-free pure logic: config, ticker helpers, confidence
  scoring, compliance filter, dedup, text quality.
- `models/` — Pydantic contracts.

The test suite is the proof this layering is real: 136 tests run in under four
seconds with **zero network access**, because everything worth testing is pure.

**Q2.6 — What's the single most important design decision?**
`available: false` + `reason` as a first-class shape on every optional section
(`PeBand`, `SectorPe`, `PeerComparison`, `Shareholding`). It means "unavailable"
is a value the type system knows about, not a `None` that renders as a blank
gap. Everything downstream — the `data_gaps` list, the `UnavailableNotice`
component, the eval harness's `degraded_ok()` check — is built on that shape.

---

## 3. LangGraph & agent orchestration

**Q3.1 — What is LangGraph and why did you use it over LangChain agents or plain code?**
LangGraph models an agent workflow as an explicit directed graph of nodes over a
shared typed state, with conditional edges controlling routing. I needed exactly
three things a ReAct-style agent doesn't give you: deterministic topology
(I know before running that market/news/filings run in parallel), a shared state
object with **reducers** for concurrent writes, and cycles (critic → planner)
with a bounded retry count. A plain `asyncio.gather` would have covered the
parallelism but not the retry-only-what-failed loop or the progress streaming,
and a tool-calling agent would have made the control flow non-deterministic —
unacceptable when the output has to be reproducible enough to evaluate.

**Q3.2 — Explain `AgentState`.**
A `TypedDict(total=False)` with three kinds of field:
- **Plain fields** (`query`, `ticker`, `market_data`, `draft_brief`) — last write
  wins.
- **Reducer fields** — `Annotated[list, operator.add]` on `sources` and
  `completed_workers`, so five parallel nodes can each append without clobbering
  one another.
- **A custom reducer** — `status_message: Annotated[str, _last_value]`, because
  parallel nodes write progress text in the same superstep and the default
  behaviour would be a conflict error.

**Q3.3 — What is a reducer and why did you need a custom one?**
A reducer is the merge function LangGraph applies when more than one node writes
the same state key in one superstep. Without one, concurrent writes to the same
key raise `InvalidUpdateError`. `operator.add` on a list means "concatenate".
For `status_message` concatenating would produce
`"market_donenews_donefilings_done"`, so `_last_value(old, new) -> new` keeps
just the most recent message — the UI only ever shows one line anyway.

**Q3.4 — How does the parallel fan-out actually work?**
`add_conditional_edges("planner", _fan_out_workers, {...})`. The routing
function returns a **list** of node names, and returning a list is how LangGraph
dispatches to multiple nodes in the same superstep:
```python
def _fan_out_workers(state):
    pending = set(state.get("pending_workers") or [])
    targets = [w for w in _IO_WORKERS if w in pending]
    return targets or ["join_workers"]
```
Every worker then has a static edge to `join_workers`, which is the barrier.

**Q3.5 — What's the `or ["join_workers"]` fallback for?**
A calc-only retry. If the critic fails on a calculation issue, the planner
queues `["calc"]` only — no I/O worker is pending, so the routing function would
return an empty list and the graph would have nowhere to go. Routing straight to
the join keeps the graph well-formed.

**Q3.6 — Why does `calc` sit after the join rather than in the fan-out?**
It's the only node with a data dependency: it reads `market_data` produced by
`market_worker`. Putting it in the fan-out would race. `_after_join` is a
conditional edge that routes to `calc` only if `"calc"` is still in
`pending_workers`, otherwise straight to the synthesizer.

**Q3.7 — Why is `join_workers` a no-op node?**
It exists purely as a synchronisation point — every parallel worker has an edge
into it, so LangGraph won't advance past it until all of them complete. It
returns only `{"status_message": "workers_joined"}`, which doubles as a UI
progress signal.

**Q3.8 — Walk me through the retry loop and prove it terminates.**
Critic → `_after_critic` → `planner` on failure. The planner sees non-empty
`critic_issues`, extracts each issue's `failed_subtask`, dedupes them, appends
`calc` if `market` is being retried (dependency), and returns *only* those in
`pending_workers` — plus it clears `critic_issues` so the next pass starts fresh.
Termination: the critic reads `retry_count` **before** incrementing it, and sets
`force_accept = (not passed) and retry_count >= MAX_CRITIC_RETRIES`. With the
default of 2 the critic runs at most 3 times, then force-accepts with
`critic_passed=false` and warning notes. There is no unbounded path.

**Q3.9 — Why does the planner append `calc` when `market` is retried?**
Every calculation — P/E from price÷EPS, SMAs, YoY revenue, the P/E band — is
derived from `market_data`. Re-fetching market data without recomputing would
leave the brief internally inconsistent: fresh prices next to stale SMAs. The
dependency is declared in the planner rather than in the graph topology because
it's a data dependency, not a routing one.

**Q3.10 — Why is the planner deterministic instead of LLM-driven?**
For an MVP the subtask set is fixed and known: the same six workers every time.
An LLM planner would add a call, latency, and a class of failure ("the planner
forgot to queue the news worker") for zero benefit. The code carries a
`# UPDATE:` marker noting where an LLM planner would slot in if the subtask set
ever became query-dependent (e.g. "only run peers if the sector is known").

**Q3.11 — How is progress surfaced from inside the graph?**
`graph.stream(initial, stream_mode="updates")` yields `{node_name: partial_state}`
after each node. The runner merges those into `final_state` and calls
`progress_cb(node_out["status_message"] or node_name)`. The callback is wrapped
in try/except — a broken progress callback must never fail a research job.

**Q3.12 — Why `stream_mode="updates"` rather than `"values"`?**
`"updates"` yields only what each node changed, which is exactly the payload the
progress callback needs and keeps the merge cheap. `"values"` would emit the
entire accumulated state after every node — including three years of daily
closes, five times over.

**Q3.13 — Why is the compiled graph a module-level lazy singleton?**
```python
_GRAPH = None
def get_graph():
    global _GRAPH
    if _GRAPH is None: _GRAPH = build_graph()
    return _GRAPH
```
Compiling validates and builds the topology; it's identical for every request,
so doing it per-job is wasted work. It's lazy rather than import-time so that
importing `graph.py` in a test doesn't force a compile.

**Q3.14 — Is the compiled graph safe to share across threads?**
Yes — it's stateless. All mutable state lives in the `state` dict passed into
`.stream()`, which is per-invocation. Nothing is stored on the graph object
between runs.

**Q3.15 — What's a checkpointer and why don't you have one?**
A checkpointer persists state after each superstep so a run can resume where it
crashed. `build_graph()` has the marked seam:
```python
# return g.compile(checkpointer=RedisSaver(...))
```
It's not wired because today a crashed job is simply re-run — jobs are short and
idempotent, and durable resume would mean serialising 3y of price history to
Redis every superstep. It's listed as follow-up #2.

**Q3.16 — What happens if a worker node raises?**
It propagates out of `graph.stream()`, out of `run_research_pipeline`, and is
caught by the blanket handler in `_execute_job`, which marks the job failed with
`error_code="internal_error"`. That's the *last* line of defence — every worker
is written so it never gets there: `market_worker` catches
`MarketDataUnavailable`, `peers_worker` and `shareholding_worker` wrap in bare
`except Exception`, and the news/filings tools swallow per-source failures.

---

## 4. Planner, workers, calc

**Q4.1 — What does each worker do and how does it fail?**

| Worker | Source | Failure behaviour |
|---|---|---|
| `market` | yfinance: 3y history, `.info`, `.financials`, `.quarterly_income_stmt`, + optional Alpha Vantage fallback | Catches `MarketDataUnavailable`, emits `unavailable: True` + reason; job continues with news/filings/peers |
| `news` | 4 India RSS feeds (primary) + Tavily (supplement) + 1 batched LLM call | Each feed fails independently; LLM failure → keyword heuristic; no articles → stub item |
| `filings` | Tavily India-domain search + yfinance calendar | Returns a stub/N-A entry, never raises |
| `peers` | Curated `peer_groups.json` + reused market/calc per peer | Ticker not in map → `available:false` + reason; one bad peer → that row omitted |
| `shareholding` | NSE shareholding-pattern endpoint via `nsepython` | `available:false` + reason, cached 7 days |
| `calc` | Pure Python + NSE `allIndices` for sector P/E | Band and sector P/E each degrade independently |

**Q4.2 — Why does `market_worker` return a shaped "unavailable" bundle rather than raising?**
This is audit finding #1.1, the worst bug in the original code. `fetch_market_bundle`
had no try/except, so one yfinance 429 crashed the entire job — discarding news
and filings work that had already succeeded. Now the tool raises a *typed*
`MarketDataUnavailable`, the worker catches it and returns a bundle with
`unavailable: True`, empty price/fundamentals, and the NSE quote URL, so the
synthesizer can still assemble a brief and the UI shows "market data unavailable
this run" instead of a blank failed job.

**Q4.3 — Why does the tool raise instead of returning `None`?**
Because the failure is meaningful and typed. `MarketDataUnavailable` distinguishes
"we asked and got nothing" from "we got a partial bundle". And the raise fires
only when *both* `last_price` and `market_cap` are absent — a partial bundle
(price but no fundamentals) is still useful and returns normally.

**Q4.4 — Explain the `pct_change` logic in `market_data.py`.**
It's date-based, not index-based:
```python
target = closes.index[-1] - pd.Timedelta(days=calendar_days)
prior  = closes[closes.index <= target]
```
Taking `closes.iloc[-30]` for "1 month" would be wrong — 30 *trading* days is
about six weeks of calendar time, and Indian markets have a lot of holidays.
The nearest close on or before the calendar target is the correct semantics.
There's a fallback: if history is slightly shorter than requested (2.9y of data
for a 3y window), it accepts the oldest close as long as the span covers ≥90%
of the request; below that it returns `None` rather than an inflated number.

**Q4.5 — Why 3 years of history?**
It's the shortest window that supports the longest horizon in the UI (3Y change),
and it's what feeds the downsampled price chart and the SMA calculations.

**Q4.6 — How does the news worker enforce the corroboration rule?**
```python
if sentiment in ("bullish","bearish") and corroboration < 2:
    sentiment = "insufficient_data"
```
Articles from RSS and Tavily are pooled, clustered by title similarity, and each
cluster's `corroboration_count` is the number of **distinct outlets**, not
articles. A directional label needs at least two independent outlets; below that
it's downgraded to `insufficient_data` with an explanatory rationale. Critically
this is enforced **in Python after the LLM answers**, not asked for in the prompt
— a prompt instruction can silently drift, a post-condition cannot.

**Q4.7 — Why RSS first and Tavily second?**
RSS from Economic Times, Moneycontrol, Livemint and Business Standard is free,
keyless, structured (title/summary/timestamp/link) and comes straight from
India's financial press. Tavily returns web-search snippets — lower signal, and
metered. So RSS is primary and Tavily supplements it for freshness and coverage.
NewsAPI/GNews were evaluated and rejected: weak Indian coverage on free tiers.

**Q4.8 — How are the four RSS feeds fetched?**
Concurrently, in a `ThreadPoolExecutor(max_workers=len(_FEEDS))`, each wrapped so
one failure contributes zero articles instead of taking down the worker. Business
Standard 403s a default httpx User-Agent — confirmed live — so a browser-shaped
UA is set explicitly. That's documented in the module docstring so nobody
"cleans it up" later.

**Q4.9 — Why one batched LLM call for sentiment instead of one per article?**
Five articles = five round-trips, five rate-limit chances, five failure points.
One call with a numbered list and a JSON-array response is a single failure point
and roughly a fifth of the latency. The response is keyed by `index`, and any
index missing from the response falls back to the keyword heuristic — partial
LLM output degrades per-article rather than losing everything.

**Q4.10 — How do you parse JSON out of a free model that likes to chat?**
`_safe_json_list` strips markdown fences, slices from the first `[` to the last
`]`, then `json.loads` inside a try/except that returns `[]` on failure. Any
unparseable response degrades to heuristics rather than raising.

**Q4.11 — What's the keyword heuristic fallback?**
Two curated word lists (`_BULLISH_WORDS`, `_BEARISH_WORDS`) matched against
title + content; whichever side has more hits wins, ties are neutral. It also
returns a rationale naming the matched words, so the fallback output is
explainable rather than an unexplained label. The point is that the brief never
says "sentiment unavailable" — a deterministic answer with visible reasoning
beats an empty section.

**Q4.12 — Why is peer group data a hand-curated JSON file?**
Because yfinance's `info['sector']` / `info['industry']` are frequently missing
or wrong for Indian tickers — verified by spot-checking during development.
`peer_groups.json` is derived from NSE's publicly downloadable sectoral index
constituent lists: 57 tickers mapped to peer groups and to a sector label, plus
12 sector→NSE-index mappings shared with the sector-P/E feature so both agree on
one taxonomy. If a ticker isn't in the file it returns
`available: false, reason: "not in the curated peer-group list"` — it never
guesses a peer group.

**Q4.13 — How does the peer worker avoid one bad peer breaking the table?**
`_row_for()` returns `None` (not a raise) when a peer's market bundle is
unavailable, and rows are fetched concurrently in a `ThreadPoolExecutor`. Failed
peers are omitted. There's one hard invariant: if the **subject** row is missing,
the entire comparison returns `available: false` — a peer table without the
stock you asked about is misleading, not partial.

**Q4.14 — What is `nsepython` and why is it isolated?**
NSE's own internal JSON endpoints (`corporate-share-holdings-master`,
`allIndices`) are the only free route to SEBI-disclosed promoter holdings and
sectoral index P/E. A plain `requests.get` to nseindia.com is refused by their
WAF; `nsepython.nsefetch` replays a browser-shaped session (headers + cookie
handshake). These are undocumented, unsupported and a grey area under NSE's
terms — fine for a portfolio project, not for production. So exactly two modules
(`tools/shareholding.py`, `tools/sector_pe.py`) import it or know the endpoint
shape. Swapping to a licensed vendor means rewriting those two files; the graph,
workers, synthesizer and UI don't change. I'd lead with that framing in an
interview rather than hide it.

**Q4.15 — Why did you not use yfinance for shareholding?**
Checked live, not assumed: `.institutional_holders` returns an empty DataFrame
for NSE tickers, and `.major_holders` returns a generic insiders/institutions
split sourced from **US SEC 13F filings**, which don't cover NSE/BSE companies.
Structurally the wrong source. That verification is written into the module
docstring so the reasoning survives.

**Q4.16 — Explain the P/E band calculation.**
Pure math, no I/O, no LLM (`compute_pe_band` in `tools/code_exec.py`):
1. `quarterly_eps` arrives newest-first from yfinance; reverse to oldest-first.
2. Slide a 4-quarter window to get trailing-twelve-month EPS at each quarter end.
3. Skip any window containing a `None` EPS — never interpolate.
4. Find the nearest close on or before that quarter-end date.
5. `pe = price / ttm_eps` → a series, plus min/max/avg.
Guards: fewer than one complete 4-quarter window → `available: false` with a
reason naming how many quarters were found. Fewer than 8 quarters → still
computed but flagged `partial_history: true`, and the UI says "band is
directional only". Zero TTM EPS is skipped (no division by zero).

**Q4.17 — Why is sector P/E computed inside `calc` and not its own worker?**
The principle is "extend calc for computation; add a worker for independent I/O".
It's one small, day-cached lookup that's semantically part of the valuation
block, and spinning up a sixth node for it would add graph surface for no
concurrency benefit — it isn't on the critical path.

**Q4.18 — What does `run_calculations` compute?**
P/E from price÷EPS, YoY revenue growth from the two newest annual revenue rows,
SMA-20 and SMA-50 over closes, plus a `notes` list that records when the
reported P/E and the derived P/E differ by more than 1.0. It's guarded
throughout: `eps not in (None, 0)`, `older != 0`, and `_sma` returns `None`
rather than a partial average when there aren't enough data points.

**Q4.19 — Why compute P/E yourself when yfinance reports one?**
Cross-validation. Reported `trailingPE` and `last_price / trailingEps` should
agree; when they diverge by more than 2.5 the critic raises `PE_MISMATCH` and
retries the market worker. It's a free consistency check that catches stale or
mismatched upstream fields — the same idea as a checksum.

---

## 5. Synthesizer & critic

**Q5.1 — What does the synthesizer actually do?**
It's the assembly step, not a "writing" step. It reads every worker's state key,
dedupes sources by id, builds the structured brief with `source_ids` attached to
each claim block, downsamples price history for the chart, derives risk flags,
collects `data_gaps`, and then makes exactly one LLM call for the prose summary.
If that call fails or returns garbage, a deterministic fallback composes a
readable summary from the same data.

**Q5.2 — Why dedupe sources, and why keep the *last* occurrence?**
Audit finding #3.1. `sources` uses `operator.add`, so it concatenates across
critic retries. Source ids are deterministic (`src-news-{ticker}-{i}`), so a
retried news worker appends a second `src-news-RELIANCE.NS-0` alongside the
stale first attempt's — and the UI rendered both, showing contradictory
citations under the same reference number. `_dedupe_sources` keeps insertion
order but keeps the **last** value per id, because the most recently written
value is the one belonging to the attempt that actually survived into this brief.

**Q5.3 — How does price history get downsampled?**
`_downsample_history` thins ~750 daily closes to ≤240 points with a stride, and
explicitly appends the final close if the stride skipped it — otherwise the
chart would end days before the current price. 240 points is more than the pixel
width of the chart, so nothing visible is lost, and the payload shrinks ~3×.

**Q5.4 — How are risks generated?**
Deterministically, from data already fetched: up to 3 risk factors per filing
(medium), each calc consistency note (low), a "bearish news tone" flag when
overall sentiment is bearish (medium), and — the highest-signal one — a
"Promoter stake declined QoQ" flag whose severity is **high** if the drop is
≥1.0 percentage point, else medium. No LLM invents a risk.

**Q5.5 — Walk me through the analyst-summary prompt.**
It's a constrained prompt with a compacted JSON payload (only the fields the
summary may reference, truncated to 6000 chars) and five numbered content
requirements: performance across horizons, valuation vs its own band and its
sector, news flow with near/far impact, promoter trend, and a one-line outlook.
Then explicit prohibitions: only use facts from the JSON, never invent numbers,
never state a price target, never use directive language, skip missing data
silently, prose only — no markdown or JSON.

**Q5.6 — You told the model not to say "buy". Is that enough?**
No, and that's the point of the compliance filter. Prompt instructions are
best-effort; the deterministic regex rewrite in `core/compliance_filter.py` runs
over the output on every critic pass regardless. Prompt = first line of defence,
code = the guarantee.

**Q5.7 — What is `looks_like_prose` and why does it exist?**
Free models sometimes return non-empty *garbage*. Captured live from
`openai/gpt-oss-20b:free`:
`"? = is... is, isALG(?.. is?.....com.... ...………iqué………i…...."`.
Every fallback in the codebase guarded on `if text:` — so this sailed straight
into the brief. `looks_like_prose` is a deterministic gate: ≥80 chars, ≥20
words of 3+ letters, ≥85% of characters from an expected set for English
financial prose, and ≥35% unique words (degenerate output repeats one token).
It's deliberately permissive — a garbage detector, not a quality grader — and
it's unit-tested with 7 tests including the captured real-world string.

**Q5.8 — Why not use a second LLM call to judge the first?**
Cost, latency, and non-determinism. Judging "is this word salad" is a
mechanical property of the text; using a model to check a model adds a second
thing that can fail in the same way. LLM-as-judge is marked as a `# UPDATE:` for
a harder problem — detecting *unsupported claims* in the summary, which regexes
genuinely cannot do.

**Q5.9 — What does the fallback summary produce?**
A real paragraph assembled from the fetched data: last traded price, every
non-null horizon change, P/E and EPS, YoY revenue, sector P/E comparison,
promoter holding with QoQ delta, overall sentiment, position relative to the
20/50-day SMAs, and a closing risk caveat. A user who gets the fallback still
gets a useful brief and never sees an error string.

**Q5.10 — What checks does the critic run?**
Four gate functions producing `CriticIssue{code, message, failed_subtask, claim}`:
1. `_check_pe_consistency` — reported vs derived P/E within 2.5 → `PE_MISMATCH`
   → retry `market`.
2. `_check_citations` — `price_action`, `fundamentals`, `calculations`, every
   news item and **every filing** must carry `source_ids`, and every id must
   exist in `sources` → `MISSING_CITATION` / `DANGLING_CITATION` /
   `NEWS_UNCITED` / `FILING_UNCITED`.
3. `_check_news_freshness` — no articles → `NO_NEWS`; nothing within 45 days
   (when ≥2 items are dated) → `STALE_NEWS`; no http(s) URLs → `NEWS_NO_URL`.
   All-stub news is tolerated so keyless demos still run.
4. `_check_required_sections` — non-empty `analyst_summary`, non-null
   `last_price`.

**Q5.11 — What was the filings-citation bug?**
Audit #3.2: the critic never iterated `draft["filings"]`, so `"filings"` was
literally unreachable as a `failed_subtask` — there was no code path that could
ever ask the planner to retry the filings worker. It was masked because the
filings worker always sets `source_ids`, but it was a real coverage hole. Fixed
by adding the loop.

**Q5.12 — Why do confidence scoring and the compliance filter run *inside* the critic, and on every pass?**
Both are pure, cheap, idempotent functions with no external dependency, and both
must apply even to a **force-accepted** brief. If they only ran on a clean pass,
a brief that exhausted its retries would ship with no confidence tags and, worse,
un-rewritten advice language — the exact case where you least want the safety
pass skipped.

**Q5.13 — Explain `critic_passed` vs `accept`.**
Two different facts. `truly_passed = len(issues) == 0` is what gets written into
the brief as `critic_passed` and rendered as the "Critic passed / warnings"
badge. `accept = truly_passed or force_accept` is the routing decision. So a
force-accepted brief routes to `finalize` but is still honestly labelled as
having warnings, with the specific issues listed in `critic_notes`.

**Q5.14 — Why is the tolerance 2.5 for the critic but 1.0 for the calc note?**
Layered thresholds. 1.0 is "worth mentioning to the user" — it becomes a low-
severity note. 2.5 is "worth spending a retry on". Market cap and reported P/E
can be computed against a slightly different snapshot than the last close, so a
small drift is normal and shouldn't burn a retry. Both are single constants in
one place each; the code marks per-metric tolerance tables as a `# UPDATE:`.

---

## 6. Compare mode

**Q6.1 — How does "TCS vs INFY" work?**
`detect_compare_intent` splits it into two queries, the job is created with
`mode="compare"`, and `run_compare_pipeline` runs the **existing** compiled
single-ticker graph twice, concurrently, in a `ThreadPoolExecutor(max_workers=2)`.
Each side gets the full planner → workers → critic → targeted-retry treatment
independently. Then `build_comparison` joins the two finished briefs into a
metrics table plus a narrative.

**Q6.2 — Why not build a compare-specific graph?**
Because a comparison *is* two research jobs plus a join. A second graph topology
would duplicate every node and double the surface area for bugs, and the two
sides would drift apart the moment someone changed one. Compare mode is
deliberately "mostly wiring".

**Q6.3 — Is the metrics table LLM-generated?**
No — pure data assembly. Every number in it was already computed by `calc` for
each side individually. Only the prose narrative touches an LLM, and it goes
through the same `rewrite_text` compliance pass and the same `looks_like_prose`
gate, with the same deterministic fallback.

**Q6.4 — How does intent detection work, and why the LLM fallback?**
Two regexes first — `X vs Y` and `compare X and|with|vs Y` — which are free,
instant, and cover the large majority of real phrasing. The LLM fallback fires
**only** when the query contains a comparison-ish word but the regex couldn't
cleanly split it, so the common single-ticker path never pays for an LLM call.
The fallback is told to answer `null` when it isn't clearly a two-way comparison,
and any parse failure returns `None` → normal single-ticker pipeline.

**Q6.5 — There are two compare-detection implementations. Why?**
Deliberate. `services/intent.py` (regex + LLM) runs on the **submit** path,
where one extra call is acceptable. `stock_search.detect_compare_pair` is
regex-only and runs on the **typeahead** path — an LLM call on every keystroke
would be absurd. The typeahead version only powers a suggestion chip ("that
reads as a comparison — switch to compare mode"), so a missed detection there
costs nothing.

**Q6.6 — What's the timeout budget for a compare job?**
The same 420s as a single job, because both sides run concurrently — wall-clock
is bounded by the slower side, not the sum. That reasoning is written as a
comment at the `asyncio.wait_for` call so nobody "fixes" it by doubling it.

**Q6.7 — How is progress reported for two concurrent pipelines?**
Each side's callback prefixes its messages with `a:` / `b:`. `PipelineStatus`
strips the prefix with `replace(/^[ab]:/, "")` for step-guessing and changes its
heading to "Agent pipeline (both stocks)" so the user knows one tracker is
covering two runs.

---

## 7. Concurrency, threading & async

**Q7.1 — Map every concurrency mechanism in this codebase.**

| Mechanism | Where | Why |
|---|---|---|
| `asyncio` event loop | FastAPI routes, Redis, cache, search, model catalog | Native async I/O for request handling |
| `BackgroundTasks` | `POST /research` | Return `job_id` immediately; run the pipeline after the response |
| `asyncio.to_thread` | `_execute_job` | LangGraph's `.stream()` is sync and CPU/blocking — running it inline would freeze the event loop |
| `asyncio.wait_for` | around the above | 420s hard cap |
| `asyncio.run_coroutine_threadsafe` | progress callback | Called from the worker thread; job-store writes are coroutines owned by the loop |
| LangGraph superstep parallelism | 5 I/O workers | Framework-level fan-out |
| `ThreadPoolExecutor` | RSS feeds (4), peer rows (≤5), compare sides (2) | Blocking `httpx`/yfinance calls inside sync graph nodes |
| `ContextVar` | model override | Per-job model selection without threading an argument through a dozen call sites |
| `AbortController` | frontend search | Cancel superseded typeahead requests |
| `inFlight` flag | frontend poll | Prevent stacked polls when the server is slow |

**Q7.2 — Why `asyncio.to_thread` specifically?**
`graph.stream()` is synchronous and does blocking network I/O through yfinance,
feedparser and the LLM client. Calling it directly in an async route would block
the event loop for the entire job — no other request could be served. `to_thread`
moves it to the default `ThreadPoolExecutor` and gives back an awaitable.

**Q7.3 — Explain the `ContextVar` for model selection.**
`get_chat_model()` is called from about a dozen places deep in the graph
(news worker, synthesizer, compare, intent, search fallback). Threading a
`model` parameter through every one of them would force modules that have no
business knowing about model choice to carry it. Instead, `run_research_pipeline`
calls `set_model_override(model)` as its very first statement — *inside the
worker thread that will execute the job* — and every client built inside that
context picks it up via `active_model_id()`.

**Q7.4 — Why a `ContextVar` and not a module-level global?**
A global would be shared across threads: two concurrent jobs with different
models would overwrite each other, and the two sides of a compare would fight.
Each thread started via `to_thread` / `ThreadPoolExecutor` gets its own context,
so a `ContextVar` set inside a thread stays confined to it. That's why the
`set_model_override` call is inside `run_research_pipeline` rather than in the
API route — setting it in the route would put it on the event loop's context,
not the worker's.

**Q7.5 — In compare mode, who sets the override?**
Three places, deliberately. `run_compare_pipeline` sets it in *its* thread
(because the comparison narrative LLM call happens there), and each side's
`run_research_pipeline` sets it again inside its own pool thread.

**Q7.6 — Why is there a `use_model` context manager as well?**
A scoped variant using `_model_override.set(...)` / `.reset(token)` for call
sites that must restore the previous value rather than pin it for the rest of
the context.

**Q7.7 — Why nested thread pools (compare → 2 pipelines → peer/RSS pools)?**
Because each level is blocking I/O with independent latency. The nesting is
bounded and small: 2 sides × (4 RSS + 5 peer rows) worst case, and those inner
pools are short-lived context managers. There's no unbounded fan-out.

**Q7.8 — What happens on timeout — is the thread killed?**
No, and the code says so explicitly:
```python
# NOTE: the worker thread may keep running after timeout (Python threads
# can't be force-killed); the job is still marked failed for the client.
```
`asyncio.wait_for` cancels the *await*, not the thread. The job is marked failed
with `error_code="timeout"` and a message explaining that free models are
rate-limited. The orphaned thread finishes and its result is discarded. Fixing
that properly means process isolation or cooperative cancellation checks between
supersteps — a real trade-off I can defend rather than a gap I missed.

**Q7.9 — Why `cache_get_sync` / `cache_set_sync` alongside the async ones?**
The async cache functions await a `redis.asyncio` client. Graph worker nodes run
in a background thread with no running event loop, so they can't await. The sync
variants are memory-only. It's an explicit, documented limitation: worker-node
caching is per-process, and Redis-backed caching only happens on async API paths
(search, model catalog).

**Q7.10 — Is the in-memory cache thread-safe?**
It's a plain dict with single-operation get/set. CPython's GIL makes those atomic
enough that there's no corruption; the worst case is two threads both missing and
both fetching, which wastes a call but produces a correct result. For a
per-process cache of slowly-changing data that's an acceptable trade; a real
distributed cache would need Redis (which is already the preferred backend on
async paths).

---

## 8. FastAPI & the API layer

**Q8.1 — List every endpoint.**

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/research` | Start a job. `{query, model?}` → job record |
| `GET` | `/api/v1/research/{job_id}` | Poll status + `brief` or `compare_brief` |
| `GET` | `/api/v1/search?q=&limit=` | Ranked typeahead candidates |
| `GET` | `/api/v1/models?refresh=` | Selectable LLMs, default first |
| `GET` | `/api/v1/health` | Redis status, job store backend, provider, active model |
| `GET` | `/docs` | OpenAPI/Swagger, free from FastAPI |

**Q8.2 — Why validate the model id at the route rather than in the pipeline?**
Two reasons. Cost: a bad id caught at the route costs one 400; caught inside the
job it surfaces as a failure several minutes later. **Security**: the OpenRouter
API key is the *server's*. An unvalidated `model` in a request body would let any
caller spend it on a paid model. `validate_model` raises `ValueError`, the route
turns that into a `400` with a readable message, and the frontend surfaces the
message rather than a bare status code.

**Q8.3 — Explain the error taxonomy.**
Four machine-readable `error_code`s, so the UI can be specific instead of
showing one generic failure. The dimension they split on is **who can fix it**:
- `ticker_not_found` — `TickerResolutionError`; the *user* mistyped. Carries
  `suggestions`, the same ranked candidates the search endpoint returns, so the
  UI renders one-click "did you mean" chips.
- `data_provider_unavailable` — `ProviderUnavailableError`; Yahoo refused every
  lookup. Nobody's typo, nobody's bug — the *operator* or time fixes it.
  Deliberately carries **no** suggestions, because a retype cannot help.
- `timeout` — exceeded 420s, with a message about free-model rate limits.
- `internal_error` — genuine bug; logged with `logger.exception`.

This started as audit finding #1.3 (all failures were indistinguishable
stringified errors) with three codes; the fourth was added after a hosted
deploy — see Q10.17 and Q20.11.

**Q8.3b — Why is the "provider blocked" case a separate code rather than reusing `internal_error`?**
Because `internal_error` means "we have a bug" and triggers a different human
response: I go read a stack trace. A provider block is neither a bug nor a bad
input — the correct response is *wait, or change the egress IP*. Collapsing them
would mean every 429 storm from Yahoo looked, in the logs and in the UI, exactly
like a crash in my own code. Three distinct causes deserve three distinct codes
precisely so the on-call action differs.

**Q8.4 — Why is `TickerResolutionError` a `ValueError` subclass carrying suggestions?**
`ValueError` because an unresolvable query genuinely is a bad value. Carrying
`suggestions` means a dead end is recoverable in one click instead of a retype
— the exception itself knows what it thinks you meant.

**Q8.5 — How does the job store work?**
Redis-first with an in-memory dict fallback, decided per call via
`get_redis()` returning `None` when Redis never connected. `save_job` writes JSON
with a TTL of `brief_cache_ttl_seconds * 6` (6 hours); `get_job` tries Redis then
falls back to memory; `update_job` is read-modify-validate-write through
`ResearchJobResponse.model_validate`, so every write is schema-checked.

**Q8.6 — Isn't read-modify-write a race?**
Yes, in principle: two concurrent `update_job` calls could interleave and lose an
update. In practice each job has exactly one writer (its own background task), and
progress updates are idempotent-ish — losing one intermediate progress string is
invisible. A production version would use a Redis hash with field-level `HSET`,
or optimistic concurrency. I'd name it as a known trade-off rather than claim it's
safe by design.

**Q8.7 — How does the app degrade without Redis?**
Fully. `init_redis` catches the connection failure at startup, logs a warning and
leaves `_redis = None`; job store and cache both fall back to process memory. The
cost is that jobs don't survive a restart and don't work across multiple workers
— which is exactly why `/health` reports `job_store: "redis" | "memory"`.

**Q8.8 — Why is search a separate endpoint from research?**
Documented in the route's docstring: search is a read-only, cached, sub-second
lookup that fires on every keystroke; research kicks off a multi-minute pipeline.
Keeping them apart means a burst of typing can never queue research jobs.

**Q8.9 — Why does search never 404 or 500?**
A search box must not break the page. The route wraps `search_stocks` in
try/except and returns `StockSearchResponse(query=q, suggestions=[], layers_used=[])`
on any exception — an empty suggestion list is a valid answer, and the user can
still submit the raw text.

**Q8.10 — What does the lifespan handler do?**
`setup_logging()`, `init_redis()`, and a fire-and-forget Ollama warm-up task
(a no-op unless `LLM_PROVIDER=ollama`) that preloads the model so the first job
doesn't pay load time. On shutdown it cancels the warm-up and closes Redis.
The warm-up is `asyncio.create_task`, not awaited, so startup isn't blocked.

**Q8.11 — How is CORS configured?**
`CORSMiddleware` with `allow_origins=settings.cors_origins_list`, parsed from a
comma-separated env var (defaults to the Vite dev ports 3000 and 5173).
Not `*` — the origin list is explicit config.

**Q8.12 — Where do Pydantic response models get used?**
Every route declares `response_model=`, which gives request validation, response
serialisation, and a complete OpenAPI schema for free. `ResearchRequest`
constrains `query` to 1–120 chars and `model` to ≤120 — input bounds at the edge.

---

## 9. Data sources & the tools layer

**Q9.1 — Enumerate every external dependency and its auth requirement.**

| Source | Key needed | Used for |
|---|---|---|
| yfinance (Yahoo) | none | Price history, fundamentals, quarterly EPS, annual revenue, earnings calendar |
| Yahoo Finance search API | none | Ticker resolution + search layer 2 |
| ET / Moneycontrol / Livemint / Business Standard RSS | none | Primary news |
| NSE `corporate-share-holdings-master` (via nsepython) | none | Promoter % + QoQ delta |
| NSE `allIndices` (via nsepython) | none | Sector-average P/E |
| NSE archives CSVs | none | Search-catalog build script |
| OpenRouter | **yes** (default LLM) | Sentiment, summaries, search/intent fallbacks |
| Tavily | recommended | News supplement + India filings search |
| Alpha Vantage | optional | Market-data fallback |
| OpenAI / Anthropic / Ollama | optional | Alternative LLM providers |

The whole thing runs on free tiers; the only strictly required key is OpenRouter.

**Q9.2 — Why not SEC EDGAR for filings?**
EDGAR doesn't cover Indian companies at all. Indian issuers file with the
exchanges and the MCA. So `india_filings.py` uses Tavily restricted to
moneycontrol / economictimes / nseindia / bseindia / business-standard, plus
yfinance's earnings calendar. The proper production source — NSE's corporate-
announcements API or BSE XBRL feeds — is marked as follow-up #4.

**Q9.3 — How do you clean scraped filing text?**
`_clean_snippets` strips markdown headers, `[...]` markers and pipes; splits on
sentence boundaries; drops fragments under 40 chars; drops known nav junk
("sign up", "open trading a/c", "stock scanner"); drops ticker-tape fragments
where letters are under 55% of the string; truncates at a word boundary with an
ellipsis; and dedupes. It's a heuristic pipeline, and I'd describe it as such.

**Q9.4 — There's a dedupe on filings too. Why?**
Observed live for RELIANCE: Tavily returned two different URLs whose scraped
text was the same exchange disclosure. Without a fingerprint check the brief
rendered the identical filing twice *and* derived duplicate risk flags from it.
The fix fingerprints the first 120 chars of the first cleaned snippet.

**Q9.5 — Why is `core/ticker.py` a separate module for four one-line functions?**
Audit finding #2.1. `ticker.replace(".NS","").replace(".BO","")` and
`.endswith(".BO")` were reimplemented independently in four files. Four copies
of the same assumption means a future change — say, numeric BSE codes — has to be
found and fixed in four places. Now there's one definition of what a ticker is,
and it has its own tests.

**Q9.6 — How does Alpha Vantage fallback work?**
Only triggered when yfinance returned no price *and* a key is configured. It
tries symbol variants (`.NSE`, `.BSE`, raw) because AV's India symbology is
inconsistent, and returns a minimal price dict. If it succeeds, `provider` on
the bundle flips to `alpha_vantage` — which matters, because
`score_exchange_data` uses the provider name to assign confidence.

---

## 10. Advanced search subsystem

**Q10.1 — Why build a search subsystem at all?**
Before it, the only entry point was `resolve_ticker()`: one query in, one ticker
out, exception otherwise. That's the wrong shape for a search box. "tata motor",
"the maggi company", "largest private bank" and a plain typo all failed
identically with no recovery path. Search is inherently ambiguous, so the API
should return *candidates with confidence* — the same trust vocabulary the brief
itself uses — and let the user pick.

**Q10.2 — Describe the three layers and their triggers.**
1. **Local catalog** — always runs. 2,378 NSE symbols from `nse_universe.json`
   plus 161 curated alias/brand entries from `stock_aliases.json`. Offline,
   sub-10ms.
2. **Yahoo Finance search** — runs only if the best local score < 0.90. Covers
   BSE-only listings and symbols newer than the last catalog rebuild.
3. **LLM interpretation** — runs only if the best score is still < 0.55 **and**
   the query is ≥2 words. For questions like "who makes jaguar cars".

**Q10.3 — How is a hallucinated ticker made impossible?**
The LLM is asked for company **names only**, never tickers. Every name it
returns is resolved back through layer 1 against the real NSE catalog. If the
name doesn't resolve, it's dropped. A symbol that doesn't exist in the catalog
can't appear in the output — that's structural, not a validation rule someone
could forget.

**Q10.4 — Walk through the scoring function.**
`_score_entry` computes the best score across independent signals, each with a
human-readable reason:

| Signal | Score |
|---|---|
| Exact NSE symbol | 1.00 |
| Exact company name | 0.97 |
| Curated alias exact ("HUL", "RIL") | 0.96 |
| Initials match ("SBI", "TCS") | 0.88 |
| Brand/product keyword exact ("maggi") | 0.80 (+0.04 per extra distinct hit, capped) |
| Every typed word matches a name word | 0.72 + 0.12 × tightness |
| Symbol prefix | 0.70 → 0.92, scaled by coverage |
| Company-name prefix | 0.68 → 0.92, scaled |
| Brand keyword partial | 0.68 |
| Substring in name | 0.58 |
| Sector match | 0.44 |
| Trigram fuzzy (typos) | 0.28 + 0.52 × Jaccard |

Then `+_tier_boost` (0.07 for Nifty-50 down to 0 outside Nifty-500) as a
tie-breaker. Thresholds: ≥0.85 high, ≥0.62 medium, else low.

**Q10.5 — Explain the trigram fuzzy matching.**
Each symbol and name is decomposed into padded character trigrams
(`"  RELIANCE "` → `{"  R", " RE", "REL", ...}`) and inverted into
`trigram → [entry indices]` at load time. A query's trigrams look up candidate
entries; similarity is Jaccard over the trigram sets. It handles transposition
typos ("relaince") that prefix matching can't.

**Q10.6 — Why are symbol and name trigrams kept separate?**
Because Jaccard against a *merged* set is dominated by whichever field is longer.
With a merged set, "relaince" scored no better against RELIANCE than against
unrelated long names. Scoring each field separately and taking the max fixed it.
That reasoning is a code comment on the dataclass field.

**Q10.7 — Why is fuzzy matching gated behind the trigram index and a score check?**
Two gates. `if best < 0.72` — don't spend the computation when something cleaner
already matched. And a result whose reason is "Closest match to your spelling" is
dropped unless the entry is in the trigram candidate set, so fuzzy hits can only
come from entries that actually share character shape.

**Q10.8 — Tell me about a scoring bug you fixed.**
Three, all preserved as comments:
- `_token_hits`: without a length floor, the single-letter "R" in "R R Kabel"
  matched *every* query starting with R. A bare 4-char floor still matched
  "Info Edge" against "Infosys". The rule became: a name word must be ≥4 chars
  **and** cover ≥60% of the typed word.
- `_phrase_in`: plain `in` matched the "EV" keyword inside "FEVICOL", pulling a
  carmaker into an adhesives search. Now it's whole-word regex containment.
- Query normalisation: "RELIANCE.NS" normalised to "RELIANCE NS", so the
  exchange suffix is stripped before matching.

**Q10.9 — What is `sector_intent` and why does it override scores?**
"IT companies" is a request for a *sector*, not for whichever symbol happens to
start with "IT". When the query contains a sector cue word (companies/stocks/
sector/firms) **and** maps to a known industry, sector members are pinned to 0.66
and non-members capped at 0.55 — demoted rather than dropped, since the user may
still have meant that one odd name. It's skipped entirely if something scored
≥0.95, so an outright identity match always wins.

**Q10.10 — What is the relative floor?**
`floor = max(min_score, 0.58 × top_score)`. Once there's a clear winner, padding
the list to `limit` with far weaker names is worse than showing fewer options —
a short confident list is the whole point of scoring them.

**Q10.11 — How does merging across layers work?**
`_merge` unions by symbol. When both the catalog and Yahoo found the same symbol
that's **corroboration** — the same principle the news pipeline applies to
headlines — so it gets +0.05 (capped at 0.999), keeps the better-scoring layer's
reason, and accumulates the source labels. The UI shows those as "via NSE listing
catalog + Yahoo Finance".

**Q10.12 — Why cap LLM-sourced suggestions at 0.70?**
0.70 is below the 0.85 "high confidence" threshold, so an interpreted match can
never read as "just run it", however cleanly the name resolved. The reason string
says so too: "Interpreted from your question — 'Nestlé India'".

**Q10.13 — Why bundle a catalog instead of hitting an API per keystroke?**
Documented in `build_stock_universe.py`: a typeahead fires on every character.
Yahoo's endpoint is unofficial, rate-limited and 200–400ms away; NSE's
autocomplete needs a cookie handshake. Neither is acceptable in the hot path,
and neither knows that "HUL" means HINDUNILVR. So the primary index is local and
the network is a supplement.

**Q10.14 — How is the catalog built and why are aliases in a separate file?**
`build_stock_universe.py` pulls NSE's public archives: `EQUITY_L.csv` (all
listed symbols, filtered to EQ/BE series — BZ is surveillance/suspended), plus
the Nifty 50/100/500 constituent lists for a popularity `tier` and the only free
industry label. Curated aliases and brand keywords live in a **separate**
hand-maintained file so regenerating the catalog never destroys curation; the
script only validates that every curated symbol still exists.

**Q10.15 — How does `resolve_ticker` differ from search?**
Search returns ranked candidates; `resolve_ticker` returns one ticker or raises.
It builds a candidate list — hardcoded alias map (fast path) → `catalog_exact`
(only accepts ≥0.85 confidence) → bare-symbol variants (`X.NS`, `X.BO`) → Yahoo
search for multi-word names — then validates each with a real `yf.Ticker(t).info`
call, taking the first that comes back live.

If nothing validates there are three distinct outcomes, in this order:
1. A high-confidence catalog hit exists → **return it anyway**, log a warning, and
   let the market section degrade itself (Q10.18).
2. Every validation attempt died on the wire → `ProviderUnavailableError` (Q10.19).
3. Otherwise → `TickerResolutionError` with `local_suggestions(query, limit=5)`
   attached for the UI's "did you mean" chips.

The ordering is the design: the catalog check is first because a symbol we can
identify offline shouldn't care *why* the probe failed.

**Q10.16 — What was the `.NS`/`.BO` resolution bug?**
Audit #9.1, and the most embarrassing one. `_clean_query` splits on dots, so
"TCS.NS" arrived as "TCS NS". The code that re-joined it lived *inside* the
`if " " not in cleaned:` block — where, by construction, a string containing a
space is unreachable. So **every** explicitly-suffixed ticker fell through to the
multi-word company-name search path and failed to resolve. Which meant the eval
harness, whose testset is all `.NS` tickers, had never actually been runnable.
Fix: hoist the re-join above the single-word test.

**Q10.17 — You deployed this and every single ticker failed to resolve. What happened?**
Yahoo Finance rate-limits and blocks **shared datacenter IP ranges**. On a laptop
every lookup resolves; on Render/Fly/Heroku the same code, same query, gets
refused — so `_validate("RELIANCE.NS")` returned `{}` for *everything*, no
candidate ever validated, and the job died as `ticker_not_found`. The user-facing
message was "Couldn't resolve that to a live NSE/BSE symbol — try the exchange
ticker (e.g. RELIANCE…)" **for the query RELIANCE**. Telling a user their spelling
is wrong when the spelling is perfect is the worst kind of error message: it sends
them off to fix something that was never broken.

Two independent fixes, and the ordering between them is the interesting part:
1. **Fall back to the offline catalog** when live validation fails but the bundled
   NSE universe already identified the company with high confidence.
2. **Distinguish "blocked" from "unknown"** with a typed
   `ProviderUnavailableError` → `error_code="data_provider_unavailable"`, for the
   case where even the catalog can't help.

**Q10.18 — Why is a catalog hit allowed to win when the live probe failed? Isn't that trusting stale data?**
It's a re-reading of what the probe is *for*. The live `yf.Ticker(t).info` call is
**enrichment** — it gives the canonical name and which exchange the symbol
actually trades on. It is not the authority on whether a listing exists;
`nse_universe.json`, built from NSE's own `EQUITY_L.csv`, is a better authority on
that than an unofficial quote endpoint. So when the catalog says with ≥0.85
confidence "RELIANCE is RELIANCE.NS, Reliance Industries Ltd", killing the whole
job because a third party wouldn't confirm it is throwing away a run the pipeline
can perfectly well finish.

And it degrades honestly downstream, which is what makes it safe: if quotes
really are unavailable, `fetch_market_bundle` raises `MarketDataUnavailable`, the
market worker returns its shaped `unavailable: True` bundle, and it lands in
`data_gaps` where the user sees it. Meanwhile news, filings, peers and
shareholding key off the **symbol alone** — none of them needed the Yahoo probe.
So the fallback converts "total failure" into "partial brief, labelled".

**Q10.19 — How do you tell "Yahoo is blocking us" apart from "that symbol doesn't exist"?**
By the *shape* of the failure, not its presence. A nonexistent symbol comes back
as an **empty-but-successful** response — HTTP 200, no useful fields. A block dies
**on the wire** — an exception out of the client. So `_validate` records which of
the two happened for every candidate it tries:
```python
def _provider_looks_blocked() -> bool:
    attempts = getattr(_probe, "attempts", 0)
    return attempts > 0 and getattr(_probe, "transport_errors", 0) == attempts
```
The predicate is deliberately strict — **every** attempt this pass must have died
on the wire. One successful "no such symbol" response proves the provider is
reachable, which means the query really is the problem, and the code falls through
to the normal `ticker_not_found` + suggestions path. Two tests pin exactly that
boundary: `test_provider_outage_is_not_reported_as_unknown_ticker` (all raise →
`ProviderUnavailableError`) and
`test_unknown_symbol_still_raises_ticker_not_found_when_provider_is_healthy`
(clean empty `info` → `TickerResolutionError`).

**Q10.20 — Why is the probe counter `threading.local()` rather than a plain module global?**
Same reasoning as the model-selection `ContextVar` (Q7.4), one layer down.
Compare mode runs both sides in their own pool threads, and each calls
`resolve_ticker` independently. A shared counter would cross-contaminate: side A's
successful validations would mask side B's total blockage, or vice versa, and the
outage detection would come out wrong depending on interleaving. `_begin_probe()`
resets the tally at the top of every `resolve_ticker` call, in that call's own
thread, so the predicate always describes exactly one resolution pass.

**Q10.21 — Why is `ProviderUnavailableError` a `RuntimeError` while `TickerResolutionError` is a `ValueError`?**
The base class encodes whose fault it is. A query that resolves to nothing
genuinely *is* a bad value, so `ValueError` — and that's why it carries
`suggestions`, because a bad value has plausible corrections. A blocked provider
is an environment failure with no bad value anywhere in sight, so `RuntimeError`,
and it deliberately carries no suggestions. If someone later writes `except
ValueError` around resolution to mean "handle user input problems", the outage
correctly refuses to be caught by it.

**Q10.22 — You changed a log level as part of this fix. Why does that count as a fix?**
`_validate`'s failure path logged at `debug`. A hosted deploy runs at the default
level, so a run that failed *every single lookup* produced **no log output at
all** — the one place in the codebase that knew why the job died was silent, and
I was left inferring the cause from a user-facing "ticker not found". It's now
`warning`, including `type(exc).__name__` so a 429 is distinguishable from a DNS
failure or a TLS error at a glance. Observability of the failure path is part of
the fix; a bug you can't see from the logs will happen twice.

**Q10.23 — What's the residual risk of the catalog fallback?**
That a symbol which was delisted or renamed *after* the last catalog rebuild now
resolves anyway, and the user gets a brief with an honestly-empty market section
instead of a clean "that symbol isn't live". I think that's the right trade —
"here's what we have, here's what's missing" beats a hard stop, and it's the same
graceful-degradation contract the rest of the project follows. The mitigations are
that the fallback logs a warning naming the ticker, only fires on a ≥0.85
confidence catalog hit, and shows up in the brief's `data_gaps`. The proper fix is
a scheduled catalog rebuild (the script already exists) rather than leaning on a
quote endpoint as a liveness check.

**Q10.24 — Isn't the real fix just to get an unblocked data source?**
Yes, and that's the honest framing: this is a mitigation for a hosting constraint,
not a solution to it. Real options are a licensed vendor with an SLA, a proxy or
egress IP that isn't in a flagged range, or the Alpha Vantage fallback path
(already in `market_data.py`) promoted from optional to primary in hosted
environments. What the fix *does* buy is that the failure is now correctly
attributed, visible in logs, and non-fatal — so the app is usable while the data
question gets solved properly.

---

## 11. LLM integration & model selection

**Q11.1 — Which LLM provider and why?**
OpenRouter by default: hosted (no local GPU), free models available, and
OpenAI-compatible so `langchain_openai.ChatOpenAI` works by just pointing
`base_url` at it. Ollama, OpenAI and Anthropic are supported via `LLM_PROVIDER`
— the factory in `services/llm.py` is the single swap point.

**Q11.2 — Why let the user pick the model per run?**
Free models are rate-limited and vary a lot on this specific workload — long
JSON context in, disciplined prose out. When one is busy or waffles, the useful
recovery is picking another, not waiting for a redeploy. `OPENROUTER_MODEL` is
now only the *default*.

**Q11.3 — How is the model catalog built?**
`GET /api/v1/models` fetches OpenRouter's public (unauthenticated) `/models`
index, keeps zero-priced entries, normalises them, and caches for an hour. A
static `FALLBACK_OPENROUTER_FREE` list is the floor so the picker is never empty
offline — flagged in the response as `live: false`. Sorting: server default
first, then a curated `PREFERRED_ORDER`, then everything else by context length.

**Q11.4 — Two filters matter in that catalog. Explain both.**
1. **Zero-priced means both directions.** A model with a zero prompt price but a
   non-zero completion price would still bill the server's key, so `_is_zero_priced`
   checks `prompt` and `completion`.
2. **Usable chat model.** The output-modality check is `⊆ {text}`, not "contains
   text": Google's Lyria music models are zero-priced and declare
   `text+image->text+audio`, so a naive "text is in the outputs" test lets a music
   generator into an equity-research picker. Extra *input* modalities are
   harmless. Plus an id-substring blocklist for guardrail/moderation/embedding/
   rerank/TTS/whisper endpoints — chat-shaped but incapable of writing a summary.

**Q11.5 — How do you prevent a caller spending your API key?**
`validate_model` runs before the job starts. It returns `None` (= server default)
for an empty id; accepts the configured default; refuses everything when
`selectable: false` (paid providers); accepts anything in the cached catalog; and
— the one interesting case — accepts an id ending in `:free` that isn't in the
cache, because OpenRouter's `:free` suffix *guarantees* zero cost and the cached
roster can lag a new release by up to an hour. Anything else is a 400.

**Q11.6 — Why is the configured default always injected into the catalog?**
If the operator's default has since gone paid or been renamed, it would fall out
of the free list — making the app's own default unselectable and causing every
request to fail validation. So it's appended if missing, labelled "Configured
server default".

**Q11.7 — What is `is_reasoning_model` for?**
Reasoning models spend hidden thinking tokens from the same output budget, so the
ordinary `max_tokens` cap makes them return an *empty* message. Detected by id
substring (`r1`, `qwq`, `thinking`, `gpt-oss`, `reasoning`, `-think`), and
`_max_output_tokens` raises the cap to ≥4000 for them. It's also surfaced in the
UI as a "Reasoning" badge so a slow run isn't a surprise.

**Q11.8 — Why `extra_body={"reasoning": {"effort": "low"}}`?**
Passed through to OpenRouter; ignored by models without a reasoning mode, and
keeps thinking cheap on the ones that have it. This workload doesn't need deep
reasoning — it needs summarisation of supplied facts.

**Q11.9 — What temperatures do you use and why?**
`temperature=0` for classification tasks (sentiment batch, compare-intent,
search interpretation) — those should be reproducible. `temperature=0.2` for the
two prose summaries — just enough variation to avoid stilted output, low enough
to stay grounded.

**Q11.10 — How many LLM calls per job, and what if they all fail?**
Two for a single-ticker job: batched news sentiment, and the analyst summary.
Compare adds one narrative call (plus, rarely, one intent-detection call). If
every call fails, the brief is still complete: sentiment comes from keyword
heuristics and the summary from the deterministic composer. Nothing user-facing
says "LLM error".

**Q11.11 — Are you doing prompt engineering or prompt *constraint*?**
Constraint. Both prose prompts pass a compacted, truncated JSON payload of only
the fields the output may reference, with explicit "ONLY use facts from the JSON",
"never invent numbers", "no price targets", "prose only". Then the *output* is
checked in code — `looks_like_prose` for quality, the compliance filter for
language. The prompt is the request; the code is the contract.

**Q11.12 — Why truncate the JSON payload to 6000 characters?**
Free models have modest effective context and get slower and less disciplined as
prompts grow. The compacted payload includes only what the summary is allowed to
reference (never raw price arrays, never the full news bodies), which keeps it
well under that anyway — the truncation is a hard stop, not the main mechanism.

---

## 12. Trust, safety & compliance

**Q12.1 — Explain the confidence scoring system.**
`core/confidence.py` — rule-based, zero dependencies, zero LLM calls, fully
unit-tested (10 tests). The table:

| Claim type | Confidence |
|---|---|
| Exchange data (yfinance / alpha_vantage / calc) | High |
| Cleanly-parsed filing | High |
| Partially/fallback-parsed filing | Medium |
| News with ≥2 independent sources | Medium |
| News, single source | Low |
| Stub/placeholder data | Low |
| Market data unavailable this run | `None` + explicit reason |

Every tagged block also carries a `confidence_reason` string, which becomes the
tooltip on the badge.

**Q12.2 — Why does confidence have no external dependency?**
Because it's a *trust* feature, not a data feature. Anything the user relies on
to judge the rest of the output must itself be maximally reliable and auditable.
Zero dependencies means it can be fully unit-tested and can never fail at
runtime.

**Q12.3 — Why is `apply_confidence` a pure function returning copies?**
`annotate_claim` returns `{**block, ...}` and never mutates in place, because
callers may reuse the source dict — and the critic can run up to three times, so
the function must be idempotent. Same input, same output, always.

**Q12.4 — Explain the SEBI-safe compliance filter.**
A frozen table of 12 `RewriteRule(pattern, replacement, reason)` regexes applied
to every free-text field: `analyst_summary`, every news `rationale` and `impact`,
every risk `detail`, and the compare narrative. Examples:
- "target price" → "historical price range"
- "buy rating" → "positive analyst coverage"
- "will rally" → "has historically moved higher in similar situations"
- "we recommend buying" → "historical patterns show"
- "guaranteed returns" → "no guaranteed outcome — past performance is not
  indicative of future results"

Every rewrite is logged as `{field, input_phrase, output_phrase, reason}` and
shipped to the client as `compliance_log`, which the UI renders in an expandable
audit trail.

**Q12.5 — Why rules instead of asking the LLM to be compliant?**
Because an LLM's idea of "compliant" drifts silently between calls, models and
prompt tweaks, and you cannot produce an audit trail of *why* it changed
something. A regex table is boring, but every rewrite is reproducible and logged
— which is the actual artifact a compliance reviewer would ask for. It's
intentionally the least "AI" module in the codebase, and I'd say that in an
interview as a feature, not an apology.

**Q12.6 — Why don't you just strip "buy" and "sell"?**
Deliberate scoping. Blanket substring-stripping would mangle "buyback",
"buyers", "sell-side" and ordinary prose. The rules target rating and
recommendation *contexts* — "buy rating", "we recommend buying", "you should
sell" — not bare words. That decision is written into the module docstring so it
reads as a choice rather than an oversight.

**Q12.7 — What are the limitations of a regex compliance filter?**
It catches known phrasings, not novel ones — a model could invent a formulation
no rule covers. Mitigations: it's layered (the prompt also forbids the language),
the eval harness asserts no banned phrase survives into the summary, and adding a
rule is a one-line change with a test. An LLM-as-judge pass for *semantic*
advice-giving is the marked follow-up.

**Q12.8 — Explain the corroboration/dedup design.**
`core/dedup.py` clusters articles by fuzzy title similarity using stdlib
`difflib.SequenceMatcher` at a 0.6 threshold. Each cluster's representative is
the article with the most content, annotated with `corroboration_count` = number
of **distinct outlets** and `corroborating_sources` = their names.

**Q12.9 — Why count outlets, not articles?**
So one feed re-publishing a wire story three times doesn't fake corroboration.
The set is built from `source_name or provider`, so three Moneycontrol items
about the same story count once.

**Q12.10 — Why `difflib` and not embeddings?**
Deterministic, free, and enough signal for same-day India financial-press
headlines about one ticker — those are near-identical strings, not paraphrases.
An embedding call per article would add latency and cost for a step whose only
job is *counting corroboration*, not understanding content.

**Q12.11 — What are `data_gaps` and why do they exist?**
A user-visible list on the brief of every section that degraded gracefully, with
the reason. It's assembled in the synthesizer from `market.unavailable`,
`peers.available`, `shareholding.available`, `pe_band.available` and
`sector_pe.available`. The `DataGapBanner` renders it prominently at the top of
the brief. It exists so a degraded brief is *legibly* degraded — the failure mode
we refuse is a section that looks complete but is silently empty.

**Q12.12 — How would an interviewer verify you don't hallucinate numbers?**
Three ways, all in the repo:
1. **Structural** — no LLM call anywhere receives a request to compute. Grep
   `get_chat_model` — 5 call sites: sentiment, summary, compare narrative,
   intent, search interpretation. None of them do arithmetic.
2. **Cross-check** — the critic recomputes P/E from price÷EPS and fails the
   brief on a >2.5 divergence.
3. **Eval** — `calc_pe_internal` asserts the brief's derived P/E equals
   `last_price / eps_ttm` within 0.05.

**Q12.13 — What about the legal/ethical side?**
The disclaimer is rendered inside the brief where the reader is actually looking,
not buried in a footer; the compliance filter enforces descriptive rather than
directive language; the confidence system makes weak claims visibly weak; and
the NSE-scraping caveat is documented openly in the README rather than glossed
over. It's a portfolio project, and it says so.

---

## 13. Caching & performance

**Q13.1 — What's cached, where, and for how long?**

| Data | TTL | Backend | Why |
|---|---|---|---|
| Shareholding pattern | 7 days | memory (sync path) | Updates ~4×/year |
| Sector P/E (live) | 1 day | memory (sync path) | Barely moves intraday |
| Sector P/E (static fallback) | 4 hours | memory | Shorter so a transient NSE outage doesn't pin us to stale-static data |
| Search suggestions | 6 hours | Redis or memory | Catalog only changes on a listing/rename |
| Model catalog | 1 hour | Redis or memory | OpenRouter's free roster changes on the order of days |
| Job records | 6 hours | Redis or memory | Brief retrieval after completion |
| NSE catalog in-process | forever | `lru_cache(maxsize=1)` | 2,378 entries + trigram index, built once per process |

**Q13.2 — Why is the static sector-P/E fallback cached for *less* time than the live value?**
Because it's worse data. Caching it for a full day would mean one transient NSE
outage pins the app to a frozen number for 24 hours. Four hours means it retries
the live source sooner.

**Q13.3 — Why is live price/news deliberately not cached?**
Staleness tolerance for live market data is a product decision, not a bug fix.
Caching a price for even a minute changes what the product *is*. The audit
explicitly records that this was considered and deliberately left alone.

**Q13.4 — What's the biggest performance win in the codebase?**
The 5-way parallel fan-out: wall-clock is the slowest worker rather than the sum
of five. Second is batching all article sentiment into a single LLM call. Third
is the local search catalog — sub-10ms typeahead with no network on the hot path.

**Q13.5 — Where does the time actually go?**
Overwhelmingly the two LLM calls on free-tier models (which queue), then
yfinance's `.info` and 3y history, then the peer worker (5 concurrent market
bundles). Everything else is noise.

**Q13.6 — How would you speed it up further?**
Cache market bundles per ticker with a short TTL (60–120s), which would make the
peer worker nearly free for popular sectors; stream the brief section-by-section
over SSE so the user sees price data while news is still resolving; and move the
peer worker's market fetches to a shared bulk yfinance download call.

---

## 14. Data modelling & type safety

**Q14.1 — Walk me through the schema hierarchy.**
`ResearchBrief` composes `PriceAction`, `Fundamentals`, `CalcMetrics`,
`ValuationContext` (which composes `PeBand` + `SectorPe`), `PeerComparison`
(rows of `PeerRow`), `Shareholding`, lists of `NewsItem` / `FilingHighlight` /
`RiskFlag` / `SourceRef` / `PricePoint`, plus `analyst_summary`, `data_gaps`,
`critic_passed`, `critic_notes`, `compliance_log` and `metadata`.
`CompareBrief` wraps two `ResearchBrief`s plus a metrics table and narrative.
`ResearchJobResponse` wraps either one plus status, mode, model, error fields
and suggestions.

**Q14.2 — What's the shared "claim block" pattern?**
Every claim-bearing block carries `source_ids: list[str]`, `confidence:
Optional[ConfidenceLevel]` and `confidence_reason: Optional[str]`. That
consistency is what lets the critic's `_check_citations` and the confidence
pass iterate generically, and lets the frontend render one `<ConfidenceBadge>`
and one `<Cite>` component everywhere.

**Q14.3 — Why is `insufficient_data` in the `SentimentLabel` enum?**
So the *schema* forbids a directional label without corroboration, rather than
relying on a convention. It's a fourth first-class state, distinct from
`neutral` — "we don't have enough evidence" is not the same claim as "the news
is neutral", and the UI styles them differently (warn vs muted).

**Q14.4 — Where is Pydantic actually enforced, and what's the gap?**
At exactly two boundaries: `ResearchBrief.model_validate` in the runner, and
`ResearchJobResponse.model_validate` on every job-store round-trip. Everywhere
upstream — every worker, the synthesizer, the critic, all retry passes — the data
is `dict[str, Any]` inside a `TypedDict`, which is a compile-time hint with zero
runtime enforcement. Practically: a key typo in a worker (`bundle["nse__url"]`)
wouldn't raise anywhere; it would surface as a `None` at the one validation
point, indistinguishable from "genuinely unavailable". I'd state that plainly
rather than overclaim "Pydantic enforced end-to-end" — it's documented as audit
finding #4.

**Q14.5 — Why `TypedDict` for graph state instead of a Pydantic model?**
It's what LangGraph's state model is built around — `Annotated` reducers on
`TypedDict` fields are the framework's mechanism. Validating on every node would
also be expensive when the state carries 750 daily closes.

**Q14.6 — Why does `PeBand` have both `available` and `partial_history`?**
They answer different questions. `available` = "could we compute a band at all"
(needs ≥1 complete 4-quarter window). `partial_history` = "we computed one, but
from fewer than 8 quarters, so treat it as directional". Collapsing them would
force a choice between hiding a usable-but-thin band and presenting it as if it
were complete.

**Q14.7 — How does the frontend stay in sync with these types?**
`frontend/src/lib/api.ts` mirrors every schema as a TypeScript interface,
including the shared `ConfidenceFields` interface that the claim blocks extend
— the same composition pattern as the Pydantic side. They're hand-maintained;
generating them from the OpenAPI schema would be the obvious improvement, and
`npm run lint` (`tsc --noEmit`) catches drift at the usage sites.

---

## 15. Testing & evaluation

**Q15.1 — What's your test strategy?**
Test the pure logic exhaustively and the I/O boundaries not at all — because
the architecture put all the load-bearing logic in pure functions. 136 backend
tests run in under four seconds with zero network. Breakdown:

| Area | Tests |
|---|---|
| `test_stock_search.py` | 27 |
| `test_model_catalog.py` | 20 |
| `test_confidence.py` | 10 |
| `test_calc.py`, `test_ticker_resolve.py` | 9 each |
| `test_intent.py` | 8 |
| `test_compliance_filter.py`, `test_text_quality.py` | 7 each |
| `test_valuation.py`, `test_peer_data.py`, `test_sector_pe.py`, `test_critic_planner.py` | 5 each |
| `test_dedup.py`, `test_shareholding.py`, `test_ticker_helpers.py` | 4 each |
| `test_news_rss.py` | 3 |
| `test_compare.py` | 2 |
| `test_market_worker_degrades.py`, `test_news_worker_corroboration.py` | 1 each |

Frontend: 55 vitest tests across 8 files (StockSearchInput 19, ModelPicker 14,
ResearchStudio model wiring 6, ThemeToggle 4, TrendIndicator 4, PeerTable 4,
ConfidenceBadge 3, DataGapBanner 3).

**Q15.2 — Which tests are the most important, and why?**
`test_calc.py` and `test_valuation.py`, because `tools/code_exec.py` is the one
place the entire architecture's central claim — "no LLM does math" — actually
lives. It being untested was the most surprising gap in the original repo:
pure, deterministic, trivially testable, and load-bearing for the whole design
story. Then `test_confidence.py` and `test_compliance_filter.py`, for the same
reason on the trust side.

**Q15.3 — What's your biggest testing gap?**
No full graph integration test with mocked tools. Nothing currently proves the
*wiring* — that a critic failure re-runs only the targeted worker through the
real `StateGraph`. The node functions are tested directly with hand-built dicts,
which is right for `planner_node` and `critic_node` but doesn't cover the edges.
It's follow-up #1 in both README and ARCHITECTURE, and I'd name it before an
interviewer finds it.

**Q15.4 — How do you test code that hits the network?**
By making the network boundary a single injectable function. `test_shareholding.py`
and `test_sector_pe.py` patch the module-level fetch helper; `test_peer_data.py`
patches `fetch_market_bundle`; `test_market_worker_degrades.py` makes it raise
`MarketDataUnavailable` and asserts the worker still returns a well-formed
degraded bundle with `completed_workers: ["market"]`.

**Q15.4b — How do you unit-test a *provider outage* without a network?**
Three tests in `test_ticker_resolve.py`, and they're a good example of testing a
failure taxonomy rather than a happy path. Each patches at a different depth to
simulate a distinct upstream behaviour:
- `_validate` patched to return `{}` → asserts the offline catalog fallback wins
  and `RELIANCE` still resolves to `RELIANCE.NS`.
- `yf.Ticker` patched to **raise** → asserts `ProviderUnavailableError`.
- `yf.Ticker` patched to return an **empty `info`** → asserts
  `TickerResolutionError`, i.e. a healthy provider saying "no such symbol" stays
  distinguishable from a blocked one.

The last one is the test that matters most, because it's the one that fails if
someone later "simplifies" the outage detection into "did anything resolve?".
Both branches are asserted, so the distinction can't silently collapse.

**Q15.5 — What does the eval harness measure?**
`eval/run_eval.py` runs the real pipeline over a frozen ticker testset and scores
~16 checks per ticker, then reports `overall_factual_accuracy` plus a **separately
reported** `data_source_coverage_pct`.

**Q15.6 — Why report coverage separately from accuracy?**
Because an honest "unavailable" is a **pass** under the graceful-degradation
contract — otherwise the metric would punish correct behaviour during an
upstream outage. But if they were the same number, you could game accuracy by
hiding gaps. So `degraded_ok()` passes a section that either carries real data or
says `available:false` *with a reason*, and coverage separately tracks how often
each source actually resolved live. A quietly-degrading source shows up as
falling coverage rather than silently passing.

**Q15.7 — What specific behaviours does the eval assert?**
Price present and cited; brief P/E within tolerance of live yfinance; derived P/E
internally consistent within 0.05; summary and sources non-empty; each of the
four optional sections honest-or-real; sector P/E always carries an `as_of` date;
every calc block and every news item carries a confidence tag; **no directional
sentiment survives with <2 sources**; no banned advice phrase reaches the
summary; and the peer table always contains its subject row.

**Q15.8 — Is the eval in CI?**
No — it hits live yfinance and a real LLM, so it's excluded from `pytest`'s
testpaths and run manually via `make eval`. It has no mock mode, which is a
deliberate scope call (it's an eval harness, not a unit test) and is documented
as such.

**Q15.9 — What would you add to CI?**
`pytest -q` + `vitest run` + `tsc --noEmit` on every PR (all three are fast and
network-free), plus a nightly eval run against the live sources so coverage
regressions surface as a trend rather than a surprise.

---

## 16. Frontend architecture

**Q16.1 — Why React + Vite + TypeScript + Tailwind, and no state library?**
Vite for instant HMR and a trivial build; TypeScript because the API contract is
large and structured and `tsc --noEmit` catches drift; Tailwind because the whole
palette is CSS variables and utility classes compose against them directly. No
Redux/Zustand because there is genuinely one piece of server state (the current
job) and a handful of local UI states — the audit explicitly notes this as
"appropriately lightweight, not over-engineered". React Query would be a
reasonable upgrade for the poll loop specifically.

**Q16.2 — Describe the component tree.**
```
App  (header, hero, footer, provider badge, ThemeToggle)
└── ResearchStudio                      ← owns all job state
    ├── ModelPicker                     ← LLM selection, localStorage-backed
    ├── StockSearchInput ×1 or ×2       ← single vs compare mode
    ├── PipelineStatus                  ← 11-step tracker
    ├── BriefSkeleton                   ← progressive loading
    └── ErrorBoundary
        ├── BriefView                   ← single-ticker brief
        │   ├── DataGapBanner
        │   ├── ValuationPanel          ← P/E band gauge + sector P/E
        │   ├── PerformancePanel        ← horizon toggle + PriceChart (inline SVG)
        │   ├── ShareholdingCard
        │   ├── PeerTable               ← sortable
        │   ├── ConfidenceBadge / Cite / TrendIndicator (leaf primitives)
        │   └── UnavailableNotice
        └── CompareView                 ← metrics table + narrative + 2× BriefView
```

**Q16.3 — Where does state live?**
`ResearchStudio` owns everything job-related: `mode`, `query`/`queryA`/`queryB`,
`job`, `error`, `submitting`, `model`, `catalog`, `comparePair`, `openSingle`.
Children are presentational or own only their own interaction state
(`StockSearchInput`'s suggestion list, `PeerTable`'s sort key,
`PerformancePanel`'s selected horizon). One owner, explicit props — no context,
because nothing needs to cross more than two levels.

**Q16.4 — Explain the polling implementation.**
```js
useEffect(() => {
  if (!job || job.status === "completed" || job.status === "failed") return;
  const id = setInterval(async () => {
    if (inFlight) return;                       // never stack requests
    if (Date.now() - startedAt > MAX_POLL_MS) { clearInterval(id); ... }
    inFlight = true;
    try { setJob(await getResearch(job.job_id)); }
    finally { inFlight = false; }
  }, 2000);
  return () => clearInterval(id);
}, [job?.job_id, job?.status]);
```
Four things to point at: the early return stops polling on terminal states; the
`inFlight` guard prevents request pile-up when the server is slow; the 10-minute
ceiling stops a runaway loop even if the backend never answers; and the cleanup
clears the interval on unmount or dependency change.

**Q16.5 — Why does the effect depend on `job?.status` as well as `job?.job_id`?**
So the interval is torn down the moment the status becomes terminal. Depending on
`job` itself would re-create the interval on every poll response — a new timer
every 2 seconds.

**Q16.6 — Why is the search debounced at 220ms with an AbortController?**
Debounce so a burst of typing produces one request rather than one per keystroke;
`AbortController` so a superseded request is cancelled rather than racing the
newer one and overwriting fresher results. Both are torn down in the effect's
cleanup, which is what makes the cancellation correct rather than best-effort.

**Q16.7 — Why does `searchStocks` return an empty result on failure instead of throwing?**
Because it runs on every keystroke. A flaky suggestion call must never block the
user from submitting what they typed — the free-text value stays authoritative
and submittable regardless of what the typeahead is doing.

**Q16.8 — How does the frontend handle a failed job?**
`ERROR_MESSAGES` maps `error_code` to a human sentence, with a fallback to the
raw `error` string for an unknown code. For `ticker_not_found` — and *only* that
code — it also renders the `suggestions` the backend attached as clickable "did
you mean" chips showing the match percentage; clicking one immediately reruns the
research. So the failure state is a recovery affordance rather than a dead end:
```tsx
job.status === "failed" && job.error_code === "ticker_not_found" ? job.suggestions || [] : []
```

**Q16.8b — Why is the suggestion gate on the error code rather than just "are there suggestions"?**
Because chips are a *claim* that retyping will help. Under
`data_provider_unavailable` the query was fine — the provider was refusing — so
offering alternative spellings would be actively misleading, sending the user to
"fix" something that isn't broken. Its copy says the opposite out loud: "Nothing's
wrong with what you typed — try again shortly." The backend cooperates by
attaching no suggestions to that code, so this is belt-and-braces: the UI
wouldn't render them even if a future backend change started sending them.

**Q16.8c — The `error_code` type is a TS union. What does that buy you?**
`error_code?: "ticker_not_found" | "data_provider_unavailable" | "timeout" |
"internal_error" | null`. When the backend added the fourth code, `tsc --noEmit`
is what points at every place that switches on it. It's the hand-mirroring
weakness from Q14.7 seen from the useful side: the mirror is manual, but once
updated the compiler finds the call sites. Generating it from the OpenAPI schema
would make the update itself automatic too.

**Q16.9 — Why do the example chips fill the box instead of running a search?**
A job takes minutes, so starting one must always be an explicit choice. Clicking
"maggi" fills the box and shows the ranked matches; picking a match is what
starts the job. The chips double as a demo of what the search accepts: a symbol,
a company, a partial, a brand, a sector, an approximate spelling.

**Q16.10 — How is the API base URL configured?**
`import.meta.env.VITE_API_URL || "http://localhost:8000"` — Vite's build-time env
substitution, set per environment (docker-compose passes it to the frontend
service).

---

## 17. Frontend components, one by one

**Q17.1 — `StockSearchInput`: what's the hardest part?**
Deciding *when not to open*. The list must never open by itself: a prefilled
value, a value the box wrote itself when a suggestion was clicked, or a remount
when switching modes are all **not questions**, so they aren't answered with a
dropdown. Four refs encode that:
- `requested` — nothing is searched until the user types or the parent bumps
  `openSignal`.
- `selfWritten` — the value this box wrote by applying a suggestion; durable, not
  one-shot, because the effect re-runs later when a job starts and finishes.
- `lastOpenSignal` — captured at mount, so a remount with an already-non-zero
  signal isn't treated as a fresh request.
- `lastQueried` — `"${query}|${openSignal}"`, so an effect re-run for an
  unrelated reason (e.g. `disabled` flipping) doesn't re-ask the same question
  and re-open the list over a finished brief.

**Q17.2 — Why is the results panel in normal document flow instead of an absolute overlay?**
So it cannot overlap the example chips or the disclaimer, cannot escape the card,
and needs no `z-index` at all — the card simply grows and the content below moves
down. The previous version floated it, and on a stale stylesheet it rendered
transparent and printed straight over the content underneath. A long list scrolls
inside its own panel.

**Q17.3 — Why does `ModelPicker` use an absolute panel then?**
Different constraint. It sits on a toolbar row, where pushing content down would
reflow the entire form on every open. So it's absolutely positioned, anchored to
a `relative` wrapper with an explicit `z-40`. The reasoning is a comment on both
components so the inconsistency reads as a decision.

**Q17.4 — What accessibility work is in the combobox?**
`role="combobox"` with `aria-expanded`, `aria-controls`, `aria-autocomplete="list"`,
`aria-busy` during load, and `aria-activedescendant` pointing at the highlighted
option id. The list is `role="listbox"` with `role="option"` + `aria-selected`
children. Keyboard: ArrowUp/Down wrap around, Enter selects (with
`preventDefault` so it doesn't also submit the form with the old text), Tab
selects, Escape closes. A visually-hidden `role="status" aria-live="polite"`
region announces "N matches for X" for screen readers. And
`row?.scrollIntoView?.()` is an optional call — a browser nicety, not something
to crash on in jsdom.

**Q17.5 — Why `preventDefault` on Enter?**
The input is inside a `<form>`. Without it, choosing a suggestion with Enter
would *also* submit the form — with the old text, since `setState` hasn't
flushed. Same reasoning in `ModelPicker`: picking a model must never start a
research job.

**Q17.6 — Why do the single and compare inputs have explicit `key` props?**
Without them React reconciles the single-mode and compare-mode boxes as the same
element, so switching tabs inherits the previous box's suggestion list and shows
a list nobody opened. Stable keys per mode force a remount.

**Q17.7 — How does `ModelPicker` persist the choice, and why store `null` for the default?**
`localStorage` under `truvest:model`, wrapped in try/catch because private mode
can throw and a preference isn't worth an exception. Picking the server default
stores `null` rather than today's default id — so the choice keeps *tracking* the
server's default if the operator changes it, instead of freezing a value forever.
On load, a stored id that's no longer in the catalog (free models get retired) is
dropped rather than sent to a backend that would 400 it.

**Q17.8 — Why does `ModelPicker` group by vendor but navigate flat?**
Grouping makes a dozen NVIDIA variants read as one family rather than a wall.
But visual grouping must not change what ArrowDown moves through, so a flattened
`flat` array drives keyboard navigation while `groups` drives rendering.

**Q17.9 — What does `PipelineStatus` do and what's the limitation?**
Renders 11 named steps, marking each done/active/pending from the job's
`progress` string via `guessStep`. The honest limitation: five workers run in
*parallel*, so a linear tracker is an approximation — any `*_done` message means
that phase is underway, and `workers_joined` means all I/O finished. It's
flex-wrap rather than an 11-column grid because fixed columns squeezed
"Synthesize" until it overflowed its own chip.

**Q17.10 — Why an `ErrorBoundary`, and what does it wrap?**
Audit #6.1: a render-time exception anywhere in `BriefView` blanked the whole
page with no recovery path. The boundary wraps only the brief/compare render, so
the search form and the pipeline tracker survive, and it offers a "try rendering
again" button that resets its own state. Its message is precise: "the underlying
data was fetched successfully — this is a display bug, not a data problem."

**Q17.11 — Why a class component?**
`getDerivedStateFromError` / `componentDidCatch` have no hooks equivalent —
error boundaries are the one thing React still requires a class for.

**Q17.12 — How is the price chart drawn?**
Hand-written inline SVG in `BriefView` — no charting library. Min/max over the
window, linear scale functions for x and y, a `<polyline>` for the line, a
`<polygon>` at 8% opacity for the area fill, and a `<circle>` on the last point.
Stroke is `currentColor` so it inherits `text-accent` or `text-danger` from the
parent — a hardcoded hex would only read correctly on one theme. It's
`role="img"` with an `aria-label`, and returns `null` under 2 points.

**Q17.13 — Why no charting library?**
One chart, one line, ~30 lines of SVG, versus 50–200KB of Recharts/Chart.js and
a theming integration. The trade-off flips the moment there's a second chart
type or interactivity — and I'd say that rather than pretending libraries are
bad.

**Q17.14 — How does the performance horizon toggle work?**
Six periods (1W/1M/3M/6M/1Y/3Y). Each button is disabled when
`price_action[field]` is null — you can't select a horizon there's no data for.
Selecting one filters `price_history` to that calendar window and falls back to
the full history if the window has fewer than 2 points.

**Q17.15 — How does `PeerTable` sort?**
Local `sortKey` + `asc` state, default `market_cap` descending. Strings use
`localeCompare`; numbers coerce `null` to `-Infinity` so missing values sink to
the bottom in either direction. The subject row is highlighted with a filled
background, bold text, and a leading `●`. The table has `min-w-[560px]` inside an
`overflow-x-auto` wrapper so it scrolls itself rather than the page.

**Q17.16 — What's `TrendIndicator` and why does it matter?**
Audit #6.3: direction was color-only. Now every percentage change carries an
icon (`ArrowUpRight` / `ArrowDownRight` / `Minus`) alongside the color, so it
still reads for color-blind users and in a black-and-white printout of a
research brief. It also has a flat band (`|value| < 0.005`) so a rounding-noise
value doesn't get a misleading arrow.

**Q17.17 — Why do skeletons exist per-section?**
Audit #6.2: while a job ran, only the step tracker rendered and the brief area was
simply absent — one blocking wait rather than progressive reveal. `BriefSkeleton`
now shows per-section placeholders so the page reads as a live system working.

**Q17.18 — How are numbers formatted?**
`Intl.NumberFormat("en-IN", ...)` — the Indian locale, which groups as
1,23,45,678 (lakh/crore), not 123,456,78. Currency style with the brief's own
currency code, and `notation: "compact"` above ₹1 crore so market caps read as
"₹19.8L Cr" instead of a 13-digit number. Percentages get an explicit `+` sign
for positives.

**Q17.19 — What is `<Cite>`?**
A leaf component that turns `source_ids` into bracketed reference links,
stripping the `src-` prefix for display and linking to the source URL when the
matching `SourceRef` has one. It's rendered next to every claim block heading —
that's what makes "every claim is source-linked" visible rather than a README
claim.

---

## 18. Theming, design system & accessibility

**Q18.1 — How does theming work?**
One set of CSS custom properties in `index.css` as bare `R G B` triples, surfaced
to Tailwind as tokens: `paper / surface / elevated / line / ink / secondary /
muted / accent / success / warn / danger / primary / onprimary`. Dark is
`:root`; light is the `[data-theme="light"]` opt-in override. No component
hardcodes a colour, so the whole product re-skins from that one block.

**Q18.2 — Why bare `R G B` triples instead of `rgb(...)` or hex?**
So Tailwind can compose them with an alpha channel:
`token(name, fallback) => rgb(var(--x, fallback) / <alpha-value>)`. That's what
makes every existing `text-ink/60`, `bg-accent/[0.12]` utility in the codebase
keep working across both themes without a single hardcoded colour.

**Q18.3 — Why is dark the default rather than light?**
So a missing or late-loading theme attribute falls back to dark rather than
flashing a white page. It's the failure-safe direction.

**Q18.4 — How is the flash of wrong theme prevented?**
An inline script in `index.html` reads `localStorage` and stamps
`<html data-theme>` **before first paint**, so React never re-decides the initial
value — `readTheme()` just reads what the bootstrap already applied, which keeps
them in sync by construction.

**Q18.5 — What's the "stale stylesheet" failure and how is it guarded?**
The single worst bug hit during development: a browser holding an outdated
stylesheet renders a dark page wearing light components, with unreadable text
(Tailwind config changes need a dev-server restart, not just a reload). Two
guards: (1) the pre-paint background is a plain `<style>` rule rather than a
scripted inline style, so any stylesheet that loads simply overrides it; (2)
every token carries its **dark** value as a CSS fallback in the Tailwind config,
so a missing variable resolves to a self-consistent dark palette rather than
collapsing to transparent. Plus `warnIfThemeTokensMissing()` at boot, which
computes the perceived lightness of `--bg-surface` and console-warns if it
disagrees with the active `data-theme` — so a stale bundle degrades to an
out-of-date *look*, never an unreadable page, and the console says so.

**Q18.6 — What accessibility work is in the app?**
Contrast is verified rather than assumed — every rendered text node in both
themes clears WCAG AA for its size, and the `muted` tier is its own token
precisely because an opacity-mixed grey measured 3.8–4.5:1 on light. Beyond
that: full combobox and listbox ARIA, `role="switch"` with `aria-checked` on the
theme toggle, `aria-pressed` on the mode segments, non-color-only trend
direction, live regions for async result counts, disabled states on unavailable
horizon buttons, and `aria-label`/`role="img"` on the chart.

**Q18.7 — Tell me about a Tailwind gotcha you hit.**
Twice: `bg-accent/12` and `bg-ink/8` compiled to **no rule at all**, because
Tailwind only emits bare slash opacities that exist in its own scale, and 8 and
12 aren't in it. Result: confidence pills rendered as bare text with no fill, and
every skeleton rendered as blank space — a loading state that showed nothing was
loading. Fix is bracket notation: `bg-accent/[0.12]`. Both are documented as
comments where they bit.

**Q18.8 — Why is the compare grid `min-w-0` on each item?**
Grid items default to `min-width: auto`, so the peer table's `min-w-[560px]`
forced the column wider than the viewport and the whole **page** scrolled
sideways on mobile instead of just the table scrolling in place.

---

## 19. DevOps, config & deployment

**Q19.1 — How is configuration handled?**
`pydantic-settings` `BaseSettings` with `env_file=("../.env", ".env")` — so
running `uvicorn` from `backend/` still picks up the project-root `.env` — and
`extra="ignore"` so frontend-only vars in the same file don't crash startup.
Every setting is a typed field with a default, and `.env.example` documents all
of them. `cors_origins_list` is a computed property splitting the comma-separated
string.

**Q19.2 — Walk me through docker-compose.**
Four services: `redis` (7-alpine, with a `redis-cli ping` healthcheck),
`backend` (built from `backend/Dockerfile`, `depends_on` redis with
`condition: service_healthy`, mounts the source for dev reload), `frontend`
(built image serving the static Vite build via nginx on port 80 → 3000), and a
commented-out `ollama` service for fully-local inference. Redis has a named
volume for persistence.

**Q19.3 — Why is Redis optional?**
Because a reviewer cloning the repo should be able to run it with two commands.
The in-memory fallback is real, not a stub — jobs and cache both work, they just
don't survive a restart or span multiple workers. `/health` reports which backend
is live so the degradation is never invisible.

**Q19.4 — What does the Makefile give you?**
`make install`, `make infra` (redis only), `make backend`, `make frontend`,
`make test`, `make eval` — the whole lifecycle without memorising venv activation
paths.

**Q19.5 — What would you change to run this in production?**
Concretely: multiple uvicorn workers behind a proxy (which *requires* Redis, since
the in-memory job store is per-process); a LangGraph checkpointer for durable
resume; a real task queue (Celery/RQ) instead of `BackgroundTasks`, so a deploy
doesn't kill in-flight jobs; rate limiting on `/research`; per-user auth and
quota, since jobs cost LLM tokens; structured JSON logging with a request/job id
correlation; and licensed market-data feeds replacing the two nsepython modules.

**Q19.6 — What broke when you actually deployed it? (Very likely to be asked.)**
The single biggest surprise: **the code was environment-dependent in a way nothing
local could reveal.** Yahoo Finance blocks shared datacenter IPs, so ticker
resolution — step one of the pipeline, before any worker runs — failed for *every
query* on a hosted box while passing 100% on a laptop. Not a config problem, not a
missing key; the same bytes behaving differently because of where they ran from.
Full write-up in Q10.17. Three lessons I'd actually name:
1. **Free unofficial endpoints are a hosting dependency, not just a data
   dependency.** yfinance and `nsepython` both work from a residential IP and both
   are at the mercy of the provider's WAF from anywhere else. That belongs in the
   deployment risk list, not the data-source list.
2. **Every failure needs an owner in its error code.** `ticker_not_found` blamed
   the user for an infrastructure failure. That's why there are now four codes
   split by *who can fix it* (Q8.3).
3. **A `debug`-level log on a failure path is a log that doesn't exist**, because
   production doesn't run at debug (Q10.22).

**Q19.7 — What would you check first if a deployed job failed for every user?**
`GET /api/v1/health` first — it reports Redis reachability, the active job-store
backend, the LLM provider and the server's default model, which clears or
confirms three of the four subsystems in one request. Then the logs for
`validate … failed:` warnings, which now name the exception type, so a 429 (rate
limit / IP block) is distinguishable from DNS or TLS at a glance. Then the job
record's `error_code`, which localises the failure to a stage: resolution
(`ticker_not_found` / `data_provider_unavailable`), the pipeline (`timeout`), or
my own code (`internal_error`).

**Q19.8 — Does `/health` tell you enough?**
Not for this class of failure, and that's a real gap I'd name. It checks Redis but
not the *data* providers, so a Yahoo block is invisible to it — the app reports
`status: ok` while being unable to resolve a single ticker. The obvious extension
is a cached, cheap reachability probe per upstream (Yahoo, NSE, OpenRouter) with
its last-success timestamp, so "healthy" means "can actually do the job" rather
than "the process is up".

**Q19.9 — What's your logging strategy?**
Module-level `logging.getLogger(__name__)` everywhere, configured once in
`core/logging.py` at lifespan start. Levels are used deliberately: `debug` for
expected misses (a peer without data), `info` for degradations worth knowing
about (a feed unreachable), `warning` for a fallback firing, `exception` for
genuine bugs. Notably, error text never reaches the user-facing brief — failures
become either an honest "unavailable" section or a deterministic fallback.

---

## 20. Bugs found & debugging war stories

These are the highest-value interview material — pick two or three and tell them
as stories. All are documented in `docs/AUDIT.md` with severity ratings.

**Q20.1 — The yfinance crash (High).**
`fetch_market_bundle` had no try/except around `yf.Ticker(t).history()`. Every
other worker's I/O was wrapped; market data wasn't. One 429 (observed live from
a rate-limited sandbox) raised out of the worker, out of the node, out of
`graph.stream()`, and was only caught by the blanket handler — **the entire job
failed, discarding news and filings work that had already succeeded**. Fix: a
typed `MarketDataUnavailable`, caught by the worker, degraded to a shaped
`unavailable` bundle. Test: `test_market_worker_degrades.py`.

**Q20.2 — Duplicate sources across retries (High).**
`sources` uses `operator.add`, and source ids are deterministic per
(ticker, index). So when the critic failed and the news worker retried, the
retried sources were *appended* alongside the failed attempt's — the same id
appearing twice with different titles/URLs, and the UI rendered both as
contradictory citations under one reference number. Fix: dedupe by id in the
synthesizer, keeping the last occurrence. The interesting part is *why* it was
hard to see: it only manifests on a retry, and only in the rendered output.

**Q20.3 — Unreachable retry target (Medium-High).**
The critic never iterated `filings`, so `"filings"` was literally unreachable as
a `failed_subtask` — no code path could ever ask the planner to retry that
worker. Masked because the filings worker always sets `source_ids`. Found by
reading the critic against the planner's contract rather than by a failing test.

**Q20.4 — The unrunnable eval (High impact, small cause).**
`_clean_query` splits on dots, so "TCS.NS" became "TCS NS". The re-join lived
inside `if " " not in cleaned:` — unreachable by construction for a string
containing a space. So every `*.NS`/`*.BO` query failed to resolve, which meant
the eval harness, whose testset is entirely `.NS` tickers, **had never been
runnable**. One misplaced block, and the project's headline metric was fiction.

**Q20.5 — Garbage that wasn't empty (High).**
`"? = is... is, isALG(?.. is?.....com.... ...………iqué………"` — real output from a
free model, written verbatim into a brief, because every fallback guarded on
"is the text empty?" rather than "is this actually prose?". Fix:
`core/text_quality.py`, with the captured string as a test case.

**Q20.6 — The music model in the equity picker.**
Google's Lyria models are zero-priced and declare output modalities
`text+image->text+audio`. A "text is in the outputs" filter let a music generator
into the model picker. Fix: the check is `set(outputs) - {"text"}` — outputs must
be a *subset* of `{text}`.

**Q20.7 — "FEVICOL" is not an EV company.**
The brand-keyword matcher used plain `in`, so the keyword "EV" matched inside
"FEVICOL" and pulled an adhesives company into an electric-vehicle search. Fix:
whole-word regex containment.

**Q20.8 — Invisible loading states.**
`bg-ink/8` compiled to no CSS rule (8 isn't in Tailwind's opacity scale), so
every skeleton rendered as blank space — a loading indicator that indicated
nothing. Same class of bug made the confidence pills render as unfilled text.

**Q20.9 — The page that scrolled sideways.**
Compare mode scrolled the entire page horizontally on mobile: grid items default
to `min-width: auto`, so the peer table's `min-w-[560px]` blew out the column
instead of scrolling inside its own container.

**Q20.10 — How did you find these?**
A structured audit: a full read of every file in scope (not a sample),
cross-checked against how LangGraph merges partial state — which is what surfaced
the `operator.add` duplication class of bug — plus a live network check from the
environment, which is how I learned that nseindia.com is unreachable from a plain
client and that Business Standard 403s a default User-Agent. Several of these are
only findable by reading the *contract between* two modules, not either one alone.

**Q20.11 — The deploy where every ticker was "not found" (High).**
The best story in the list, because it's the only bug that **could not be
reproduced locally by construction**. Yahoo blocks shared datacenter IP ranges,
so on a hosted box `_validate` failed for every candidate and the very first
pipeline stage reported `ticker_not_found` — telling users that *RELIANCE* wasn't
a live NSE symbol. Everything downstream was fine and never got to run.

What makes it worth telling: the first instinct is "add a retry". The actual
diagnosis was that the code was **asking the wrong question**. It treated a live
quote lookup as the authority on whether a listing exists, when the bundled NSE
universe — built from NSE's own `EQUITY_L.csv` — is the better authority and was
sitting right there. So the fix wasn't resilience plumbing, it was correcting
which source owns which fact: the probe is enrichment, the catalog is truth, and
missing quotes degrade the market section rather than the whole job. Then, for the
case the catalog genuinely can't answer, a typed `ProviderUnavailableError` so the
message stops blaming the user. Three tests pin the outage-vs-typo boundary.

**Q20.12 — What class of bug is that, and how would you catch it earlier?**
It's an **environment-dependent correctness bug** — the same code, correct in one
network position and wrong in another. Unit tests can't see it (they mock the
network) and local runs can't see it (the network is friendly). Earlier detection
means testing from the target environment: a post-deploy smoke check that resolves
a known ticker and fails the deploy loudly, plus per-upstream health probes
(Q19.8). The general lesson is that "works on my machine" has a specific,
predictable failure mode for anything hitting an unofficial third-party endpoint,
and the mitigation is to name that endpoint a *hosting* dependency up front.

---

## 21. Trade-offs, scale & "what would you change"

**Q21.1 — What are the honest weaknesses of this project?**
1. No end-to-end graph integration test — the wiring is unproven by tests.
2. Two data sources are unofficial NSE endpoints; they can break without notice.
3. Pydantic only validates at two boundaries; the graph interior is untyped at
   runtime.
4. `BackgroundTasks` means in-flight jobs die on deploy.
5. Job-store `update_job` is read-modify-write with no locking.
6. A timed-out job's worker thread isn't actually killed.
7. Peer groups cover 57 tickers, not the full universe.
8. TypeScript types are hand-mirrored rather than generated from OpenAPI.
9. Yahoo blocks shared datacenter IPs, so a hosted deploy runs with degraded
   market data unless the egress IP is clean — mitigated (catalog fallback +
   a distinct error code), not solved (Q10.17–Q10.24).
10. `/health` checks Redis but no data provider, so it reports `ok` during an
    upstream block (Q19.8).
11. The catalog fallback can resolve a symbol delisted since the last catalog
    rebuild; there's no scheduled rebuild job yet (Q10.23).

**Q21.2 — Scale it to 10,000 users a day.**
Rate-limit and authenticate `/research`; replace `BackgroundTasks` with a real
queue and dedicated workers; make Redis mandatory (multi-process job state);
add a per-ticker brief cache with a short TTL so popular names serve instantly;
batch and cache market bundles across concurrent jobs; move to a licensed data
vendor with an SLA; and put the LLM calls behind a per-user token budget, since
that's the actual unit cost.

**Q21.3 — What would you build next?**
Follow-ups, in order: (1) the graph integration test with mocked tools, (2) a
market-data path that survives a hosted deploy — per-upstream health probes plus a
post-deploy smoke check, since that's the one open issue that makes the product
worse for *every* user rather than in one section, (3) a LangGraph Redis
checkpointer for durable resume, (4) SSE progress to replace polling, (5) NSE's
corporate-announcements API for real filings instead of Tavily snippets,
(6) FII/DII shareholding v2 from monthly NSDL data.

**Q21.4 — If you rewrote it, what would you do differently?**
Generate the TypeScript client from the OpenAPI schema instead of hand-mirroring
it. Write the graph integration test *first*, since it's the piece that would
have caught the retry-path bugs. And introduce a thin `Result`-shaped wrapper
(`{available, reason, value}`) at the tool boundary from day one instead of
arriving at it feature-by-feature — I converged on it for four sections, and it
should have been the pattern everywhere from the start.

**Q21.5 — Why not use an off-the-shelf agent framework like CrewAI/AutoGen?**
Because the value here is the *determinism*: a fixed topology, targeted retries,
and code-enforced post-conditions. Role-playing agent frameworks optimise for
emergent collaboration, which is exactly the property you don't want when the
output has to be evaluable and reproducible.

**Q21.6 — Isn't the critic just an expensive linter?**
Somewhat, and that's the point — it's deliberately deterministic rather than an
LLM judge. Its value is that it can *route*: each issue names the worker that
caused it, so a failure re-runs one worker instead of the whole job. A linter
tells you something's wrong; this tells the planner what to do about it.

**Q21.7 — Where would this system still lie to a user?**
Honest answer: the sentiment label. It comes from an LLM reading headlines, and
the corroboration rule bounds the *confidence* but not the *correctness* of the
direction. The mitigations are that it's tagged Medium at best, the rationale is
shown, the corroboration count is printed under every item, and it never feeds
any number in the brief. It's the section I'd caveat first.

---

## 22. Rapid-fire one-liners

| Question | Answer |
|---|---|
| Nodes in the graph? | 12 |
| Workers in parallel? | 5 |
| LLM calls per job? | 2 (+1 for compare) |
| Retry cap? | 2 → critic runs at most 3× |
| Job timeout? | 420s |
| Poll interval / ceiling? | 2s / 10 min |
| Search debounce? | 220ms |
| Confidence levels? | high / medium / low (+ `None` when data was unavailable) |
| Sentiment labels? | bullish / bearish / neutral / insufficient_data |
| Min sources for a directional call? | 2 distinct outlets |
| Title-similarity threshold for dedup? | 0.6 (`difflib.SequenceMatcher`) |
| P/E mismatch tolerance? | 2.5 (critic) / 1.0 (calc note) |
| News freshness window? | 45 days |
| Quarters for a full P/E band? | 8 (4 minimum to compute anything) |
| Search confidence thresholds? | ≥0.85 high, ≥0.62 medium |
| Yahoo layer trigger / LLM layer trigger? | top score < 0.90 / < 0.55 and ≥2 words |
| Catalog size? | 2,378 symbols + 161 curated entries |
| Peer group coverage? | 57 tickers, 12 sector→index mappings |
| Max peers per table? | 4 + the subject |
| Price-history downsample target? | ≤240 points from ~750 |
| Backend / frontend tests? | 136 / 55 |
| Compliance rules? | 12 regex rewrite rules |
| Error codes? | ticker_not_found, data_provider_unavailable, timeout, internal_error |
| Which error code carries suggestions? | `ticker_not_found` only |
| Provider-outage test? | every attempt dies on the wire → `ProviderUnavailableError` |
| Resolution fallback order? | alias map → catalog (≥0.85) → `X.NS`/`X.BO` → Yahoo search → **offline catalog** → outage/not-found |
| Cache TTLs? | shareholding 7d, sector P/E 1d (4h fallback), search 6h, models 1h, jobs 6h |
| State reducers? | `operator.add` on `sources`/`completed_workers`, `_last_value` on `status_message` |

---

## 23. Live-coding / whiteboard prompts

**Q23.1 — Add a new worker (e.g. dividend history). What do you touch?**
1. `tools/dividends.py` — fetch + return `{available, reason, ...}`; never raise.
2. `agents/workers.py` — a `dividends_worker` returning
   `{"dividend_data": ..., "completed_workers": ["dividends"], "status_message": "dividends_done"}`.
3. `agents/state.py` — add `dividend_data` and extend the `WorkerName` literal.
4. `agents/graph.py` — add to `_IO_WORKERS`, `add_node`, and the conditional-edge
   map (the `for w in _IO_WORKERS` loop wires the join edge automatically).
5. `agents/planner.py` — add to `DEFAULT_WORKERS` + a plan line.
6. `agents/synthesizer.py` — put it in the draft and append to `data_gaps` when
   unavailable.
7. `models/schemas.py` — a `Dividends` model + field on `ResearchBrief`.
8. `core/confidence.py` — a scoring rule if it carries claims.
9. `lib/api.ts` + a component + `PipelineStatus` step.
10. Tests + an eval `degraded_ok` check.
The fact this list is mechanical is the argument that the architecture is sound.

**Q23.2 — Add a new critic check.**
Write a `_check_x(draft) -> list[CriticIssue]` returning issues with a `code`, a
`message`, a `failed_subtask` naming the worker that can fix it, and a `claim`.
Add it to the `issues.extend(...)` block. The retry routing is then automatic —
the planner re-queues whatever `failed_subtask` names.

**Q23.3 — Implement SSE to replace polling.**
Backend: an `asyncio.Queue` per job; the progress callback pushes to it;
`GET /research/{job_id}/events` returns a `StreamingResponse` with
`media_type="text/event-stream"` yielding `data: {json}\n\n`, plus a terminal
event on completion. Frontend: `new EventSource(url)` in a `useEffect`, replacing
`setInterval`, with a fallback to polling if the connection errors — the seam is
already marked in `lib/api.ts`.

**Q23.4 — The critic keeps failing on P/E for one ticker. Debug it.**
Check whether `pe_ratio` came from `trailingPE` or `forwardPE` (the code falls
back to forward), since forward P/E legitimately differs from trailing
price÷EPS by more than 2.5. Then check whether `eps_ttm` is trailing while the
price is live. Then decide: is 2.5 the wrong tolerance for this metric, or is the
fallback to `forwardPE` the bug? I'd argue the latter — mixing forward and
trailing under one field name is the actual defect, and the `# UPDATE:` for
per-metric tolerance tables is the second-order fix.

**Q23.5 — Write the P/E band function on a whiteboard.**
```python
def compute_pe_band(dates, closes, quarterly_eps):
    if not quarterly_eps or not dates or not closes:
        return {"available": False, "reason": "Insufficient price or EPS history.", "series": []}
    eps = list(reversed(quarterly_eps))           # oldest-first
    series = []
    for i in range(3, len(eps)):
        window = eps[i-3:i+1]
        if any(w.get("eps") is None for w in window):
            continue                              # never interpolate
        ttm = sum(w["eps"] for w in window)
        if not ttm:
            continue                              # no div-by-zero
        price = nearest_close_on_or_before(eps[i]["period"])
        if price is None:
            continue
        series.append({"date": eps[i]["period"][:10], "pe": round(price/ttm, 2)})
    if not series:
        return {"available": False, "reason": f"Only {len(quarterly_eps)} quarter(s)…", "series": []}
    pes = [p["pe"] for p in series]
    return {"available": True, "series": series,
            "band_min": min(pes), "band_max": max(pes),
            "band_avg": sum(pes)/len(pes),
            "partial_history": len(quarterly_eps) < 8,
            "quarters_used": len(quarterly_eps)}
```

**Q23.6 — Design a rate limiter for `/research`.**
Redis `INCR` on `rate:{user_or_ip}:{minute}` with `EXPIRE 60` on first increment;
reject with 429 + `Retry-After` above the threshold. For this app the limit
should be on *concurrent jobs per user*, not requests per minute, because the
cost is a multi-minute pipeline: a Redis set of active job ids per user, checked
before job creation and cleaned up on terminal status.

---

## 24. Behavioural questions with this project as evidence

**Q24.1 — Tell me about a time you found a serious bug in your own code.**
The `.NS` resolution bug (Q20.4). One misplaced block meant every explicitly
suffixed ticker failed to resolve, which meant the eval harness — the source of
my headline accuracy metric — had never actually run. The lesson I took wasn't
"write more tests", it was "be suspicious of any metric you've never watched
fail". A number that always passes is a number that's never been exercised.

**Q24.2 — Tell me about a technical decision you reversed.**
Search started as "make `resolve_ticker` a bit fuzzier". That was wrong at the
shape level: one-in-one-out can't express ambiguity, so every failure looked
identical to the user. Rebuilding it as ranked candidates with confidence — the
same vocabulary the brief already used for claims — was more work but made the
whole product coherent. The trigger for reversing was noticing that "tata motor",
"the maggi company" and a typo all produced the same dead end.

**Q24.3 — How do you decide when something is good enough?**
The graceful-degradation contract is my line. A feature ships when its failure
mode is honest and visible — `available: false` with a reason, an entry in
`data_gaps`, a rendered "unavailable" notice. What I won't ship is a section that
looks complete but is silently empty, because that's the failure the user can't
detect.

**Q24.4 — How do you handle unreliable third-party dependencies?**
Isolate, wrap, degrade, document. `nsepython` is confined to two files behind
clean interfaces so swapping vendors is a two-file change. Every external call is
wrapped. Every failure has a shaped, user-visible degraded state. And the risk is
written into the README openly, including the fact that scraping those endpoints
is a grey area — because a reviewer finding that themselves is far worse than me
naming it first.

**Q24.5 — Tell me about a time something worked in development and broke in production.**
The Yahoo datacenter-IP block (Q20.11). Ticker resolution passed every test and
every local run, then failed 100% of queries on a hosted box — and reported it as
"that isn't a live NSE symbol" for the query *RELIANCE*. Two things I'd highlight
about how I handled it. First, I didn't reach for a retry loop; I asked which
source should own the fact "does this listing exist", and the answer was the
bundled NSE catalog, not a third-party quote endpoint — so the fix was a
correction of authority, not added plumbing. Second, I treated the misleading
error message as part of the bug rather than cosmetics: blaming a user for an
infrastructure failure costs them real time, so a fourth error code and a fourth
message went in alongside the logic. The follow-through was raising a `debug` log
to `warning`, because the one line that knew the cause had been invisible in
production the whole time.

**Q24.6 — What did you learn?**
That in an LLM system the hard engineering isn't the prompt — it's the
post-conditions. Every meaningful safety property in this project (corroboration,
compliance, prose quality, no-fabricated-tickers, no-LLM-arithmetic) is enforced
by deterministic code *after* the model answers, because a prompt is a request
and only code is a contract.

**Q24.7 — What are you most proud of?**
That the system tells the truth when it's degraded. Anyone can build the happy
path. Making six independent, flaky sources fail independently, keeping the brief
useful, and having the UI say exactly what's missing and why — that's the part
that required discipline in every layer, and it's the part I'd defend hardest.
