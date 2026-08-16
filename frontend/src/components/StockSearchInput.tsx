import { ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
import { Loader2, Search } from "lucide-react";
import { searchStocks, type StockSuggestion } from "@/lib/api";

/**
 * Typeahead search box for NSE/BSE listings.
 *
 * Layout, deliberately: the results panel is a NORMAL BLOCK in the document
 * flow, rendered between the input row and whatever the parent puts below it.
 * It is not an absolutely-positioned overlay, so it cannot sit on top of the
 * example chips or the disclaimer, cannot escape the search card, and needs no
 * z-index at all — the card simply grows and the content below moves down.
 * (The previous version floated the list; on a stale stylesheet it rendered
 * transparent and printed straight over the content underneath it.)
 *
 * Behaviour, deliberately:
 *  - it never opens on its own. A prefilled value, a value written by a
 *    suggestion click, or a remount when switching modes is not a question, so
 *    it isn't answered with a dropdown. Only typing, or an explicit
 *    `openSignal` from the parent, starts a search.
 *  - it closes and stays closed while a research job is running.
 *
 * Typing is never blocked: the free-text value stays authoritative and
 * submittable even if the suggestion request is slow, aborted or failing.
 */

const DEBOUNCE_MS = 220;

// Opacities are in bracket notation: Tailwind only emits bare slash values
// from its own scale, and 12 and 8 are not in it. The previous values compiled
// to no rule, so these pills rendered as bare text with no fill behind them.
const CONFIDENCE_STYLES: Record<string, { pill: string; bar: string; label: string }> = {
  high: { pill: "bg-accent/[0.12] text-accent", bar: "bg-accent", label: "High" },
  medium: { pill: "bg-warn/[0.12] text-warn", bar: "bg-warn", label: "Medium" },
  low: { pill: "bg-ink/[0.08] text-secondary", bar: "bg-ink/30", label: "Low" },
};

const LAYER_LABELS: Record<string, string> = {
  catalog: "NSE listing catalog",
  yahoo: "Yahoo Finance",
  llm: "AI interpretation",
};

export function StockSearchInput({
  label,
  value,
  onChange,
  onSelect,
  onComparePair,
  placeholder,
  hint,
  selectHint = "Click a match to run the research pipeline",
  action,
  disabled = false,
  /** Increment to make the box search its current value and show matches. */
  openSignal = 0,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  /** Fired when a suggestion is chosen (click, Enter or Tab). */
  onSelect: (choice: StockSuggestion) => void;
  /** Fired when the typed text reads as "A vs B". */
  onComparePair?: (pair: [string, string] | null) => void;
  placeholder?: string;
  hint?: string;
  /** What choosing a match does here — it runs a job in single mode, but only
      fills the field in compare mode, and the panel should say which. */
  selectHint?: string;
  /** Submit button, rendered on the input's row (stacks below on mobile). */
  action?: ReactNode;
  disabled?: boolean;
  openSignal?: number;
}) {
  const [suggestions, setSuggestions] = useState<StockSuggestion[]>([]);
  const [layers, setLayers] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [searchedFor, setSearchedFor] = useState("");

  const baseId = useId();
  const inputId = `${baseId}-input`;
  const listId = `${baseId}-list`;
  const boxRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  // Nothing is searched until the user asks for it — by typing, or via the
  // parent's openSignal. This is what stops a prefilled "RELIANCE" from
  // greeting everyone with an open list on first paint.
  const requested = useRef(false);
  // The value this box wrote itself when a suggestion was chosen. It is an
  // answer, not a question, so it is never searched — and the suppression is
  // durable rather than one-shot, because the effect re-runs again later when
  // a job starts and finishes. Cleared as soon as the user types or asks for
  // a fresh lookup.
  const selfWritten = useRef<string | null>(null);
  // Only a *change* in openSignal is a request. Comparing against the value
  // captured at mount matters: switching modes remounts this box with a signal
  // that is already non-zero, and treating that as a request would re-open the
  // list for a query the user asked about several interactions ago.
  const lastOpenSignal = useRef(openSignal);
  // What the last search actually asked for. The effect also re-runs when
  // `disabled` flips (a job starting and finishing), and without this the box
  // would silently re-open its list over the finished brief — a question the
  // user asked several minutes ago.
  const lastQueried = useRef<string | null>(null);

  // Declared before the search effect so the flags are set by the time it runs.
  useEffect(() => {
    if (openSignal !== lastOpenSignal.current) {
      lastOpenSignal.current = openSignal;
      requested.current = true;
      selfWritten.current = null;
    }
  }, [openSignal]);

  useEffect(() => {
    const query = value.trim();
    if (!requested.current || disabled) return;
    // The box put this text here itself by applying a suggestion.
    if (selfWritten.current === query) return;
    if (!query) {
      lastQueried.current = null;
      setSuggestions([]);
      setLayers([]);
      setOpen(false);
      onComparePair?.(null);
      return;
    }
    // Same question as last time (the effect re-ran for some other reason) —
    // don't re-ask it, and above all don't re-open the list on the user.
    if (lastQueried.current === `${query}|${openSignal}`) return;

    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      lastQueried.current = `${query}|${openSignal}`;
      try {
        const result = await searchStocks(query, 5, controller.signal);
        setSuggestions(result.suggestions);
        setLayers(result.layers_used || []);
        setSearchedFor(query);
        setActiveIndex(result.suggestions.length ? 0 : -1);
        setOpen(true);
        onComparePair?.(result.compare_pair ?? null);
      } catch {
        // Aborted or offline — keep whatever was on screen; the raw text is
        // still submittable, which is the behaviour we had before search.
      } finally {
        setLoading(false);
      }
    }, DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // onComparePair is intentionally excluded: callers pass inline closures,
    // and re-running the search on every parent render would defeat debouncing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, openSignal, disabled]);

  // A running job takes over the page — collapse the list rather than leaving
  // it sitting above the pipeline view.
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  // Click-away closes the list without stealing the click from the page.
  useEffect(() => {
    if (!open) return;
    function onDocumentPointerDown(event: MouseEvent) {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocumentPointerDown);
    return () => document.removeEventListener("mousedown", onDocumentPointerDown);
  }, [open]);

  // Keep the keyboard-highlighted row inside the scroll viewport. Optional
  // call: scrollIntoView is a browser nicety, not something to crash on when
  // the environment (jsdom, older engines) doesn't implement it.
  useEffect(() => {
    if (!open || activeIndex < 0) return;
    const row = listRef.current?.children[activeIndex] as HTMLElement | undefined;
    row?.scrollIntoView?.({ block: "nearest" });
  }, [activeIndex, open]);

  const choose = useCallback(
    (choice: StockSuggestion) => {
      selfWritten.current = choice.symbol;
      onChange(choice.symbol);
      setOpen(false);
      setActiveIndex(-1);
      onSelect(choice);
    },
    [onChange, onSelect],
  );

  function handleChange(next: string) {
    requested.current = true;
    selfWritten.current = null;
    onChange(next);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!open || suggestions.length === 0) {
      // Nothing to navigate — let Enter submit the raw text as usual.
      if (event.key === "ArrowDown" && suggestions.length) setOpen(true);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((i) => (i + 1) % suggestions.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((i) => (i <= 0 ? suggestions.length - 1 : i - 1));
    } else if (event.key === "Enter" && activeIndex >= 0) {
      // Choosing a suggestion must not also submit the form with the old text.
      event.preventDefault();
      choose(suggestions[activeIndex]);
    } else if (event.key === "Tab" && activeIndex >= 0) {
      choose(suggestions[activeIndex]);
    }
  }

  const trimmed = value.trim();
  const showResults = open && suggestions.length > 0;
  const showEmptyState =
    open && !loading && suggestions.length === 0 && searchedFor === trimmed && trimmed.length > 1;

  return (
    <div className="w-full min-w-0" ref={boxRef}>
      <label
        htmlFor={inputId}
        className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.12em] text-muted"
      >
        {label}
      </label>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="relative min-w-0 flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/30"
            aria-hidden="true"
          />
          <input
            id={inputId}
            value={value}
            onChange={(e) => handleChange(e.target.value)}
            onKeyDown={onKeyDown}
            onFocus={() => suggestions.length && !disabled && setOpen(true)}
            placeholder={placeholder}
            disabled={disabled}
            required
            autoComplete="off"
            spellCheck={false}
            role="combobox"
            aria-expanded={showResults}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-busy={loading}
            aria-activedescendant={activeIndex >= 0 ? `${listId}-opt-${activeIndex}` : undefined}
            className="h-11 w-full rounded-lg border border-line bg-surface pl-9 pr-9 text-[15px] font-medium text-ink outline-none transition placeholder:font-normal placeholder:text-muted focus:border-accent/60 focus:ring-2 focus:ring-accent/20 disabled:cursor-not-allowed disabled:bg-elevated disabled:text-muted"
          />
          {loading && (
            <Loader2
              className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-accent"
              aria-hidden="true"
            />
          )}
        </div>
        {action}
      </div>

      {/* Screen-reader announcement for a change the eye gets from the list. */}
      <p className="sr-only" role="status" aria-live="polite">
        {showResults ? `${suggestions.length} matches for ${searchedFor}` : ""}
      </p>

      {hint && !showResults && !showEmptyState && (
        <p className="mt-2 text-xs text-muted">{hint}</p>
      )}

      {showResults && (
        <div className="mt-2 overflow-hidden rounded-lg border border-line bg-surface">
          <ul
            id={listId}
            ref={listRef}
            role="listbox"
            aria-label="Matching stocks"
            className="scroll-thin max-h-[19rem] overflow-y-auto"
          >
            {suggestions.map((s, i) => {
              const style = CONFIDENCE_STYLES[s.confidence] || CONFIDENCE_STYLES.low;
              const active = i === activeIndex;
              return (
                <li key={`${s.ticker}-${i}`}>
                  <button
                    type="button"
                    id={`${listId}-opt-${i}`}
                    role="option"
                    aria-selected={active}
                    onMouseEnter={() => setActiveIndex(i)}
                    onClick={() => choose(s)}
                    className={`flex w-full items-center gap-3 border-b border-line/70 px-3.5 py-2.5 text-left transition last:border-b-0 ${
                      active ? "bg-elevated" : "bg-transparent hover:bg-elevated/70"
                    }`}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-sm font-semibold tracking-tight text-ink">
                          {s.symbol}
                        </span>
                        <span className="shrink-0 rounded border border-line px-1 py-px text-[9px] font-semibold uppercase tracking-[0.1em] text-muted">
                          {s.exchange}
                        </span>
                        {s.sources.includes("llm") && (
                          <span className="shrink-0 rounded bg-accent/[0.12] px-1 py-px text-[9px] font-semibold uppercase tracking-[0.1em] text-accent">
                            AI
                          </span>
                        )}
                      </span>
                      <span className="block truncate text-[13px] text-ink/70">{s.name}</span>
                      <span className="block truncate text-[11px] text-muted">
                        {s.match_reason}
                        {s.industry ? ` · ${s.industry}` : ""}
                      </span>
                    </span>
                    <span className="w-[88px] shrink-0 text-right">
                      <span
                        className={`inline-block whitespace-nowrap rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.08em] ${style.pill}`}
                        title={`Match confidence: ${Math.round(s.score * 100)}%`}
                      >
                        {style.label} {Math.round(s.score * 100)}%
                      </span>
                      <span className="mt-1 block h-[3px] w-full overflow-hidden rounded-full bg-ink/10">
                        <span
                          className={`block h-full ${style.bar}`}
                          style={{ width: `${Math.round(s.score * 100)}%` }}
                        />
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <p className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t border-line bg-elevated px-3.5 py-1.5 text-[11px] text-muted">
            <span>{selectHint}</span>
            {layers.length > 0 && <span>via {layers.map((l) => LAYER_LABELS[l] || l).join(" + ")}</span>}
          </p>
        </div>
      )}

      {showEmptyState && (
        <p className="mt-2 rounded-lg border border-line bg-elevated px-3.5 py-2.5 text-sm text-muted">
          No NSE/BSE match for “{trimmed}”. You can still run it as typed.
        </p>
      )}
    </div>
  );
}
