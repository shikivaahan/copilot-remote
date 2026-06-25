import { useCallback, useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import type { SessionStatus } from "@/types";

export interface UseTerminalOptions {
  sessionId: string;
  onClose?: () => void;
  onStatusChange?: (status: SessionStatus) => void;
}

export interface UseTerminalReturn {
  ref: (el: HTMLDivElement | null) => void;
  sendInput: (data: string) => void;
  connected: boolean;
  reconnecting: boolean;
  error: string | null;
}

interface ServerMessage {
  type: string;
  state?: SessionStatus;
  message?: string;
  rows?: number;
  cols?: number;
}

const RECONNECT_INITIAL_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;
const PING_INTERVAL_MS = 25_000;

function jitter(ms: number): number {
  // ±20% jitter so multiple clients don't reconnect in lockstep.
  const delta = ms * 0.2;
  return Math.round(ms - delta + Math.random() * (delta * 2));
}

function nextDelay(attempt: number): number {
  const exp = Math.min(RECONNECT_MAX_MS, RECONNECT_INITIAL_MS * 2 ** attempt);
  return jitter(exp);
}

function wsUrl(sessionId: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/sessions/${encodeURIComponent(sessionId)}`;
}

/**
 * Drives the full xterm.js + WebSocket lifecycle for one session.
 *
 * Lifecycle:
 *   1. Mount: xterm + FitAddon are created when `ref` is invoked with a div.
 *   2. Connect: WebSocket opens, sends an initial `resize` control frame.
 *   3. Pump: WS binary → term.write; term.onData → ws.send (binary).
 *   4. Control: JSON text frames handle resize echo, status updates, errors.
 *   5. Reconnect: closed sockets are reconnected with exponential backoff
 *      (1s → 30s) and jitter; a fresh `resize` is sent after each reconnect
 *      so the server emits a redraw.
 *   6. Cleanup: WS closed, terminal disposed, observer disconnected.
 */
export function useTerminal({
  sessionId,
  onClose,
  onStatusChange,
}: UseTerminalOptions): UseTerminalReturn {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const observerRef = useRef<ResizeObserver | null>(null);
  const pingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const isUnmountedRef = useRef(false);
  const onCloseRef = useRef(onClose);
  const onStatusChangeRef = useRef(onStatusChange);

  const [connected, setConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Keep callback refs up to date without re-creating the WebSocket on every
  // parent render.
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    onStatusChangeRef.current = onStatusChange;
  }, [onStatusChange]);

  const sendResize = useCallback(() => {
    const ws = wsRef.current;
    const term = termRef.current;
    const fit = fitRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !term) return;
    let rows = term.rows;
    let cols = term.cols;
    if (fit) {
      try {
        const dims = fit.proposeDimensions();
        if (dims) {
          rows = dims.rows;
          cols = dims.cols;
        }
      } catch {
        // FitAddon throws when the container has zero size; ignore.
      }
    }
    ws.send(JSON.stringify({ type: "resize", rows, cols }));
  }, []);

  const sendControl = useCallback((payload: ServerMessage) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify(payload));
  }, []);

  const scheduleReconnect = useCallback(() => {
    if (isUnmountedRef.current) return;
    const delay = nextDelay(attemptRef.current);
    attemptRef.current += 1;
    setReconnecting(true);
    setConnected(false);
    reconnectTimerRef.current = setTimeout(() => {
      reconnectTimerRef.current = null;
      connect();
    }, delay);
  }, []);

  const connect = useCallback(() => {
    if (isUnmountedRef.current) return;
    if (!termRef.current) return;

    // Tear down any existing socket before opening a new one.
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch {
        // ignore
      }
      wsRef.current = null;
    }

    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl(sessionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to open socket");
      scheduleReconnect();
      return;
    }
    wsRef.current = ws;
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      if (isUnmountedRef.current) {
        ws.close();
        return;
      }
      attemptRef.current = 0;
      setConnected(true);
      setReconnecting(false);
      setError(null);
      // Inform the server of our size so it sends a redraw.
      sendResize();

      // Periodic keep-alive ping (browser WS have no native ping).
      if (pingTimerRef.current) clearInterval(pingTimerRef.current);
      pingTimerRef.current = setInterval(() => {
        sendControl({ type: "ping" });
      }, PING_INTERVAL_MS);
    };

    ws.onmessage = (ev: MessageEvent) => {
      const term = termRef.current;
      if (!term) return;
      if (typeof ev.data === "string") {
        let msg: ServerMessage | null = null;
        try {
          msg = JSON.parse(ev.data) as ServerMessage;
        } catch {
          // Malformed JSON — ignore rather than spam the terminal.
          return;
        }
        if (!msg || typeof msg.type !== "string") return;
        switch (msg.type) {
          case "pong":
            break;
          case "status":
            if (
              (msg.state === "running" ||
                msg.state === "exited" ||
                msg.state === "errored" ||
                msg.state === "stopped") &&
              onStatusChangeRef.current
            ) {
              onStatusChangeRef.current(msg.state);
            }
            break;
          case "error":
            setError(msg.message ?? "Server reported an error");
            break;
          case "resize":
            // Server-initiated resize echo; re-fit locally.
            try {
              if (fitRef.current) fitRef.current.fit();
            } catch {
              // ignore
            }
            break;
          default:
            break;
        }
        return;
      }
      // Binary frame → terminal bytes.
      if (ev.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(ev.data));
      } else if (ev.data instanceof Blob) {
        void ev.data.arrayBuffer().then((buf) => {
          term.write(new Uint8Array(buf));
        });
      } else {
        // Some browsers deliver binary as Uint8Array directly.
        term.write(ev.data as Uint8Array);
      }
    };

    ws.onerror = () => {
      // The 'close' handler will run right after — let it decide reconnect.
      setError("WebSocket connection failed");
    };

    ws.onclose = () => {
      if (pingTimerRef.current) {
        clearInterval(pingTimerRef.current);
        pingTimerRef.current = null;
      }
      setConnected(false);
      if (isUnmountedRef.current) {
        onCloseRef.current?.();
        return;
      }
      scheduleReconnect();
    };
  }, [scheduleReconnect, sendControl, sendResize, sessionId]);

  const ref = useCallback(
    (el: HTMLDivElement | null) => {
      // Detach: dispose of everything.
      if (!el) {
        if (reconnectTimerRef.current) {
          clearTimeout(reconnectTimerRef.current);
          reconnectTimerRef.current = null;
        }
        if (pingTimerRef.current) {
          clearInterval(pingTimerRef.current);
          pingTimerRef.current = null;
        }
        if (observerRef.current) {
          observerRef.current.disconnect();
          observerRef.current = null;
        }
        if (wsRef.current) {
          try {
            wsRef.current.close();
          } catch {
            // ignore
          }
          wsRef.current = null;
        }
        if (termRef.current) {
          try {
            termRef.current.dispose();
          } catch {
            // ignore
          }
          termRef.current = null;
        }
        fitRef.current = null;
        containerRef.current = null;
        setConnected(false);
        setReconnecting(false);
        return;
      }

      if (containerRef.current === el && termRef.current) {
        // Same node, second render — ignore.
        return;
      }

      containerRef.current = el;

      const term = new Terminal({
        convertEol: false,
        cursorBlink: true,
        fontFamily:
          '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
        fontSize: 14,
        theme: {
          background: "#000000",
          foreground: "#e5e5e5",
          cursor: "#e5e5e5",
          selectionBackground: "#3f3f46",
        },
        scrollback: 5_000,
      });
      const fit = new FitAddon();
      term.loadAddon(fit);
      term.open(el);

      term.onData((data) => {
        const ws = wsRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        // Spec §6.2: user keystrokes are sent as binary frames (raw bytes).
        const enc = new TextEncoder();
        ws.send(enc.encode(data));
      });

      term.onResize(() => {
        sendResize();
      });

      termRef.current = term;
      fitRef.current = fit;

      // Initial fit (ignore the very first one if the container has no size yet).
      try {
        fit.fit();
      } catch {
        // ignore
      }

      // ResizeObserver is more accurate than window.resize inside flex
      // containers; re-fit and notify the server when the box changes.
      const ro = new ResizeObserver(() => {
        try {
          fit.fit();
        } catch {
          // ignore
        }
        sendResize();
      });
      ro.observe(el);
      observerRef.current = ro;

      // Kick off the WebSocket once we have a terminal.
      connect();
    },
    [connect, sendResize],
  );

  // Reconnect when the sessionId changes (defensive — usually stable).
  useEffect(() => {
    if (!termRef.current) return;
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch {
        // ignore
      }
      wsRef.current = null;
    }
    attemptRef.current = 0;
    connect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    isUnmountedRef.current = false;
    return () => {
      isUnmountedRef.current = true;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (pingTimerRef.current) {
        clearInterval(pingTimerRef.current);
        pingTimerRef.current = null;
      }
      if (observerRef.current) {
        observerRef.current.disconnect();
        observerRef.current = null;
      }
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          // ignore
        }
        wsRef.current = null;
      }
      if (termRef.current) {
        try {
          termRef.current.dispose();
        } catch {
          // ignore
        }
        termRef.current = null;
      }
      fitRef.current = null;
    };
  }, []);

  const sendInput = useCallback((data: string) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const enc = new TextEncoder();
    ws.send(enc.encode(data));
  }, []);

  return { ref, sendInput, connected, reconnecting, error };
}
