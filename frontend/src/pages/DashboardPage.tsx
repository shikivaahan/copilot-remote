import { useState } from "react";
import { Link } from "react-router-dom";
import clsx from "clsx";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useRequireAuth } from "@/hooks/useRequireAuth";
import {
  createSession,
  deleteSession,
  getSessionHealth,
  getSessionPreview,
  listCommands,
  listRepos,
  listSessions,
  restartSession,
  stopSession,
  type CreateSessionInput,
} from "@/api/sessions";
import { ApiError } from "@/api/client";
import StatusDot from "@/components/StatusDot";
import type { SessionOut } from "@/types";

const REFETCH_INTERVAL_MS = 5_000;

function relativeTime(iso: string, now: number = Date.now()): string {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "—";
  const diff = Math.max(0, now - t);
  const sec = Math.floor(diff / 1_000);
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  return new Date(iso).toLocaleDateString();
}

function previewLines(text: string, maxLines = 3): string {
  const lines = text.replace(/\r/g, "").split("\n");
  // Drop trailing blank lines.
  while (lines.length > 0 && lines[lines.length - 1].trim() === "") {
    lines.pop();
  }
  return lines.slice(-maxLines).join("\n");
}

interface CreateSessionModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

function CreateSessionModal({ open, onClose, onCreated }: CreateSessionModalProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [repo, setRepo] = useState("");
  const [command, setCommand] = useState("");

  const reposQuery = useQuery({
    queryKey: ["repos"],
    queryFn: listRepos,
    enabled: open,
  });
  const commandsQuery = useQuery({
    queryKey: ["commands"],
    queryFn: listCommands,
    enabled: open,
  });

  const createMut = useMutation({
    mutationFn: (input: CreateSessionInput) => createSession(input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
      setName("");
      setRepo("");
      setCommand("");
      onCreated();
      onClose();
    },
  });

  if (!open) return null;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !repo || !command) return;
    createMut.mutate({ name: name.trim(), repo, command });
  };

  const repos = reposQuery.data ?? [];
  const commands = commandsQuery.data ?? [];

  return (
    <div
      className="fixed inset-0 z-30 flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-session-title"
    >
      <form
        onSubmit={submit}
        className={clsx(
          "w-full max-w-md rounded-t-lg border border-neutral-800",
          "bg-neutral-900 p-5 shadow-xl sm:rounded-lg",
        )}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2
            id="create-session-title"
            className="text-base font-semibold tracking-tight"
          >
            Create session
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
          >
            ✕
          </button>
        </div>

        {createMut.isError && (
          <div
            role="alert"
            className="mb-3 rounded border border-rose-800 bg-rose-950/40 px-3 py-2 text-sm text-rose-200"
          >
            {createMut.error instanceof ApiError
              ? createMut.error.message
              : "Failed to create session."}
          </div>
        )}

        <div className="mb-3">
          <label
            htmlFor="cs-name"
            className="mb-1 block text-xs uppercase tracking-wide text-neutral-400"
          >
            Name <span className="text-rose-400">*</span>
          </label>
          <input
            id="cs-name"
            name="name"
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={createMut.isPending}
            placeholder="e.g. SparseIR refactor"
            className={clsx(
              "w-full rounded border border-neutral-700 bg-neutral-950 px-3 py-2",
              "text-sm text-neutral-100 placeholder:text-neutral-600",
              "focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500",
              "disabled:opacity-50",
            )}
          />
        </div>

        <div className="mb-3">
          <label
            htmlFor="cs-repo"
            className="mb-1 block text-xs uppercase tracking-wide text-neutral-400"
          >
            Repository <span className="text-rose-400">*</span>
          </label>
          <select
            id="cs-repo"
            name="repo"
            required
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            disabled={createMut.isPending || reposQuery.isLoading}
            className={clsx(
              "w-full rounded border border-neutral-700 bg-neutral-950 px-3 py-2",
              "text-sm text-neutral-100",
              "focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500",
              "disabled:opacity-50",
            )}
          >
            <option value="">Select a repository…</option>
            {repos.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>

        <div className="mb-5">
          <label
            htmlFor="cs-command"
            className="mb-1 block text-xs uppercase tracking-wide text-neutral-400"
          >
            Command <span className="text-rose-400">*</span>
          </label>
          <select
            id="cs-command"
            name="command"
            required
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            disabled={createMut.isPending || commandsQuery.isLoading}
            className={clsx(
              "w-full rounded border border-neutral-700 bg-neutral-950 px-3 py-2",
              "text-sm text-neutral-100",
              "focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500",
              "disabled:opacity-50",
            )}
          >
            <option value="">Select a command…</option>
            {commands.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={createMut.isPending}
            className={clsx(
              "rounded border border-neutral-700 px-3 py-2 text-sm",
              "text-neutral-200 hover:bg-neutral-800",
              "disabled:opacity-50",
            )}
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={createMut.isPending || !name.trim() || !repo || !command}
            className={clsx(
              "rounded bg-emerald-500 px-4 py-2 text-sm font-semibold text-neutral-950",
              "hover:bg-emerald-400 active:bg-emerald-300",
              "disabled:cursor-not-allowed disabled:opacity-50",
            )}
          >
            {createMut.isPending ? "Creating…" : "Create"}
          </button>
        </div>
      </form>
    </div>
  );
}

interface SessionCardProps {
  session: SessionOut;
  onStop: (id: string) => void;
  onRestart: (id: string) => void;
  onDelete: (id: string) => void;
}

function SessionCard({ session, onStop, onRestart, onDelete }: SessionCardProps) {
  const healthQuery = useQuery({
    queryKey: ["session-health", session.id],
    queryFn: () => getSessionHealth(session.id),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
  const previewQuery = useQuery({
    queryKey: ["session-preview", session.id],
    queryFn: () => getSessionPreview(session.id),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const liveStatus = healthQuery.data?.status ?? session.status;
  const lastActivity =
    healthQuery.data?.last_activity_at ?? session.last_activity_at;
  const previewText = previewQuery.data?.text ?? "";

  return (
    <article
      data-testid={`session-card-${session.id}`}
      className={clsx(
        "rounded-lg border border-neutral-800 bg-neutral-900 p-4",
        "transition-colors hover:border-neutral-700",
      )}
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <Link
            to={`/sessions/${encodeURIComponent(session.id)}`}
            className="block"
          >
            <h2 className="truncate text-base font-semibold text-neutral-100 hover:text-emerald-300">
              {session.name}
            </h2>
          </Link>
          <p className="mt-0.5 truncate text-xs text-neutral-500">
            <span className="font-mono">{session.repo}</span>
            <span className="mx-1.5 text-neutral-700">·</span>
            <span className="font-mono">{session.command}</span>
          </p>
        </div>
        <StatusDot status={liveStatus} />
      </header>

      <div className="mt-2 grid gap-0.5 text-xs text-neutral-500 sm:grid-cols-2">
        <p>Created {relativeTime(session.created_at)}</p>
        <p>Active {relativeTime(lastActivity)}</p>
      </div>

      <pre
        className={clsx(
          "mt-3 max-h-24 overflow-hidden whitespace-pre-wrap break-words",
          "rounded border border-neutral-800 bg-neutral-950 p-2",
          "font-mono text-xs text-neutral-300",
        )}
        aria-label="Session preview"
      >
        {previewText ? previewLines(previewText) : (
          <span className="text-neutral-600">(no output yet)</span>
        )}
      </pre>

      <div className="mt-3 flex flex-wrap gap-2">
        <Link
          to={`/sessions/${encodeURIComponent(session.id)}`}
          className={clsx(
            "rounded border border-neutral-700 px-3 py-1 text-xs",
            "text-neutral-100 hover:bg-neutral-800",
          )}
        >
          Open
        </Link>
        <button
          type="button"
          onClick={() => onStop(session.id)}
          className={clsx(
            "rounded border border-neutral-700 px-3 py-1 text-xs",
            "text-neutral-200 hover:bg-neutral-800",
          )}
        >
          Stop
        </button>
        <button
          type="button"
          onClick={() => onRestart(session.id)}
          className={clsx(
            "rounded border border-neutral-700 px-3 py-1 text-xs",
            "text-neutral-200 hover:bg-neutral-800",
          )}
        >
          Restart
        </button>
        <button
          type="button"
          onClick={() => {
            if (
              window.confirm(
                `Delete session "${session.name}"? This is irreversible.`,
              )
            ) {
              onDelete(session.id);
            }
          }}
          className={clsx(
            "rounded border border-rose-800 px-3 py-1 text-xs",
            "text-rose-300 hover:bg-rose-950",
          )}
        >
          Delete
        </button>
      </div>
    </article>
  );
}

function SessionCardSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading sessions"
      className={clsx(
        "rounded-lg border border-neutral-800 bg-neutral-900 p-4",
        "animate-pulse",
      )}
    >
      <div className="h-4 w-1/2 rounded bg-neutral-800" />
      <div className="mt-2 h-3 w-2/3 rounded bg-neutral-800" />
      <div className="mt-3 h-12 rounded bg-neutral-800" />
    </div>
  );
}

export default function DashboardPage() {
  const user = useRequireAuth();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);

  const sessionsQuery = useQuery({
    queryKey: ["sessions"],
    queryFn: listSessions,
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const stopMut = useMutation({
    mutationFn: (id: string) => stopSession(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
  const restartMut = useMutation({
    mutationFn: (id: string) => restartSession(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteSession(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });

  if (!user) {
    return (
      <div className="p-4 text-neutral-400" role="status">
        Loading…
      </div>
    );
  }

  const sessions = sessionsQuery.data ?? [];
  const isLoading = sessionsQuery.isLoading && sessions.length === 0;
  const isEmpty = !isLoading && sessions.length === 0;

  return (
    <section className="space-y-4">
      <header className="flex items-center justify-between gap-3">
        <h1 className="text-base font-semibold tracking-tight">
          Welcome, <span className="text-neutral-100">@{user.username}</span>.
        </h1>
        <button
          type="button"
          onClick={() => setCreateOpen(true)}
          data-testid="create-session-button"
          className={clsx(
            "rounded bg-emerald-500 px-3 py-2 text-sm font-semibold text-neutral-950",
            "hover:bg-emerald-400 active:bg-emerald-300",
            "transition-colors",
          )}
        >
          + Create session
        </button>
      </header>

      {(stopMut.isError || restartMut.isError || deleteMut.isError) && (
        <div
          role="alert"
          className="rounded border border-rose-800 bg-rose-950/40 px-3 py-2 text-sm text-rose-200"
        >
          Action failed:{" "}
          {((stopMut.error ?? restartMut.error ?? deleteMut.error) as Error)
            ?.message ?? "Unknown error"}
        </div>
      )}

      {isLoading && (
        <div
          className="grid gap-3"
          aria-busy="true"
          data-testid="dashboard-loading"
        >
          <SessionCardSkeleton />
          <SessionCardSkeleton />
          <SessionCardSkeleton />
        </div>
      )}

      {isEmpty && (
        <div
          data-testid="dashboard-empty"
          className={clsx(
            "rounded-lg border border-dashed border-neutral-700",
            "bg-neutral-900/50 p-8 text-center",
          )}
        >
          <p className="text-sm text-neutral-300">
            No sessions yet. Click "Create session" to start one.
          </p>
        </div>
      )}

      {!isLoading && !isEmpty && (
        <div className="grid gap-3" data-testid="dashboard-list">
          {sessions.map((s) => (
            <SessionCard
              key={s.id}
              session={s}
              onStop={(id) => stopMut.mutate(id)}
              onRestart={(id) => restartMut.mutate(id)}
              onDelete={(id) => deleteMut.mutate(id)}
            />
          ))}
        </div>
      )}

      <CreateSessionModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => {
          void queryClient.invalidateQueries({ queryKey: ["sessions"] });
        }}
      />
    </section>
  );
}
