import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/useAuth";
import type { UserOut } from "@/types";

/**
 * Ensures the caller is authenticated. While the auth status is
 * "loading", returns null so the caller can render a spinner. If the user
 * is unauthed, navigates to /login.
 */
export function useRequireAuth(): UserOut | null {
  const { user, status } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (status === "unauthed") {
      navigate("/login", { replace: true });
    }
  }, [status, navigate]);

  if (status === "loading") {
    return null;
  }
  return user;
}
