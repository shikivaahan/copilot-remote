import clsx from "clsx";
import type { SessionStatus } from "@/types";

interface StatusDotProps {
  status: SessionStatus;
  size?: "sm" | "md";
  /** Override the tooltip / aria-label text (defaults to `status`). */
  title?: string;
  /** Hide the inline text label next to the dot. */
  hideLabel?: boolean;
}

const DOT_COLOR: Record<SessionStatus, string> = {
  running: "bg-emerald-500",
  exited: "bg-amber-400",
  errored: "bg-rose-500",
  stopped: "bg-neutral-500",
};

const TEXT_COLOR: Record<SessionStatus, string> = {
  running: "text-emerald-300",
  exited: "text-amber-300",
  errored: "text-rose-300",
  stopped: "text-neutral-300",
};

const SIZE_DOT: Record<NonNullable<StatusDotProps["size"]>, string> = {
  sm: "h-2 w-2",
  md: "h-2.5 w-2.5",
};

/**
 * Small colored status indicator used by the dashboard and the session
 * page. Green = running, yellow = exited, red = errored, neutral = stopped.
 */
export default function StatusDot({
  status,
  size = "md",
  title,
  hideLabel = false,
}: StatusDotProps) {
  const tooltip = title ?? status;
  return (
    <span
      className="inline-flex items-center gap-1.5 align-middle"
      role="status"
      aria-label={`status: ${tooltip}`}
    >
      <span
        aria-hidden="true"
        title={tooltip}
        className={clsx(
          "inline-block shrink-0 rounded-full",
          DOT_COLOR[status],
          SIZE_DOT[size],
        )}
      />
      {!hideLabel && (
        <span
          className={clsx("text-xs uppercase tracking-wide", TEXT_COLOR[status])}
        >
          {status}
        </span>
      )}
    </span>
  );
}
