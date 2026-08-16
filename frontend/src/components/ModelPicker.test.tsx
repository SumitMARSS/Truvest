import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ModelPicker, contextLabel } from "./ModelPicker";
import type { LlmModel, ModelCatalog } from "@/lib/api";

/**
 * The picker's contract, not its pixels: it offers only what the server says is
 * selectable, it reports a choice as null when that choice IS the default (so
 * the app keeps tracking the server's default), and it never renders a live
 * control on a provider that would reject every pick.
 */

function model(id: string, over: Partial<LlmModel> = {}): LlmModel {
  return {
    id,
    name: id.split("/").pop()!.replace(":free", ""),
    vendor: id.split("/")[0],
    context_length: 128000,
    description: "",
    free: true,
    reasoning: false,
    ...over,
  };
}

function catalog(over: Partial<ModelCatalog> = {}): ModelCatalog {
  return {
    provider: "openrouter",
    default: "openai/gpt-oss-20b:free",
    selectable: true,
    live: true,
    note: "Free-tier models on OpenRouter.",
    models: [
      model("openai/gpt-oss-20b:free", { reasoning: true }),
      model("z-ai/glm-5.2:free"),
      model("nvidia/nemotron-3-super-120b-a12b:free", { context_length: 1_000_000 }),
    ],
    ...over,
  };
}

describe("ModelPicker", () => {
  it("renders nothing when the catalog is unavailable", () => {
    // The endpoint being down must not block research — runs fall back to the
    // server default, exactly as before model selection existed.
    const { container } = render(
      <ModelPicker catalog={null} value={null} onChange={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the server default when nothing is picked", () => {
    render(<ModelPicker catalog={catalog()} value={null} onChange={() => {}} />);
    expect(screen.getByRole("button")).toHaveAccessibleName(/gpt-oss-20b/);
  });

  it("shows the user's pick over the default", () => {
    render(<ModelPicker catalog={catalog()} value="z-ai/glm-5.2:free" onChange={() => {}} />);
    expect(screen.getByRole("button")).toHaveAccessibleName(/glm-5\.2/);
  });

  it("lists every model from the catalog, grouped by vendor", () => {
    render(<ModelPicker catalog={catalog()} value={null} onChange={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /change model/i }));
    expect(screen.getAllByRole("option")).toHaveLength(3);
    expect(screen.getByText("openai")).toBeInTheDocument();
    expect(screen.getByText("nvidia")).toBeInTheDocument();
  });

  it("reports a non-default choice by id", () => {
    const onChange = vi.fn();
    render(<ModelPicker catalog={catalog()} value={null} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /change model/i }));
    fireEvent.click(screen.getByRole("option", { name: /glm-5\.2/ }));
    expect(onChange).toHaveBeenCalledWith("z-ai/glm-5.2:free");
  });

  it("reports picking the default as null, not as its id", () => {
    // Storing null keeps the app tracking whatever the server's default becomes
    // instead of freezing today's value forever.
    const onChange = vi.fn();
    render(<ModelPicker catalog={catalog()} value="z-ai/glm-5.2:free" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /change model/i }));
    fireEvent.click(screen.getByRole("option", { name: /gpt-oss-20b/ }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("marks the default and flags reasoning models", () => {
    render(<ModelPicker catalog={catalog()} value={null} onChange={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /change model/i }));
    expect(screen.getByText("Default")).toBeInTheDocument();
    expect(screen.getByText("Reasoning")).toBeInTheDocument();
  });

  it("closes on Escape without choosing", () => {
    const onChange = vi.fn();
    render(<ModelPicker catalog={catalog()} value={null} onChange={onChange} />);
    const trigger = screen.getByRole("button", { name: /change model/i });
    fireEvent.click(trigger);
    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("navigates with the keyboard and selects with Enter", () => {
    const onChange = vi.fn();
    render(<ModelPicker catalog={catalog()} value={null} onChange={onChange} />);
    const trigger = screen.getByRole("button", { name: /change model/i });
    fireEvent.keyDown(trigger, { key: "ArrowDown" }); // opens, highlights current
    fireEvent.keyDown(trigger, { key: "ArrowDown" }); // -> second model
    fireEvent.keyDown(trigger, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("z-ai/glm-5.2:free");
  });

  it("renders read-only on a provider that fixes the model", () => {
    // A control that looks live but 400s on every choice is worse than a label.
    render(
      <ModelPicker
        catalog={catalog({
          provider: "anthropic",
          selectable: false,
          default: "claude-3-5-haiku-latest",
          models: [model("claude-3-5-haiku-latest", { free: false })],
        })}
        value={null}
        onChange={() => {}}
      />,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText(/claude-3-5-haiku-latest/)).toBeInTheDocument();
  });

  it("does not open while a job is running", () => {
    render(<ModelPicker catalog={catalog()} value={null} onChange={() => {}} disabled />);
    const trigger = screen.getByRole("button", { name: /change model/i });
    expect(trigger).toBeDisabled();
    fireEvent.click(trigger);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});

describe("contextLabel", () => {
  it("abbreviates window sizes and stays silent when unknown", () => {
    expect(contextLabel(128000)).toBe("128K ctx");
    expect(contextLabel(1_000_000)).toBe("1M ctx");
    expect(contextLabel(262144)).toBe("262K ctx");
    expect(contextLabel(null)).toBeNull();
    expect(contextLabel(0)).toBeNull();
  });
});
