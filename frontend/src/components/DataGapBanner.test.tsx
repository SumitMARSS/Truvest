import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataGapBanner } from "./DataGapBanner";

describe("DataGapBanner", () => {
  it("renders nothing when there are no gaps", () => {
    const { container } = render(<DataGapBanner gaps={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists every gap honestly instead of hiding them", () => {
    render(
      <DataGapBanner
        gaps={["Market data unavailable this run.", "Shareholding data unavailable this cycle."]}
      />
    );
    expect(screen.getByText(/2 sections degraded gracefully/i)).toBeInTheDocument();
    expect(screen.getByText("Market data unavailable this run.")).toBeInTheDocument();
    expect(screen.getByText("Shareholding data unavailable this cycle.")).toBeInTheDocument();
  });

  it("uses singular section wording for exactly one gap", () => {
    render(<DataGapBanner gaps={["Sector-average P/E unavailable."]} />);
    expect(screen.getByText(/1 section degraded gracefully/i)).toBeInTheDocument();
  });
});
