import { apiFetch } from "./client";
import type { UserOut } from "@/types";

export async function login(username: string, password: string): Promise<UserOut> {
  return apiFetch<UserOut>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function logout(): Promise<void> {
  await apiFetch<void>("/api/auth/logout", {
    method: "POST",
  });
}

export async function me(): Promise<UserOut | null> {
  try {
    return await apiFetch<UserOut>("/api/auth/me");
  } catch (err) {
    if (err instanceof Error && "status" in err && (err as { status: number }).status === 401) {
      return null;
    }
    throw err;
  }
}
