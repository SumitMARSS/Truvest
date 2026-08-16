import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConfidenceBadge } from "./ConfidenceBadge";

describe("ConfidenceBadge", () => {
  it("renders nothing when level is missing", () => {
    const { container } = render(<ConfidenceBadge level={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the high-confidence label and reason as a tooltip", () => {
    render(<ConfidenceBadge level="high" reason="Direct pull from yfinance." />);
    const badge = screen.getByText(/high confidence/i);
    expect(badge).toBeInTheDocument();
    expect(badge.closest("span")).toHaveAttribute("title", "Direct pull from yfinance.");
  });

  it("renders distinct labels for medium and low", () => {
    const { rerender } = render(<ConfidenceBadge level="medium" />);
    expect(screen.getByText(/medium confidence/i)).toBeInTheDocument();
    rerender(<ConfidenceBadge level="low" />);
    expect(screen.getByText(/low confidence/i)).toBeInTheDocument();
  });
});
