import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { forwardRef, type ReactNode } from "react";
import * as sessionsApi from "@/api/sessions";
import type { SessionHealth, SessionOut } from "@/types";

vi.mock("@/hooks/useRequireAuth", () => ({
  useRequireAuth: () => ({ id: 1, username: "alice", created_at: "" }),
}));

vi.mock("@/components/Terminal", () => ({
  default: forwardRef(() => <div data-testid="terminal-mock" />),
}));

vi.mock("@/components/MobileKeyboard", async () => {
  const actual = await vi.importActual<typeof import("@/components/MobileKeyboard")>(
    "@/components/MobileKeyboard",
  );
  return {
    ...actual,
    default: () => <div data-testid="keyboard-mock" />,
  };
});

vi.mock("@/api/sessions", () => ({
  getSession: vi.fn(),
  getSessionHealth: vi.fn(),
  stopSession: vi.fn(),
  restartSession: vi.fn(),
}));

const mocked = sessionsApi as unknown as {
  getSession: ReturnType<typeof vi.fn>;
  getSessionHealth: ReturnType<typeof vi.fn>;
  stopSession: ReturnType<typeof vi.fn>;
  restartSession: ReturnType<typeof vi.fn>;
};

function makeSession(overrides: Partial<SessionOut> = {}): SessionOut {
  return {
    id: "s-1",
    name: "Test session",
    repo: "/home/user/projects/test",
    command: "bash",
    status: "running",
    created_at: "2025-01-01T00:00:00Z",
    last_activity_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeHealth(overrides: Partial<SessionHealth> = {}): SessionHealth {
  return {
    id: "s-1",
    status: "running",
    tmux_session_exists: true,
    process_alive: true,
    active_connections: 0,
    last_activity_at: "2025-01-01T00:00:00Z",
    output_buffer_bytes: 0,
    ...overrides,
  };
}

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/sessions/s-1"]}>
          <Routes>
            <Route path="/sessions/:id" element={children} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
  };
}

describe("SessionPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.getSession.mockResolvedValue(makeSession());
    mocked.getSessionHealth.mockResolvedValue(makeHealth());
    mocked.stopSession.mockResolvedValue(undefined);
    mocked.restartSession.mockResolvedValue(makeSession({ id: "s-2" }));
  });

  it("renders uptime and terminal controls for a running session", async () => {
    const Wrapper = makeWrapper();
    render(<SessionPage />, { wrapper: Wrapper });
    expect(await screen.findByText("Test session")).toBeInTheDocument();
    expect(screen.getByText(/Uptime/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Restart" })).toBeEnabled();
    expect(screen.getByTestId("terminal-mock")).toBeInTheDocument();
    expect(screen.getByTestId("keyboard-mock")).toBeInTheDocument();
  });

  it("calls stopSession from the detail page", async () => {
    const user = userEvent.setup();
    const Wrapper = makeWrapper();
    render(<SessionPage />, { wrapper: Wrapper });
    await user.click(await screen.findByRole("button", { name: "Stop" }));
    await waitFor(() => {
      expect(mocked.stopSession).toHaveBeenCalledWith("s-1");
    });
  });

  it("does not mount terminal controls for a stopped session", async () => {
    mocked.getSession.mockResolvedValue(makeSession({ status: "stopped" }));
    mocked.getSessionHealth.mockResolvedValue(
      makeHealth({
        status: "stopped",
        tmux_session_exists: false,
        process_alive: false,
      }),
    );
    const Wrapper = makeWrapper();
    render(<SessionPage />, { wrapper: Wrapper });
    expect(await screen.findByText("Session is stopped.")).toBeInTheDocument();
    expect(screen.queryByTestId("terminal-mock")).not.toBeInTheDocument();
    expect(screen.queryByTestId("keyboard-mock")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeDisabled();
  });
});

import SessionPage from "./SessionPage";
