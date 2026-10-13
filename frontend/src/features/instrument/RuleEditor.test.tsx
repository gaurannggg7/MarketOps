import { fetchMock, mutations, resetNetwork, routes } from "../../test/network";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import type { Schemas } from "../../lib/api/client";
import { errorResponse, ruleFixture } from "../../test/fixtures";
import { RuleEditor } from "./RuleEditor";

function renderEditor(rule: Schemas["RuleOut"], canEdit: boolean) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <RuleEditor rule={rule} canEdit={canEdit} />
    </QueryClientProvider>,
  );
}

describe("RuleEditor", () => {
  beforeEach(() => {
    resetNetwork();
  });

  it("shows the bound message for an invalid threshold and does not submit", async () => {
    const user = userEvent.setup();
    renderEditor(ruleFixture({ rule_type: "STALE", threshold: "30" }), true);
    const input = screen.getByLabelText(/threshold/i);
    await user.clear(input);
    await user.type(input, "5000");
    expect(await screen.findByText("Threshold must be between 1 and 3600 seconds.")).toBeInTheDocument();
    expect(input).toHaveAttribute("aria-invalid", "true");
    await user.click(screen.getByRole("button", { name: "Save rule" }));
    expect(screen.getByText("Threshold must be between 1 and 3600 seconds.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("validates blank input for a wide-spread rule", async () => {
    const user = userEvent.setup();
    renderEditor(ruleFixture({ rule_type: "WIDE_SPREAD", unit: "BPS", threshold: "25" }), true);
    await user.clear(screen.getByLabelText(/threshold/i));
    expect(await screen.findByText("Enter a threshold.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends the patch with the current version for a valid change", async () => {
    const user = userEvent.setup();
    const bodies: unknown[] = [];
    routes(async ({ method, request }) => {
      if (method === "PATCH") {
        bodies.push(await request.json());
        return new Response(JSON.stringify(ruleFixture({ threshold: "45", version: 4 })), { status: 200, headers: { "content-type": "application/json" } });
      }
      return errorResponse(404, "NOT_FOUND", "nope");
    });
    renderEditor(ruleFixture({ threshold: "30", version: 3 }), true);
    const input = screen.getByLabelText(/threshold/i);
    await user.clear(input);
    await user.type(input, "45");
    await user.click(screen.getByRole("button", { name: "Save rule" }));
    expect(await screen.findByText(/New rule version v4/)).toBeInTheDocument();
    expect(bodies).toEqual([{ version: 3, threshold: "45", enabled: null }]);
  });

  it("shows a version conflict notice with a reload button", async () => {
    const user = userEvent.setup();
    routes(({ method }) => (method === "PATCH" ? errorResponse(409, "VERSION_CONFLICT", "Rule is at version 5.") : errorResponse(404, "NOT_FOUND", "nope")));
    renderEditor(ruleFixture(), true);
    const input = screen.getByLabelText(/threshold/i);
    await user.clear(input);
    await user.type(input, "60");
    await user.click(screen.getByRole("button", { name: "Save rule" }));
    expect(await screen.findByText("Someone else changed this rule.")).toBeInTheDocument();
    expect(screen.getByText("Rule is at version 5.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload latest rule" })).toBeInTheDocument();
    expect(mutations()).toHaveLength(1);
  });

  it("is read-only for viewers", () => {
    renderEditor(ruleFixture(), false);
    expect(screen.getByLabelText(/threshold/i)).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Enabled" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /save/i })).not.toBeInTheDocument();
    expect(screen.getByText(/Viewers can read rules/)).toBeInTheDocument();
  });
});
