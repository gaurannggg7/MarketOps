import { mutations, resetNetwork, routes } from "../../test/network";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import type { Schemas } from "../../lib/api/client";
import { AuthContext, type AuthValue } from "../../lib/auth";
import { errorResponse, incidentFixture, jsonResponse, userFixture } from "../../test/fixtures";
import { IncidentActions } from "./IncidentDetailPage";

function renderActions(incident: Schemas["IncidentDetail"], isOperator: boolean) {
  const auth: AuthValue = {
    user: userFixture(isOperator ? "OPERATOR" : "VIEWER"),
    loading: false,
    error: null,
    retry: () => undefined,
    isOperator,
    login: () => Promise.resolve(),
    logout: () => Promise.resolve(),
  };
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={auth}>
        <IncidentActions incident={incident} />
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
}

describe("IncidentActions", () => {
  beforeEach(() => {
    resetNetwork();
    routes(({ method, path }) => {
      if (method === "GET" && path.endsWith("/auth/operators")) return jsonResponse([]);
      return errorResponse(404, "NOT_FOUND", "unexpected");
    });
  });

  it("shows a read-only message and no actions to viewers", () => {
    renderActions(incidentFixture(), false);
    expect(screen.getByText(/signed in as a viewer \(read-only\)/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("lets operators acknowledge an OPEN incident but blocks resolving", () => {
    renderActions(incidentFixture({ status: "OPEN" }), true);
    expect(screen.getByRole("button", { name: "Acknowledge" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Resolve incident" })).toBeDisabled();
    expect(screen.getByText("Acknowledge the incident before resolving it.")).toBeInTheDocument();
  });

  it("explains that an active condition blocks resolution", () => {
    renderActions(incidentFixture({ status: "ACKNOWLEDGED", condition_active: true }), true);
    expect(screen.getByText(/market condition is still active/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resolve incident" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Acknowledge" })).toBeDisabled();
  });

  it("requires a resolution note before resolving a recovered incident", async () => {
    const user = userEvent.setup();
    renderActions(incidentFixture({ status: "ACKNOWLEDGED", condition_active: false }), true);
    const resolve = screen.getByRole("button", { name: "Resolve incident" });
    expect(resolve).toBeEnabled();
    await user.click(resolve);
    expect(await screen.findByText("Describe the resolution before resolving.")).toBeInTheDocument();
    expect(mutations()).toHaveLength(0);
  });

  it("treats a whitespace-only note as blank", async () => {
    const user = userEvent.setup();
    renderActions(incidentFixture({ status: "ACKNOWLEDGED", condition_active: false }), true);
    await user.type(screen.getByLabelText(/Resolution note/), "   ");
    await user.click(screen.getByRole("button", { name: "Resolve incident" }));
    expect(await screen.findByText("Describe the resolution before resolving.")).toBeInTheDocument();
    expect(mutations()).toHaveLength(0);
  });

  it("submits the resolution with the incident version when a note is given", async () => {
    const user = userEvent.setup();
    const bodies: unknown[] = [];
    routes(async ({ method, path, request }) => {
      if (method === "GET" && path.endsWith("/auth/operators")) return jsonResponse([]);
      if (method === "POST" && path.endsWith("/resolve")) {
        bodies.push(await request.json());
        return jsonResponse(incidentFixture({ status: "RESOLVED" }));
      }
      return errorResponse(404, "NOT_FOUND", "unexpected");
    });
    renderActions(incidentFixture({ status: "ACKNOWLEDGED", condition_active: false, version: 6 }), true);
    await user.type(screen.getByLabelText(/Resolution note/), "  Feed recovered.  ");
    await user.click(screen.getByRole("button", { name: "Resolve incident" }));
    await screen.findByRole("button", { name: "Resolve incident" });
    expect(bodies).toEqual([{ version: 6, resolution_note: "Feed recovered." }]);
  });

  it("shows a conflict notice when acknowledge hits a version conflict", async () => {
    const user = userEvent.setup();
    routes(({ method, path }) => {
      if (method === "GET" && path.endsWith("/auth/operators")) return jsonResponse([]);
      if (method === "POST" && path.endsWith("/acknowledge")) return errorResponse(409, "VERSION_CONFLICT", "Incident is at version 2.");
      return errorResponse(404, "NOT_FOUND", "unexpected");
    });
    renderActions(incidentFixture({ status: "OPEN" }), true);
    await user.click(screen.getByRole("button", { name: "Acknowledge" }));
    expect(await screen.findByText("This incident changed while you were viewing it.")).toBeInTheDocument();
    expect(screen.getByText("Incident is at version 2.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload incident" })).toBeInTheDocument();
  });
});
