import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import * as authApi from "@/api/auth";
import type { UserOut } from "@/types";

export type AuthStatus = "loading" | "authed" | "unauthed";

export interface AuthContextValue {
  user: UserOut | null;
  status: AuthStatus;
  login: (username: string, password: string) => Promise<UserOut>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<UserOut | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const me = await authApi.me();
        if (cancelled) return;
        if (me) {
          setUser(me);
          setStatus("authed");
        } else {
          setUser(null);
          setStatus("unauthed");
        }
      } catch {
        if (cancelled) return;
        setUser(null);
        setStatus("unauthed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(
    async (username: string, password: string): Promise<UserOut> => {
      const next = await authApi.login(username, password);
      setUser(next);
      setStatus("authed");
      return next;
    },
    [],
  );

  const logout = useCallback(async (): Promise<void> => {
    try {
      await authApi.logout();
    } finally {
      setUser(null);
      setStatus("unauthed");
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, status, login, logout }),
    [user, status, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
