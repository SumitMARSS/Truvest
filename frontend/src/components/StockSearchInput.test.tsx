import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StockSearchInput } from "./StockSearchInput";
import type { StockSuggestion } from "@/lib/api";

const searchStocks = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ searchStocks }));

function suggestion(partial: Partial<StockSuggestion> = {}): StockSuggestion {
  return {
    symbol: "RELIANCE",
    ticker: "RELIANCE.NS",
    name: "Reliance Industries Limited",
    exchange: "NSE",
    industry: "Oil Gas & Consumable Fuels",
    score: 1,
    confidence: "high",
    match_reason: "Exact NSE symbol",
    sources: ["catalog"],
    ...partial,
  };
}

function resultOf(suggestions: StockSuggestion[], extra: Record<string, unknown> = {}) {
  return { query: "q", suggestions, layers_used: ["catalog"], compare_pair: null, ...extra };
}

/** Stateful host so typing behaves like it does in the real form. */
function Harness({
  initialValue = "",
  onSelect = vi.fn(),
  onComparePair = vi.fn(),
  disabled = false,
  openSignal = 0,
}: {
  initialValue?: string;
  onSelect?: (choice: StockSuggestion) => void;
  onComparePair?: (pair: [string, string] | null) => void;
  disabled?: boolean;
  openSignal?: number;
}) {
  const [value, setValue] = useState(initialValue);
  return (
    <StockSearchInput
      label="Ticker"
      value={value}
      onChange={setValue}
      onSelect={onSelect}
      onComparePair={onComparePair}
      disabled={disabled}
      openSignal={openSignal}
    />
  );
}

function type(text: string) {
  fireEvent.change(screen.getByRole("combobox"), { target: { value: text } });
}

afterEach(() => {
  searchStocks.mockReset();
});

describe("StockSearchInput", () => {
  it("does not search or open on its own when the box is prefilled", async () => {
    searchStocks.mockResolvedValue(resultOf([suggestion()]));
    render(<Harness initialValue="RELIANCE" />);

    await new Promise((r) => setTimeout(r, 350));
    expect(searchStocks).not.toHaveBeenCalled();
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("searches the current value when the page asks it to (Try example)", async () => {
    searchStocks.mockResolvedValue(resultOf([suggestion()]));
    const { rerender } = render(<Harness initialValue="RELIANCE" openSignal={0} />);
    rerender(<Harness initialValue="RELIANCE" openSignal={1} />);

    expect(await screen.findByRole("option")).toHaveTextContent("RELIANCE");
  });

  it("does not open when mounted with a signal from an earlier interaction", async () => {
    /** Regression: switching tabs remounts the box with openSignal already
     *  non-zero, which used to re-open the previous query's matches. */
    searchStocks.mockResolvedValue(resultOf([suggestion()]));
    render(<Harness initialValue="TCS" openSignal={3} />);

    await new Promise((r) => setTimeout(r, 350));
    expect(searchStocks).not.toHaveBeenCalled();
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("shows ranked suggestions with their confidence and reason", async () => {
    searchStocks.mockResolvedValue(
      resultOf([
        suggestion(),
        suggestion({
          symbol: "RPOWER",
          ticker: "RPOWER.NS",
          name: "Reliance Power Limited",
          score: 0.72,
          confidence: "medium",
          match_reason: "Company name starts with your text",
        }),
      ]),
    );
    render(<Harness />);
    type("reliance");

    const options = await screen.findAllByRole("option");
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveTextContent("RELIANCE");
    expect(options[0]).toHaveTextContent("High 100%");
    expect(options[0]).toHaveTextContent("Exact NSE symbol");
    expect(options[1]).toHaveTextContent("Medium 72%");
  });

  it("renders the results panel in the document flow, after the input", async () => {
    /** Regression: the panel used to be an absolutely-positioned overlay,
     *  so it printed on top of the example chips and the disclaimer. It must
     *  be a normal block that comes after the input and takes up space, which
     *  is what makes the surrounding content move down instead of being
     *  covered. jsdom applies no CSS, so this asserts the two structural
     *  facts a layout regression would break: DOM order, and the absence of
     *  out-of-flow positioning classes. */
    searchStocks.mockResolvedValue(resultOf([suggestion()]));
    const { container } = render(<Harness />);
    type("reliance");

    const list = await screen.findByRole("listbox");
    const input = screen.getByRole("combobox");
    const position = input.compareDocumentPosition(list);
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    for (let el: HTMLElement | null = list as HTMLElement; el && el !== container; el = el.parentElement) {
      expect(el.className).not.toMatch(/\b(absolute|fixed)\b/);
    }
  });

  it("caps its own height so a long list scrolls internally", async () => {
    searchStocks.mockResolvedValue(
      resultOf(Array.from({ length: 5 }, (_, i) => suggestion({ symbol: `SYM${i}`, ticker: `SYM${i}.NS` }))),
    );
    render(<Harness />);
    type("s");

    const list = await screen.findByRole("listbox");
    expect(list.className).toMatch(/max-h-/);
    expect(list.className).toMatch(/overflow-y-auto/);
  });

  it("names the layers that produced the answer", async () => {
    searchStocks.mockResolvedValue(
      resultOf([suggestion({ sources: ["catalog", "yahoo"] })], { layers_used: ["catalog", "yahoo"] }),
    );
    render(<Harness />);
    type("reliance");

    expect(await screen.findByText(/NSE listing catalog \+ Yahoo Finance/i)).toBeInTheDocument();
  });

  it("selects a suggestion on click and reports it to the page", async () => {
    const onSelect = vi.fn();
    searchStocks.mockResolvedValue(resultOf([suggestion()]));
    render(<Harness onSelect={onSelect} />);
    type("reliance");

    fireEvent.click(await screen.findByRole("option"));

    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ ticker: "RELIANCE.NS" }));
    expect(screen.getByRole("combobox")).toHaveValue("RELIANCE");
  });

  it("does not reopen the list after a selection fills the box", async () => {
    searchStocks.mockResolvedValue(resultOf([suggestion()]));
    render(<Harness />);
    type("reliance");

    fireEvent.click(await screen.findByRole("option"));

    await new Promise((r) => setTimeout(r, 350));
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("supports arrow-key navigation and Enter to choose", async () => {
    const onSelect = vi.fn();
    searchStocks.mockResolvedValue(
      resultOf([suggestion(), suggestion({ symbol: "RPOWER", ticker: "RPOWER.NS" })]),
    );
    render(<Harness onSelect={onSelect} />);
    type("reliance");

    await screen.findAllByRole("option");
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ symbol: "RPOWER" }));
  });

  it("closes the list on Escape", async () => {
    searchStocks.mockResolvedValue(resultOf([suggestion()]));
    render(<Harness />);
    type("reliance");

    await screen.findByRole("option");
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });

    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("closes and stays closed once a research job is running", async () => {
    searchStocks.mockResolvedValue(resultOf([suggestion()]));
    const { rerender } = render(<Harness />);
    type("reliance");
    await screen.findByRole("option");

    rerender(<Harness disabled />);

    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("stays closed after a research job finishes", async () => {
    /** Regression: `disabled` flipping back at the end of a job re-ran the
     *  search effect and popped the list open again, over the finished brief. */
    searchStocks.mockResolvedValue(resultOf([suggestion()]));
    const { rerender } = render(<Harness />);
    type("reliance");
    await screen.findByRole("option");

    rerender(<Harness disabled />); // job starts
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    rerender(<Harness />); // job finishes

    await new Promise((r) => setTimeout(r, 350));
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("stays closed after the job started by a chosen suggestion finishes", async () => {
    /** Regression: picking a match writes the symbol into the box, then the
     *  job's disabled→enabled flip re-ran the search for that symbol and
     *  re-opened the list on top of the freshly rendered brief. */
    searchStocks.mockResolvedValue(resultOf([suggestion()]));
    const { rerender } = render(<Harness />);
    type("reliance");
    fireEvent.click(await screen.findByRole("option"));

    rerender(<Harness disabled />); // job runs
    rerender(<Harness />); // job finishes

    await new Promise((r) => setTimeout(r, 350));
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("searches again once the user edits a value it wrote itself", async () => {
    searchStocks.mockResolvedValue(resultOf([suggestion()]));
    render(<Harness />);
    type("reliance");
    fireEvent.click(await screen.findByRole("option"));
    searchStocks.mockClear();

    type("reliance industries");

    await waitFor(() => expect(searchStocks).toHaveBeenCalled());
    expect(await screen.findByRole("option")).toBeInTheDocument();
  });

  it("reports a detected comparison so the page can offer compare mode", async () => {
    const onComparePair = vi.fn();
    searchStocks.mockResolvedValue(resultOf([], { compare_pair: ["TCS", "INFY"] }));
    render(<Harness onComparePair={onComparePair} />);
    type("TCS vs INFY");

    await waitFor(() => expect(onComparePair).toHaveBeenCalledWith(["TCS", "INFY"]));
  });

  it("tells the user their text is still runnable when nothing matches", async () => {
    searchStocks.mockResolvedValue(resultOf([]));
    render(<Harness />);
    type("qwertyuiop");

    expect(await screen.findByText(/still run it as typed/i)).toBeInTheDocument();
  });

  it("does not search an empty box", async () => {
    render(<Harness />);
    type("   ");

    await new Promise((r) => setTimeout(r, 350));
    expect(searchStocks).not.toHaveBeenCalled();
  });

  it("keeps the typed text usable when the search request fails", async () => {
    searchStocks.mockRejectedValue(new Error("offline"));
    render(<Harness />);
    type("reliance");

    await waitFor(() => expect(searchStocks).toHaveBeenCalled());
    expect(screen.getByRole("combobox")).toHaveValue("reliance");
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });
});
