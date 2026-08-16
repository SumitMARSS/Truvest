# Codebase Audit — Truvest

Scope: `backend/app/agents/`, `backend/app/tools/`, `backend/app/services/`, `backend/app/api/`, `backend/app/models/`, `frontend/src/`, `backend/tests/`, `eval/`.

Method: full read of every file in scope (not a sample), cross-checked against how LangGraph merges partial state updates, plus a live check of outbound network access from this environment (Yahoo Finance reachable but rate-limited; `nseindia.com` unreachable directly from this sandbox — informs the fallback design for shareholding/sector data in Phase 2).

Severity key: **High** = causes a crash, silent data loss, or a false claim reaching the user. **Medium** = degrades UX/maintainability/trust but has a workaround or limited blast radius. **Low** = polish/hygiene.

---

## 1. Error handling gaps

| # | Finding | Severity | Where |
|---|---|---|---|
| 1.1 | `fetch_market_bundle` has **no try/except** around `yf.Ticker(ticker).history(period="3y")`. Every other worker's I/O call (news, filings) is wrapped and degrades to stub/empty data on failure. Market data is not — a single yfinance timeout, rate-limit (429, observed live from this sandbox), or network blip raises out of `market_worker`, out of the LangGraph node, out of `graph.stream()`, and is only caught by the blanket `except Exception` in `research.py:_execute_job`. The **entire job fails**, including news/filings/calc that may have already succeeded — no partial brief, no honest "market data unavailable" section. This is the single biggest violation of the "never crash the whole brief" requirement. | **High** | `tools/market_data.py:22-24` |
| 1.2 | No explicit timeout on the yfinance calls (`t.history()`, `t.info`, `t.calendar`, `t.financials`). yfinance's internal HTTP client has its own defaults, but nothing here bounds worst-case latency, so a hung upstream can stall the whole `pipeline_timeout_seconds` budget on one call. | Medium | `tools/market_data.py`, `tools/india_filings.py` |
| 1.3 | `resolve_ticker` raises `TickerResolutionError` (subclass of `ValueError`) for an unresolvable query. `resolve_ticker_node` doesn't catch it, so it propagates through the graph the same way as 1.1 — caught only by the outer blanket handler, which stringifies it into `job.error`. Functionally the job does fail gracefully (status becomes `failed`, not a 500), but the error path is indistinguishable from an actual internal bug in the API layer — no error *type*, so the frontend can't tell "you mistyped a ticker" from "our backend broke." | Medium | `agents/graph.py:47-53`, `api/routes/research.py:96-104` |
| 1.4 | No retry/backoff on any outbound call (yfinance, Tavily, Yahoo search). A transient failure is treated the same as a permanent one — one shot, then give up. Acceptable for an MVP demo, but worth calling out since the brief explicitly asks about "retry caps." | Low | all of `tools/` |

**Fix applied in this pass:** 1.1 (wrapped, degrades to a `market_unavailable` flag the synthesizer/UI can render honestly instead of crashing the job). 1.3 given a distinct, user-legible error path. See §7.

---

## 2. Hardcoded values / scattered logic

| # | Finding | Severity |
|---|---|---|
| 2.1 | `.NS`/`.BO` suffix stripping (`ticker.replace(".NS", "").replace(".BO", "")`) and exchange inference (`ticker.upper().endswith(".BO")`) are each **reimplemented independently** in `tools/market_data.py`, `tools/news_search.py`, `tools/india_filings.py`, and `agents/synthesizer.py`. Four copies of the same two lines — a future change to how BSE tickers are detected (e.g. numeric BSE codes) has to be found and fixed in four places. | **High** (exactly the "ticker-format assumptions scattered" gap named in scope) |
| 2.2 | The NSE quote URL template (`https://www.nseindia.com/get-quotes/equity?symbol={bare}`) is duplicated in `market_data.py` and `india_filings.py`. | Medium |
| 2.3 | `settings.brief_cache_ttl_seconds` exists in config but is used for the **job-status Redis TTL** (`job_store.py`, `ex=... * 6`), not for caching any actual market/news/filing data — misleading name vs. actual effect (see §4). | Medium |
| 2.4 | No config validation that `MAX_CRITIC_RETRIES` stays sane relative to LangGraph's default recursion budget. Not a live bug at the default (2), but there's no guard rail if someone sets it to, say, 20 — the graph would hit LangGraph's internal recursion limit before the critic's own cap. | Low |

**Fix applied in this pass:** 2.1 centralized into `app/core/ticker.py` (`strip_suffix`, `exchange_of`, `nse_quote_url`), all four call sites updated to import it.

---

## 3. State machine correctness

The graph topology itself (`agents/graph.py`) is correct: conditional fan-out to a list of node names is the right way to get parallel dispatch in LangGraph, the join is a real barrier before `calc`, and `calc`'s dependency on `market` is respected by the planner appending `"calc"` to any retry that includes `"market"`. Two real bugs found on closer inspection, both **not** the ones the brief speculated about (no infinite loop — the max-retry accounting is correct: `retry_count` is read *before* the current pass's issues are counted, so the critic runs at most `MAX_CRITIC_RETRIES + 1` times before force-accepting):

| # | Finding | Severity |
|---|---|---|
| 3.1 | **`sources` accumulates duplicates across retries.** `sources: Annotated[list[dict], operator.add]` concatenates rather than replaces. Source IDs are deterministic per (ticker, index) — e.g. `src-news-{ticker}-{i}` — so when `news` is retried after a critic failure, the retried worker's sources are *appended* to, not merged with, the first (failed) attempt's sources. The final brief's `sources` list can contain the **same ID twice** with different `title`/`url` (one stale from the failed attempt, one corrected) — the UI renders both, showing a contradictory pair of citations under the same reference number. This is a genuine "silently keeps a failed worker's output around" bug. | **High** |
| 3.2 | **The critic never checks `filings` for citation integrity.** `_check_citations` validates `price_action`, `fundamentals`, `calculations`, and each `news` item, but never iterates `draft.get("filings")`. Consequently `"filings"` is not reachable as a `failed_subtask` value anywhere in `critic.py` — there is no code path that can ever ask the planner to retry the filings worker. Today this is masked because `filings_worker` always sets `source_ids` on every entry it emits, so nothing currently *needs* the retry — but it's a real coverage gap: if a future filings source ever omitted citations, the pipeline would silently accept it rather than retry or flag it. | Medium-High |
| 3.3 | `completed_workers` has the same `operator.add` duplication as 3.1, but it's cosmetic (a worker name can appear twice in a list nothing else keys off of) — not user-visible. | Low |

**Fix applied in this pass:** 3.1 (dedupe `sources` by `id`, keep the last occurrence, at the point the synthesizer assembles the draft — that's the one place all accumulated sources are read before being frozen into the brief). 3.2 (added a filings citation check to the critic).

---

## 4. Type safety

- The Pydantic schemas (`models/schemas.py`) are enforced at exactly **one** boundary: `ResearchBrief.model_validate(brief_dict)` in `agents/runner.py`, right before returning from the sync pipeline entrypoint, and again on the round-trip through `job_store` (`ResearchJobResponse.model_validate`). Everywhere upstream of that — every worker, the synthesizer, the critic, all seven retry passes — the data is a raw `dict[str, Any]` inside a `TypedDict` (`AgentState`), which is a compile-time-only shape hint with zero runtime enforcement.
- Practically: a key typo in a worker (e.g. writing `bundle["nse__url"]`) would not raise anywhere — it would just silently produce a `None` at the one validation point, indistinguishable from "data genuinely unavailable." This is a reasonable trade-off for a LangGraph state machine (validating on every node would be expensive and LangGraph's TypedDict-state model doesn't really support it natively), but it means the schemas are documentation-and-final-contract, not an internal safety net — worth being explicit about in interview framing rather than overclaiming "Pydantic enforced end-to-end."
- Severity: **Medium** — no observed bug from this today, but it's the reason 3.1/3.2 were only caught by manual read-through rather than a validator complaining.

---

## 5. Caching

**There is no data cache anywhere in this codebase today.** Confirmed by exhaustive grep — the only TTL in the system is the Redis **job record** TTL (`job_store.py`), which stores the finished brief for a given `job_id`, not a reusable cache keyed by ticker. Two identical requests for `RELIANCE.NS` one second apart each independently: call yfinance for 3 years of daily history + `.info` + `.financials`, call Tavily twice (news + filings), and make 2 LLM calls. This is:

- **High** severity for cost/latency (every repeat query pays full price, and free-tier Tavily/OpenRouter quotas burn faster than necessary).
- Specifically called out as a blocker for Phase 2: shareholding pattern and sector P/E only change ~4x/year and daily respectively — fetching them fresh on every request would be actively wasteful and is the kind of thing an interviewer will ask "so you just... refetch that every time?"

**Fix applied in this pass:** added `app/services/cache.py`, a small TTL cache with an in-memory backend and an optional Redis backend (reuses the existing `redis_client`), keyed by an explicit namespace + key (e.g. `sector_pe:{sector}`, `shareholding:{ticker}:{quarter}`). Wired into the new valuation and shareholding workers in Phase 2 (§ARCHITECTURE.md). Did **not** retrofit caching onto the existing market/news/filings workers in this pass — that's a larger behavior change (staleness tolerance for *live* price data is a product decision, not a bug fix) and is called out as a follow-up rather than silently changed.

---

## 6. Frontend

| # | Finding | Severity |
|---|---|---|
| 6.1 | No error boundary — a render-time exception in `BriefView` (e.g. an unexpected null somewhere in a large brief) blanks the whole page with no recovery path. | Medium |
| 6.2 | No skeleton loaders for any section — while a job is `running`, only the step tracker (`PipelineStatus`) renders; the brief area is just absent until everything finishes. Users get one blocking wait, not per-section progressive reveal. | Medium |
| 6.3 | Directional color is the *only* signal on percentage changes (`pctTone`) — green/red text with no icon/shape, a real (if soft) accessibility gap for color-blind users on the single most important number in the UI. | Medium |
| 6.4 | State management is plain `useState` + a hand-rolled poll loop with a manual `inFlight` guard — appropriately lightweight for this app's size, not a real problem, just noting it wasn't over-engineered (React Query would be a reasonable but non-essential upgrade). | Low |
| 6.5 | No request cancellation (`AbortController`) tied to component unmount in `lib/api.ts` — if a user navigates away mid-poll, the in-flight fetch still resolves and (harmlessly, since polling stops via the `useEffect` cleanup clearing the interval) is just discarded. Low blast radius. | Low |
| 6.6 | Responsive breakpoints (`sm:`/`md:`/`lg:`) are already used consistently in `BriefView`/`PipelineStatus` — mobile layout is in reasonable shape already, not a gap. | — (no finding) |
| 6.7 | No test framework configured in `frontend/package.json` (no vitest/jest/testing-library) — zero frontend tests exist. | Medium |

**Fix applied in this pass:** 6.1–6.3 addressed as part of the Phase 3 UI upgrade (error boundary, skeleton components, non-color trend indicators). 6.7 addressed by adding Vitest + a handful of component/unit tests for the new confidence badge and compliance-filter-facing UI. Full frontend test coverage of the pre-existing components is out of scope for this pass (see `README.md` follow-ups).

---

## 7. Tests

**Before this pass:** `backend/tests/test_critic_planner.py` — 3 tests total (planner initial fan-out, planner targeted retry, one critic check for missing price). Nothing else has a test.

Missing, in order of how load-bearing the untested code is:

1. `tools/code_exec.py` (`run_calculations`) — **the one place the entire architecture claims "no LLM does math."** This being untested is the most surprising gap in the repo: it's pure, deterministic, trivially testable, and it's the load-bearing proof of the project's central design claim. **High.**
2. `tools/market_data.py` — no test exercises the `pct_change` date-window logic (the trickiest pure function in the tools layer: nearest-prior-close-by-calendar-day, with a fallback for short history windows).
3. `services/ticker_resolve.py` — no test for suffix cleaning, alias fast-path, or the `TickerResolutionError` path.
4. No integration test runs the graph end-to-end with mocked tools (everything today calls `planner_node`/`critic_node` directly with hand-built dicts — reasonable for those two, but nothing proves the graph *wiring* itself, e.g. that a critic failure actually produces a re-run of only the targeted worker through the real `StateGraph`).
5. `eval/run_eval.py` hits live yfinance + a real LLM for 19 tickers — it's an eval harness, not a CI test, and is correctly excluded from `pytest`'s `testpaths`, but it has no mock mode, so it can't run in CI at all today (by design, not a bug — noting it since Phase 2 extends this harness).
6. Frontend: zero tests (see 6.7).

**Fix applied in this pass:** added tests for `run_calculations` (#1) and `ticker_resolve` (#3) as part of Phase 1, since both are pure logic with no external dependency — no excuse for them to stay untested while I was already in those files fixing 2.1. Added unit tests for the new confidence-scoring and compliance-filter modules in Phase 2 (both pure-logic, explicitly required by the task). Did not attempt #4 (full graph integration test with mocked tools) or #2 in this pass — flagged as the top follow-up in `ARCHITECTURE.md`.

---

---

## 8. Defects found by live browser verification (Phase 3)

Unit tests and typechecking passed on all of the below — these were only caught by actually launching the app and driving it in a headless browser at desktop *and* mobile viewports. Worth listing separately because "the tests were green" was true the whole time.

| # | Finding | Severity | Fix |
|---|---|---|---|
| 8.1 | **Page-level horizontal scroll on mobile in compare mode.** The classic CSS-grid footgun: grid items default to `min-width: auto`, so they refuse to shrink below their content's min-content width. The peer table's `min-w-[560px]` therefore forced the whole grid column past the 390px viewport, and the *page* scrolled sideways instead of the table scrolling inside its own `overflow-x-auto` container. Measured: `documentElement.scrollWidth` 603 vs `clientWidth` 390, with uncontained overflowing elements (headers, disclaimer, summary) confirmed by walking every element's ancestors for a scroll container. | **High** (breaks the stated mobile-responsiveness requirement) | `min-w-0` on each grid item in `CompareView`. Re-measured: `pageOverflows: false`, 0 uncontained overflows. |
| 8.2 | **Duplicate React keys** in the risks / news / filing-bullet lists — keys were derived from content (`r.title + r.detail.slice(0,24)`), and the backend legitimately emits two risks sharing both. React's warning is not cosmetic here: duplicate keys let it omit or duplicate children on re-render. Pre-existing in `BriefView`, surfaced by the new data. | Medium | Index-prefixed keys throughout `BriefView` + `DataGapBanner`. Verified: 0 duplicate-key warnings in console. |
| 8.3 | **Duplicate filings rendered as separate cards.** Tavily returns multiple URLs whose scraped text is the same exchange disclosure, so the brief showed the identical INDIA_RESULTS filing twice and derived duplicate risk flags from it — visibly a "data dump" artifact. | Medium | Fingerprint-dedupe on the first cleaned snippet in `_tavily_india_filings`. Verified live: filing cards 3 → 2, risk flags 4 → 2, no content repeated. |
| 8.4 | Missing favicon → a 404 on every page load, and a generic browser icon on a product meant to read as polished fintech. | Low | Inline `data:` SVG favicon in `index.html` (no extra asset request). Console now completely clean — zero errors or warnings. |

Method note for reproducibility: backend + Vite launched for real, driven with headless Chromium via `puppeteer-core` — single-ticker flow, compare flow, and a fresh mobile-viewport compare run, asserting on rendered text, table sort behavior, per-element overflow containment, and the console error/warning stream.

---

---

## 9. Defect found by running the eval harness (Phase 2)

| # | Finding | Severity | Fix |
|---|---|---|---|
| 9.1 | **Explicitly-suffixed tickers (`TCS.NS`, `RELIANCE.BO`) failed to resolve at all.** `_clean_query` replaces dots with spaces, so `"TCS.NS"` becomes `"TCS NS"`. The code that re-joins the suffix (`if cleaned.endswith((" NS", " BO"))`) sat **inside** `if " " not in cleaned:` — a branch where a string containing a space is unreachable by construction. So the re-join was dead code, every `*.NS`/`*.BO` query fell through to the multi-word company-name search path, Yahoo search returned nothing useful for `"TCS NS"`, and resolution raised `TickerResolutionError: Tried: nothing`. Consequences: (a) **the entire eval harness was unrunnable** — every ticker in `eval/tickers_testset.json` is `.NS`-suffixed, so `make eval` failed on the first case; (b) any user entering the exact format the README documents (`TCS.NS`) got a "could not resolve" error. Not caught earlier because every manual test, smoke test, and browser test used the bare symbol (`RELIANCE`), and the pre-existing unit test only covered the bare-symbol path. | **High** | Hoisted the suffix re-join above the single-word test. Two regression tests added (NSE + BSE). Verified: `TCS.NS` now resolves directly with **no** network round-trip and no `.NS`/`.BO` guessing. |

This one is worth calling out in an interview: it's a case where the tests were green, the app worked in the browser, and the bug was only exposed by running a *different* entrypoint (the eval harness) that happened to use the input format nothing else did.

| # | Finding | Severity | Fix |
|---|---|---|---|
| 9.2 | **Degenerate LLM output reached the user verbatim.** Every LLM fallback in the codebase guarded on `if text:` — i.e. it only fell back when the model returned an *empty* string. Free/small models also fail by returning non-empty gibberish. Captured live from `openai/gpt-oss-20b:free` on the compare prompt: `"? = is... is, isALG(?.. is?.....com.... ...………iqué………i…....…..……..…"` — which was written straight into the brief as the comparison summary. In a tool whose entire pitch is trustworthiness, unreadable word-salad is worse than an honest deterministic summary. | **High** | New `core/text_quality.py::looks_like_prose` — a deterministic gate (length, real-word count, expected-character ratio, vocabulary variety); no second LLM call to judge the first. Wired into both the single-ticker summary and the compare summary. 7 unit tests, including the verbatim captured garbage string. Verified live: the same compare query now falls back to clean, accurate, compliance-safe prose. |

---

## Summary — what got fixed in Phase 1 vs. deferred

| Fixed now | Deferred (tracked as follow-up) |
|---|---|
| 1.1 market worker crash-the-whole-job bug | 1.2 explicit per-call timeouts |
| 2.1 centralized ticker suffix/exchange helper | 2.2 NSE URL template dedup (cosmetic) |
| 3.1 duplicate-sources-on-retry bug | 3.3 duplicate `completed_workers` (cosmetic, no user impact) |
| 3.2 filings citation-check gap in critic | full graph integration test (§7.4) |
| 5. cache layer built + wired into new Phase-2 workers | retrofitting cache onto existing market/news/filings workers (product decision, not a bug) |
| 7. tests for `run_calculations` + `ticker_resolve` | `pct_change` window tests, frontend test suite beyond the new components |
| 6.1–6.3 frontend error boundary / skeletons / non-color trend indicators | 6.4/6.5 (no real bug, left as-is) |
| 8.1 mobile page-level horizontal scroll in compare mode | — |
| 8.2 duplicate React keys · 8.3 duplicate filings · 8.4 favicon 404 | — |
| 9.1 `*.NS`/`*.BO` tickers unresolvable (eval harness fully broken) | — |
| 9.2 degenerate LLM output reaching the brief verbatim | — |

All **High**-severity items are fixed. Medium items are either fixed (where cheap and in-scope) or explicitly deferred above with a one-line reason, not silently dropped.

### Where each class of bug was caught

Worth noting for the interview narrative, because the three phases caught genuinely different classes of defect and no single technique would have found them all:

| Technique | Bugs it caught |
|---|---|
| Reading the code | 1.1 crash-the-job, 2.1 scattered ticker logic, 3.1 duplicate sources on retry, 3.2 missing filings citation check, 5 no caching |
| Unit tests (new) | Confirmed the pure-logic contracts (confidence, compliance, P/E band, corroboration rule) — no new bugs, but they're the regression net |
| Running the app in a real browser | 8.1 mobile overflow, 8.2 duplicate keys, 8.3 duplicate filings, 8.4 favicon 404 — all invisible to a green test suite |
| Running a second entrypoint (eval harness) | 9.1 `*.NS` resolution failure — invisible to both the tests and the browser, because only the eval harness used that input format |
| Reading actual output on a real query | 9.2 degenerate LLM text — every automated check passed (job completed, schema valid, summary non-empty); only reading the words revealed it was gibberish |
