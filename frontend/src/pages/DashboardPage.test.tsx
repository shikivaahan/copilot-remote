import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import * as sessionsApi from "@/api/sessions";
import type {
  SessionHealth,
  SessionOut,
  SessionPreview,
} from "@/types";

// Mock useRequireAuth so we can drive the user state from the test.
vi.mock("@/hooks/useRequireAuth", () => ({
  useRequireAuth: () => ({ id: 1, username: "alice", created_at: "" }),
}));

vi.mock("@/api/sessions", () => ({
  listSessions: vi.fn(),
  listRepos: vi.fn(),
  listCommands: vi.fn(),
  getSession: vi.fn(),
  getSessionHealth: vi.fn(),
  getSessionPreview: vi.fn(),
  createSession: vi.fn(),
  stopSession: vi.fn(),
  restartSession: vi.fn(),
  deleteSession: vi.fn(),
}));

const mocked = sessionsApi as unknown as {
  listSessions: ReturnType<typeof vi.fn>;
  listRepos: ReturnType<typeof vi.fn>;
  listCommands: ReturnType<typeof vi.fn>;
  getSessionHealth: ReturnType<typeof vi.fn>;
  getSessionPreview: ReturnType<typeof vi.fn>;
  createSession: ReturnType<typeof vi.fn>;
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

function makePreview(overrides: Partial<SessionPreview> = {}): SessionPreview {
  return { id: "s-1", text: "", bytes: 0, ...overrides };
}

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  };
}

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.listRepos.mockResolvedValue([
      "/home/user/projects/test",
      "/home/user/projects/other",
    ]);
    mocked.listCommands.mockResolvedValue(["bash", "copilot"]);
    mocked.getSessionHealth.mockResolvedValue(makeHealth());
    mocked.getSessionPreview.mockResolvedValue(makePreview());
  });

  it("renders a welcome header for the logged-in user", async () => {
    mocked.listSessions.mockResolvedValue([]);
    const Wrapper = makeWrapper();
    render(<Dashboard />, { wrapper: Wrapper });
    const heading = await screen.findByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent(/Welcome, @alice\./);
  });

  it("shows the empty state when there are no sessions", async () => {
    mocked.listSessions.mockResolvedValue([]);
    const Wrapper = makeWrapper();
    render(<Dashboard />, { wrapper: Wrapper });
    expect(
      await screen.findByTestId("dashboard-empty"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/No sessions yet\./i),
    ).toBeInTheDocument();
  });

  it("renders one card per session", async () => {
    mocked.listSessions.mockResolvedValue([
      makeSession({ id: "a", name: "Alpha" }),
      makeSession({ id: "b", name: "Bravo" }),
    ]);
    const Wrapper = makeWrapper();
    render(<Dashboard />, { wrapper: Wrapper });
    expect(
      await screen.findByTestId("session-card-a"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("session-card-b")).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Bravo")).toBeInTheDocument();
  });

  it("opens the create-session modal when the button is clicked", async () => {
    mocked.listSessions.mockResolvedValue([]);
    const Wrapper = makeWrapper();
    render(<Dashboard />, { wrapper: Wrapper });

    const btn = await screen.findByTestId("create-session-button");
    fireEvent.click(btn);

    expect(
      screen.getByRole("dialog", { name: /create session/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/^Name/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Repository/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Command/)).toBeInTheDocument();
  });

  it("submits the create form and calls createSession", async () => {
    const user = userEvent.setup();
    mocked.listSessions.mockResolvedValue([]);
    mocked.createSession.mockResolvedValue(
      makeSession({ id: "new", name: "Hello" }),
    );
    const Wrapper = makeWrapper();
    render(<Dashboard />, { wrapper: Wrapper });

    await user.click(await screen.findByTestId("create-session-button"));

    const nameInput = screen.getByLabelText(/^Name/) as HTMLInputElement;
    const repoSelect = screen.getByLabelText(/Repository/) as HTMLSelectElement;
    const commandSelect = screen.getByLabelText(/Command/) as HTMLSelectElement;

    await user.type(nameInput, "Hello");
    await user.selectOptions(repoSelect, "/home/user/projects/test");
    await user.selectOptions(commandSelect, "bash");

    const form = screen.getByRole("dialog").querySelector("form")!;
    fireEvent.submit(form);

    await waitFor(() => {
      expect(mocked.createSession).toHaveBeenCalledWith({
        name: "Hello",
        repo: "/home/user/projects/test",
        command: "bash",
      });
    });
  });
});

// Late import so the mocks above are registered before module evaluation.
import Dashboard from "./DashboardPage";
