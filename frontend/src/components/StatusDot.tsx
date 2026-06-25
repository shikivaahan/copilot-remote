import clsx from "clsx";
import type { SessionStatus } from "@/types";

interface StatusDotProps {
  status: SessionStatus | "unknown";
  size?: "sm" | "md";
  title?: string;
}

const COLORS: Record<SessionStatus | "unknown", string> = {
  running: "bg-emerald-400",
  exited: "bg-neutral-500",
  errored: "bg-rose-500",
  unknown: "bg-neutral-700",
};

/**
 * Phase 6 stub. Renders a small colored circle for a session status.
 * Used by Phase 7 (DashboardPage) and beyond.
 */
export default function StatusDot({ status, size = "md", title }: StatusDotProps) {
  return (
    <span
      role="img"
      aria-label={title ?? `status: ${status}`}
      title={title ?? status}
      className={clsx(
        "inline-block rounded-full",
        COLORS[status],
        size === "sm" ? "h-2 w-2" : "h-2.5 w-2.5",
      )}
    />
  );
}
