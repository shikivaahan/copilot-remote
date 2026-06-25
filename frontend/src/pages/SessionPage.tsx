import { useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
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
} from "@/api/sessions";
import type { SessionStatus } from "@/types";

const REFETCH_INTERVAL_MS = 5_000;

export default function SessionPage() {
  const { id } = useParams<{ id: string }>();
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
          </p>
        </div>
        <StatusDot status={liveStatus} />
      </div>

      <div
        className={clsx(
          "min-h-0 flex-1 overflow-hidden",
          "rounded border border-neutral-800 bg-black",
        )}
      >
        <Terminal ref={terminalRef} sessionId={id} className="h-full" />
      </div>

      <MobileKeyboard
        onKey={(data) => terminalRef.current?.sendInput(data)}
        onCtrl={(letter) => terminalRef.current?.sendInput(encodeCtrl(letter))}
        onEnter={() => terminalRef.current?.sendInput("\r")}
        onArrow={(dir) => terminalRef.current?.sendInput(encodeArrow(dir))}
        onEsc={() => terminalRef.current?.sendInput("\x1b")}
        onTab={() => terminalRef.current?.sendInput("\t")}
        onSlash={() => terminalRef.current?.sendInput("/")}
      />
    </section>
  );
}
