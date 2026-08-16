import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ResearchStudio } from "./ResearchStudio";
import type { ModelCatalog } from "@/lib/api";

/**
 * The wiring between the picker and the job: choosing a model has to actually
 * reach `startResearch`, survive a reload, and quietly drop itself when the
 * model it names is gone. Each of those is a place the choice could silently
 * stop mattering while the UI still shows it.
 */

const listModels = vi.hoisted(() => vi.fn());
const startResearch = vi.hoisted(() => vi.fn());
const getResearch = vi.hoisted(() => vi.fn());
const searchStocks = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({ listModels, startResearch, getResearch, searchStocks }));

const CATALOG: ModelCatalog = {
  provider: "openrouter",
  default: "openai/gpt-oss-20b:free",
  selectable: true,
  live: true,
  note: "Free models on OpenRouter.",
  models: [
    {
      id: "openai/gpt-oss-20b:free",
      name: "gpt-oss-20b",
      vendor: "OpenAI",
      context_length: 131072,
      description: "",
      free: true,
      reasoning: true,
    },
    {
      id: "z-ai/glm-5.2:free",
      name: "GLM 5.2",
      vendor: "Z.AI",
      context_length: 128000,
      description: "",
      free: true,
      reasoning: false,
    },
  ],
};

beforeEach(() => {
  localStorage.clear();
  listModels.mockResolvedValue(CATALOG);
  searchStocks.mockResolvedValue({ query: "", suggestions: [], layers_used: [], compare_pair: null });
  startResearch.mockResolvedValue({
    job_id: "j1",
    status: "completed",
    query: "RELIANCE",
    mode: "single",
    model: "z-ai/glm-5.2:free",
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

async function openPicker() {
  const trigger = await screen.findByRole("button", { name: /change model/i });
  fireEvent.click(trigger);
  return trigger;
}

describe("ResearchStudio model selection", () => {
  it("runs on the server default until the user picks something", async () => {
    render(<ResearchStudio />);
    await screen.findByRole("button", { name: /change model/i });
    fireEvent.click(screen.getByRole("button", { name: /run research/i }));
    await waitFor(() => expect(startResearch).toHaveBeenCalled());
    // null, not the default's id — the server decides what the default is.
    expect(startResearch).toHaveBeenCalledWith("RELIANCE", null);
  });

  it("sends the picked model with the job", async () => {
    render(<ResearchStudio />);
    await openPicker();
    fireEvent.click(screen.getByRole("option", { name: /GLM 5\.2/ }));
    fireEvent.click(screen.getByRole("button", { name: /run research/i }));
    await waitFor(() => expect(startResearch).toHaveBeenCalledWith("RELIANCE", "z-ai/glm-5.2:free"));
  });

  it("remembers the pick across a remount", async () => {
    const first = render(<ResearchStudio />);
    await openPicker();
    fireEvent.click(screen.getByRole("option", { name: /GLM 5\.2/ }));
    first.unmount();

    render(<ResearchStudio />);
    expect(await screen.findByRole("button", { name: /GLM 5\.2/ })).toBeInTheDocument();
  });

  it("drops a stored model the server no longer offers", async () => {
    // Free models get retired; sending a stale id would 400 on every run.
    localStorage.setItem("truvest:model", "retired/model:free");
    render(<ResearchStudio />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /change model/i })).toHaveAccessibleName(
        /gpt-oss-20b/,
      ),
    );
    expect(localStorage.getItem("truvest:model")).toBeNull();
  });

  it("keeps working when the model endpoint is unavailable", async () => {
    listModels.mockResolvedValue(null);
    render(<ResearchStudio />);
    fireEvent.click(screen.getByRole("button", { name: /run research/i }));
    await waitFor(() => expect(startResearch).toHaveBeenCalledWith("RELIANCE", null));
    expect(screen.queryByRole("button", { name: /change model/i })).not.toBeInTheDocument();
  });

  it("surfaces the backend's reason when a model is rejected", async () => {
    startResearch.mockRejectedValue(new Error("'openai/gpt-4o' is not an available model."));
    render(<ResearchStudio />);
    fireEvent.click(screen.getByRole("button", { name: /run research/i }));
    expect(await screen.findByText(/is not an available model/)).toBeInTheDocument();
  });
});
