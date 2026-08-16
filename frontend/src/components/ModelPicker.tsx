import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Cpu, Sparkles } from "lucide-react";
import type { LlmModel, ModelCatalog } from "@/lib/api";

/**
 * Which LLM writes the brief.
 *
 * The pipeline used to be pinned to one free model. Free models are
 * rate-limited and vary a lot on this workload — long JSON context in,
 * disciplined prose out — so when one is busy or waffles, the useful recovery
 * is picking another, not waiting for a redeploy.
 *
 * Layout note, same reasoning as StockSearchInput: the panel is absolutely
 * positioned but anchored to a wrapper with an explicit z-index, because unlike
 * the search box this control sits on a toolbar row where pushing content down
 * would reflow the whole form on every open.
 *
 * Read-only mode matters: on a paid provider (`selectable: false`) the server
 * fixes the model, so this renders as a plain label rather than a control that
 * looks live and then rejects every choice.
 */

function contextLabel(tokens?: number | null): string | null {
  if (!tokens) return null;
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(tokens % 1_000_000 === 0 ? 0 : 1)}M ctx`;
  return `${Math.round(tokens / 1000)}K ctx`;
}

export function ModelPicker({
  catalog,
  value,
  onChange,
  disabled = false,
}: {
  catalog: ModelCatalog | null;
  /** null = follow the server default. */
  value: string | null;
  onChange: (modelId: string | null) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const boxRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const baseId = useId();
  const listId = `${baseId}-list`;

  const models = catalog?.models ?? [];
  const selectedId = value ?? catalog?.default ?? null;
  const selected = useMemo(
    () => models.find((m) => m.id === selectedId) ?? null,
    [models, selectedId],
  );

  // Grouped by vendor so a list of a dozen NVIDIA variants reads as one family
  // rather than a wall. Order within each group is the server's ranking.
  const groups = useMemo(() => {
    const byVendor = new Map<string, LlmModel[]>();
    for (const model of models) {
      const bucket = byVendor.get(model.vendor);
      if (bucket) bucket.push(model);
      else byVendor.set(model.vendor, [model]);
    }
    return Array.from(byVendor, ([vendor, items]) => ({ vendor, items }));
  }, [models]);

  // Flat order for keyboard navigation — the visual grouping above must not
  // change what Arrow Down moves through.
  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  // A running job owns the page — don't leave a menu floating over it.
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  useEffect(() => {
    if (!open || activeIndex < 0) return;
    const row = listRef.current?.querySelectorAll("[role='option']")[activeIndex] as
      | HTMLElement
      | undefined;
    row?.scrollIntoView?.({ block: "nearest" });
  }, [activeIndex, open]);

  function choose(model: LlmModel) {
    // Store the default as null so the choice keeps tracking the server's
    // default if it changes, instead of freezing today's value forever.
    onChange(model.id === catalog?.default ? null : model.id);
    setOpen(false);
    setActiveIndex(-1);
  }

  function toggle() {
    if (disabled) return;
    setOpen((wasOpen) => {
      if (!wasOpen) setActiveIndex(Math.max(0, flat.findIndex((m) => m.id === selectedId)));
      return !wasOpen;
    });
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!open) {
      if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggle();
      }
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((i) => (i + 1) % flat.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((i) => (i <= 0 ? flat.length - 1 : i - 1));
    } else if (event.key === "Enter" && activeIndex >= 0) {
      // Never let choosing a model also submit the research form.
      event.preventDefault();
      choose(flat[activeIndex]);
    }
  }

  // No catalog (endpoint down or nothing to choose between) — say nothing. The
  // run still works on the server default.
  if (!catalog || models.length === 0) return null;

  if (!catalog.selectable) {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-elevated px-2.5 py-1.5 text-xs text-muted"
        title={catalog.note}
      >
        <Cpu className="h-3.5 w-3.5" aria-hidden="true" />
        <span className="font-medium text-ink/75">{selected?.name || catalog.default}</span>
        <span className="hidden sm:inline">· fixed by server</span>
      </span>
    );
  }

  return (
    <div className="relative" ref={boxRef}>
      <button
        type="button"
        onClick={toggle}
        onKeyDown={onKeyDown}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-label={`AI model: ${selected?.name || catalog.default}. Change model`}
        title={catalog.note}
        className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-line bg-elevated px-2.5 py-1.5 text-xs text-muted transition hover:border-accent/40 hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Cpu className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className="truncate font-semibold text-ink/80">{selected?.name || catalog.default}</span>
        {selected?.reasoning && (
          <Sparkles className="h-3 w-3 shrink-0 text-accent" aria-label="reasoning model" />
        )}
        <ChevronDown
          className={`h-3.5 w-3.5 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>

      {open && (
        <div className="absolute right-0 z-40 mt-2 w-[min(23rem,calc(100vw-2rem))] overflow-hidden rounded-lg border border-line bg-surface shadow-pop">
          <p className="border-b border-line bg-elevated px-3.5 py-2 text-[11px] leading-relaxed text-muted">
            {catalog.note}
          </p>
          <ul
            id={listId}
            ref={listRef}
            role="listbox"
            aria-label="AI model"
            className="scroll-thin max-h-[21rem] overflow-y-auto"
          >
            {groups.map(({ vendor, items }) => (
              <li key={vendor} role="presentation">
                <p className="sticky top-0 z-10 bg-surface/95 px-3.5 pb-1 pt-2.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted backdrop-blur">
                  {vendor}
                </p>
                <ul role="presentation">
                  {items.map((model) => {
                    const index = flat.indexOf(model);
                    const active = index === activeIndex;
                    const isSelected = model.id === selectedId;
                    const isDefault = model.id === catalog.default;
                    const ctx = contextLabel(model.context_length);
                    return (
                      <li key={model.id}>
                        <button
                          type="button"
                          role="option"
                          aria-selected={isSelected}
                          onMouseEnter={() => setActiveIndex(index)}
                          onClick={() => choose(model)}
                          title={model.description || model.id}
                          className={`flex w-full items-start gap-2.5 px-3.5 py-2 text-left transition ${
                            active ? "bg-elevated" : "bg-transparent hover:bg-elevated/70"
                          }`}
                        >
                          <Check
                            className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${
                              isSelected ? "text-accent" : "text-transparent"
                            }`}
                            aria-hidden="true"
                          />
                          <span className="min-w-0 flex-1">
                            <span className="flex flex-wrap items-center gap-1.5">
                              <span className="truncate text-[13px] font-semibold text-ink">
                                {model.name}
                              </span>
                              {isDefault && (
                                <span className="shrink-0 rounded bg-accent/[0.12] px-1 py-px text-[9px] font-bold uppercase tracking-[0.08em] text-accent">
                                  Default
                                </span>
                              )}
                              {model.reasoning && (
                                <span
                                  className="shrink-0 rounded border border-line px-1 py-px text-[9px] font-semibold uppercase tracking-[0.08em] text-muted"
                                  title="Reasoning model — thinks before answering, so runs take longer"
                                >
                                  Reasoning
                                </span>
                              )}
                            </span>
                            <span className="mt-0.5 block truncate text-[11px] text-muted">
                              {[ctx, model.id].filter(Boolean).join(" · ")}
                            </span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export { contextLabel };
