import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TrendIndicator } from "./TrendIndicator";

describe("TrendIndicator", () => {
  it("shows a dash (never a fabricated value) when value is null", () => {
    render(<TrendIndicator value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("prefixes a plus sign and renders the suffix for a positive value", () => {
    render(<TrendIndicator value={3.456} decimals={1} />);
    expect(screen.getByText("+3.5%")).toBeInTheDocument();
  });

  it("does not add a plus sign for a negative value", () => {
    render(<TrendIndicator value={-2.1} decimals={1} />);
    expect(screen.getByText("-2.1%")).toBeInTheDocument();
  });

  it("supports a custom suffix (e.g. shareholding QoQ points)", () => {
    render(<TrendIndicator value={-0.42} suffix=" pts QoQ" />);
    expect(screen.getByText("-0.42 pts QoQ")).toBeInTheDocument();
  });
});
