import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import * as authApi from "@/api/auth";
import type { UserOut } from "@/types";
import { AuthProvider, AuthContext } from "./AuthContext";
import { useAuth } from "./useAuth";

vi.mock("@/api/auth", () => ({
  me: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}));

const mockedAuthApi = authApi as unknown as {
  me: ReturnType<typeof vi.fn>;
  login: ReturnType<typeof vi.fn>;
  logout: ReturnType<typeof vi.fn>;
};

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    );
  };
}

function makeUser(overrides: Partial<UserOut> = {}): UserOut {
  return {
    id: 1,
    username: "alice",
    created_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("AuthContext", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("starts in loading status then transitions to unauthed when /me rejects with 401", async () => {
    const authError = Object.assign(new Error("unauthorized"), { status: 401 });
    mockedAuthApi.me.mockRejectedValueOnce(authError);

    const wrapper = makeWrapper();
    const { result } = renderHook(() => useAuth(), { wrapper });

    expect(result.current.status).toBe("loading");

    await waitFor(() => {
      expect(result.current.status).toBe("unauthed");
    });
    expect(result.current.user).toBeNull();
  });

  it("transitions to authed when /me returns a user", async () => {
    const user = makeUser({ username: "bob" });
    mockedAuthApi.me.mockResolvedValueOnce(user);

    const wrapper = makeWrapper();
    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => {
      expect(result.current.status).toBe("authed");
    });
    expect(result.current.user).toEqual(user);
  });

  it("login() updates the context to authed with the returned user", async () => {
    mockedAuthApi.me.mockResolvedValueOnce(null);
    const user = makeUser({ username: "carol" });
    mockedAuthApi.login.mockResolvedValueOnce(user);

    let ctxValue: React.ContextType<typeof AuthContext> | undefined;
    function Probe() {
      ctxValue = useAuth();
      return null;
    }

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <Probe />
        </AuthProvider>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(ctxValue?.status).toBe("unauthed");
    });

    await act(async () => {
      await ctxValue!.login("carol", "hunter2");
    });

    expect(ctxValue?.status).toBe("authed");
    expect(ctxValue?.user).toEqual(user);
    expect(mockedAuthApi.login).toHaveBeenCalledWith("carol", "hunter2");
  });
});
