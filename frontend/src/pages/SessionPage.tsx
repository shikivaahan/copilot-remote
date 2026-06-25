import { useRef } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { useRequireAuth } from "@/hooks/useRequireAuth";
import {
  encodeArrow,
  encodeCtrl,
} from "@/components/MobileKeyboard";
import MobileKeyboard from "@/components/MobileKeyboard";
import StatusDot from "@/components/StatusDot";
import Terminal, { type TerminalHandle } from "@/components/Terminal";
import {
  getSession,
  getSessionHealth,
  restartSession,
  stopSession,
} from "@/api/sessions";
import type { SessionStatus } from "@/types";

const REFETCH_INTERVAL_MS = 5_000;

function formatDuration(startIso: string | undefined, now: number = Date.now()): string {
  if (!startIso) return "…";
  const start = new Date(startIso).getTime();
  if (!Number.isFinite(start)) return "…";
  const total = Math.max(0, Math.floor((now - start) / 1_000));
  const days = Math.floor(total / 86_400);
  const hours = Math.floor((total % 86_400) / 3_600);
  const minutes = Math.floor((total % 3_600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export default function SessionPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const user = useRequireAuth();
  const terminalRef = useRef<TerminalHandle | null>(null);

  const sessionQuery = useQuery({
    queryKey: ["session", id],
    queryFn: () => getSession(id ?? ""),
    enabled: Boolean(id),
  });
  const healthQuery = useQuery({
    queryKey: ["session-health", id],
    queryFn: () => getSessionHealth(id ?? ""),
    enabled: Boolean(id),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
  const stopMut = useMutation({
    mutationFn: (sessionId: string) => stopSession(sessionId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["session", id] });
      await queryClient.invalidateQueries({ queryKey: ["session-health", id] });
      await queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
  const restartMut = useMutation({
    mutationFn: (sessionId: string) => restartSession(sessionId),
    onSuccess: async (newSession) => {
      await queryClient.invalidateQueries({ queryKey: ["sessions"] });
      navigate(`/sessions/${encodeURIComponent(newSession.id)}`, { replace: true });
    },
  });

  if (!user) {
    return (
      <div className="p-4 text-neutral-400" role="status">
        Loading…
      </div>
    );
  }

  if (!id) {
    return (
      <div role="alert" className="p-4 text-rose-300">
        Missing session id.
      </div>
    );
  }

  if (sessionQuery.isError) {
    return (
      <div role="alert" className="p-4 text-rose-300">
        Failed to load session:{" "}
        {sessionQuery.error instanceof Error
          ? sessionQuery.error.message
          : "Unknown error"}
      </div>
    );
  }

  const session = sessionQuery.data;
  const liveStatus: SessionStatus =
    healthQuery.data?.status ?? session?.status ?? "errored";
  const canOpenTerminal = Boolean(session) && liveStatus === "running";
  const uptime = formatDuration(session?.created_at);

  const actionError = stopMut.error ?? restartMut.error;

  return (
    <section
      className={clsx(
        "flex h-[calc(100vh-4rem)] min-h-[24rem] flex-col",
        "gap-2",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <Link
          to="/"
          className={clsx(
            "rounded border border-neutral-700 px-3 py-1 text-xs",
            "text-neutral-200 hover:bg-neutral-800",
          )}
        >
          ← Dashboard
        </Link>
        {sessionQuery.isLoading && (
          <span role="status" className="text-xs text-neutral-500">
            Loading…
          </span>
        )}
      </div>

      <div
        className={clsx(
          "flex items-center justify-between gap-3",
          "rounded border border-neutral-800 bg-neutral-900 px-3 py-2",
        )}
      >
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-semibold text-neutral-100">
            {session?.name ?? "(loading)"}
          </h1>
          <p className="truncate text-xs text-neutral-500">
            <span className="font-mono">{session?.repo ?? "…"}</span>
            <span className="mx-1.5 text-neutral-700">·</span>
            <span className="font-mono">{session?.command ?? "…"}</span>
            <span className="mx-1.5 text-neutral-700">·</span>
            <span>Uptime {uptime}</span>
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <StatusDot status={liveStatus} />
          <button
            type="button"
            onClick={() => terminalRef.current?.focus()}
            disabled={!canOpenTerminal}
            className={clsx(
              "rounded border border-neutral-700 px-3 py-1 text-xs",
              "text-neutral-200 hover:bg-neutral-800",
              "disabled:cursor-not-allowed disabled:opacity-50",
            )}
          >
            Open Terminal
          </button>
          <button
            type="button"
            onClick={() => stopMut.mutate(id)}
            disabled={!canOpenTerminal || stopMut.isPending || restartMut.isPending}
            className={clsx(
              "rounded border border-neutral-700 px-3 py-1 text-xs",
              "text-neutral-200 hover:bg-neutral-800",
              "disabled:cursor-not-allowed disabled:opacity-50",
            )}
          >
            Stop
          </button>
          <button
            type="button"
            onClick={() => restartMut.mutate(id)}
            disabled={restartMut.isPending || stopMut.isPending || !session}
            className={clsx(
              "rounded border border-neutral-700 px-3 py-1 text-xs",
              "text-neutral-200 hover:bg-neutral-800",
              "disabled:cursor-not-allowed disabled:opacity-50",
            )}
          >
            Restart
          </button>
        </div>
      </div>

      {actionError && (
        <div role="alert" className="rounded border border-rose-800 bg-rose-950/40 px-3 py-2 text-sm text-rose-200">
          Action failed: {actionError instanceof Error ? actionError.message : "Unknown error"}
        </div>
      )}

      <div
        className={clsx(
          "min-h-0 flex-1 overflow-hidden",
          "rounded border border-neutral-800 bg-black",
        )}
      >
        {canOpenTerminal ? (
          <Terminal ref={terminalRef} sessionId={id} className="h-full" />
        ) : (
          <div className="flex h-full items-center justify-center p-4 text-sm text-neutral-500" role="status">
            Session is {liveStatus}.
          </div>
        )}
      </div>

      {canOpenTerminal && (
        <MobileKeyboard
          onKey={(data) => terminalRef.current?.sendInput(data)}
          onCtrl={(letter) => terminalRef.current?.sendInput(encodeCtrl(letter))}
          onEnter={() => terminalRef.current?.sendInput("\r")}
          onArrow={(dir) => terminalRef.current?.sendInput(encodeArrow(dir))}
          onEsc={() => terminalRef.current?.sendInput("\x1b")}
          onTab={() => terminalRef.current?.sendInput("\t")}
          onSlash={() => terminalRef.current?.sendInput("/")}
        />
      )}
    </section>
  );
}
