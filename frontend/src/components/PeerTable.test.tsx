import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PeerTable } from "./PeerTable";
import type { PeerComparison } from "@/lib/api";

const comparison: PeerComparison = {
  available: true,
  sector: "IT Services",
  rows: [
    { ticker: "TCS.NS", pe_ratio: 25, market_cap: 900, is_subject: true },
    { ticker: "INFY.NS", pe_ratio: 20, market_cap: 500, is_subject: false },
    { ticker: "WIPRO.NS", pe_ratio: 15, market_cap: 300, is_subject: false },
  ],
};

function rowTickers() {
  const rows = screen.getAllByRole("row").slice(1); // skip header row
  return rows.map((r) => within(r).getAllByRole("cell")[0].textContent?.replace("●", ""));
}

describe("PeerTable", () => {
  it("shows an honest unavailable notice when comparison data isn't available", () => {
    render(<PeerTable comparison={{ available: false, reason: "Not covered yet.", rows: [] }} />);
    expect(screen.getByText(/unavailable this cycle/i)).toBeInTheDocument();
    expect(screen.getByText(/not covered yet/i)).toBeInTheDocument();
  });

  it("defaults to sorting by market cap descending", () => {
    render(<PeerTable comparison={comparison} />);
    expect(rowTickers()).toEqual(["TCS", "INFY", "WIPRO"]);
  });

  it("re-sorts ascending on second click of the same column", () => {
    render(<PeerTable comparison={comparison} />);
    const peHeader = screen.getByRole("button", { name: /p\/e/i });
    fireEvent.click(peHeader); // first click: P/E descending
    expect(rowTickers()).toEqual(["TCS", "INFY", "WIPRO"]);
    fireEvent.click(peHeader); // second click: ascending
    expect(rowTickers()).toEqual(["WIPRO", "INFY", "TCS"]);
  });

  it("visually marks the subject row", () => {
    render(<PeerTable comparison={comparison} />);
    const rows = screen.getAllByRole("row").slice(1);
    const subjectRow = rows.find((r) => within(r).queryByText("●"));
    expect(subjectRow).toBeDefined();
    expect(within(subjectRow!).getByText("TCS")).toBeInTheDocument();
  });
});
