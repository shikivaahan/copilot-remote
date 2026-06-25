import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import clsx from "clsx";
import { useAuth } from "@/auth/useAuth";
import { ApiError } from "@/api/client";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      await login(username, password);
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        setError("Invalid username or password.");
      } else if (err instanceof Error) {
        setError(err.message || "Sign-in failed.");
      } else {
        setError("Sign-in failed.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-950 px-4 font-mono text-neutral-100">
      <form
        onSubmit={handleSubmit}
        className={clsx(
          "w-full max-w-sm rounded-lg border border-neutral-800",
          "bg-neutral-900 p-6 shadow-lg",
        )}
        noValidate
      >
        <h1 className="mb-1 text-lg font-semibold tracking-tight">
          Copilot Remote
        </h1>
        <p className="mb-6 text-xs text-neutral-500">Sign in to continue.</p>

        {error && (
          <div
            role="alert"
            className="mb-4 rounded border border-rose-800 bg-rose-950/40 px-3 py-2 text-sm text-rose-200"
          >
            {error}
          </div>
        )}

        <div className="mb-4">
          <label
            htmlFor="username"
            className="mb-1 block text-xs uppercase tracking-wide text-neutral-400"
          >
            Username
          </label>
          <input
            id="username"
            name="username"
            type="text"
            autoComplete="username"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={pending}
            aria-invalid={error ? "true" : "false"}
            className={clsx(
              "w-full rounded border border-neutral-700 bg-neutral-950 px-3 py-2",
              "text-sm text-neutral-100 placeholder:text-neutral-600",
              "focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500",
              "disabled:opacity-50",
            )}
          />
        </div>

        <div className="mb-6">
          <label
            htmlFor="password"
            className="mb-1 block text-xs uppercase tracking-wide text-neutral-400"
          >
            Password
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={pending}
            aria-invalid={error ? "true" : "false"}
            className={clsx(
              "w-full rounded border border-neutral-700 bg-neutral-950 px-3 py-2",
              "text-sm text-neutral-100 placeholder:text-neutral-600",
              "focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500",
              "disabled:opacity-50",
            )}
          />
        </div>

        <button
          type="submit"
          disabled={pending || !username || !password}
          className={clsx(
            "w-full rounded bg-emerald-500 px-3 py-2 text-sm font-semibold text-neutral-950",
            "hover:bg-emerald-400 active:bg-emerald-300",
            "disabled:cursor-not-allowed disabled:opacity-50",
            "transition-colors",
          )}
        >
          {pending ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
