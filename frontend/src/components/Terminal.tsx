import {
  forwardRef,
  useImperativeHandle,
  useRef,
} from "react";
import clsx from "clsx";
import "@xterm/xterm/css/xterm.css";
import { useTerminal } from "@/hooks/useTerminal";

export interface TerminalHandle {
  sendInput: (data: string) => void;
  focus: () => void;
}

interface TerminalProps {
  sessionId: string;
  className?: string;
}

/**
 * xterm.js terminal mounted against a live WebSocket to /ws/sessions/{id}.
 *
 * Parents can drive input from outside via the ref handle (used by
 * <MobileKeyboard />). Connection state is shown as a small status bar
 * below the terminal so the user sees reconnects happening.
 */
const Terminal = forwardRef<TerminalHandle, TerminalProps>(function Terminal(
  { sessionId, className },
  ref,
) {
  const innerRef = useRef<HTMLDivElement | null>(null);
  const {
    ref: attachRef,
    sendInput,
    connected,
    reconnecting,
    error,
  } = useTerminal({ sessionId });

  useImperativeHandle(
    ref,
    () => ({
      sendInput,
      focus: () => {
        const term = innerRef.current?.querySelector<HTMLElement>(
          ".xterm-helper-textarea",
        );
        term?.focus();
      },
    }),
    [sendInput],
  );

  // Combined callback so we forward our internal node to useTerminal AND
  // keep a local ref so we can focus the textarea.
  const setRef = (el: HTMLDivElement | null) => {
    innerRef.current = el;
    attachRef(el);
  };

  const statusText = (() => {
    if (error) return error;
    if (reconnecting) return "Reconnecting…";
    if (connected) return "Connected";
    return "Connecting…";
  })();

  const statusTone = error
    ? "bg-rose-950 text-rose-200 border-rose-800"
    : reconnecting
      ? "bg-amber-950 text-amber-200 border-amber-800"
      : connected
        ? "bg-emerald-950 text-emerald-200 border-emerald-800"
        : "bg-neutral-900 text-neutral-300 border-neutral-800";

  return (
    <div
      className={clsx(
        "flex h-full min-h-0 w-full flex-col",
        "bg-black",
        className,
      )}
    >
      <div
        ref={setRef}
        className="xterm-host min-h-0 flex-1 overflow-hidden bg-black p-2"
        data-testid="terminal-host"
      />
      <div
        role="status"
        aria-live="polite"
        className={clsx(
          "shrink-0 border-t px-3 py-1 text-xs",
          "font-mono",
          statusTone,
        )}
      >
        {statusText}
      </div>
    </div>
  );
});

export default Terminal;
