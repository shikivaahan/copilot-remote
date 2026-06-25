import { useState } from "react";
import clsx from "clsx";

export type ArrowDir = "up" | "down" | "left" | "right";

interface Props {
  onKey: (data: string) => void;
  onCtrl: (letter: string) => void;
  onEnter: () => void;
  onArrow: (dir: ArrowDir) => void;
  onEsc: () => void;
  onTab: () => void;
  onSlash: () => void;
}

interface KeyDef {
  label: string;
  ariaLabel: string;
  testId: string;
  className?: string;
  onPress: (api: Props, ctrlActive: boolean) => void;
  /** Returns true if the key should appear "pressed" / active. */
  isActive?: (ctrlActive: boolean) => boolean;
}

const ARROW_DATA: Record<ArrowDir, string> = {
  up: "\x1b[A",
  down: "\x1b[B",
  left: "\x1b[D",
  right: "\x1b[C",
};

const CTRL_KEYS = [
  { label: "C", value: "c", testId: "key-ctrl-c", ariaLabel: "Control C" },
  { label: "D", value: "d", testId: "key-ctrl-d", ariaLabel: "Control D" },
];

const KEYS: KeyDef[] = [
  {
    label: "Esc",
    ariaLabel: "Escape",
    testId: "key-esc",
    onPress: (api) => api.onEsc(),
  },
  {
    label: "Tab",
    ariaLabel: "Tab",
    testId: "key-tab",
    onPress: (api) => api.onTab(),
  },
  {
    label: "Ctrl",
    ariaLabel: "Control (next key sends Ctrl-letter)",
    testId: "key-ctrl",
    className: "ctrl-key",
    // Pressing the Ctrl button itself does not send data; it exposes
    // explicit Ctrl-C/Ctrl-D actions for mobile keyboards that lack Ctrl.
    onPress: () => undefined,
    isActive: (ctrlActive) => ctrlActive,
  },
  {
    label: "↑",
    ariaLabel: "Arrow up",
    testId: "key-arrow-up",
    onPress: (api) => api.onArrow("up"),
  },
  {
    label: "↓",
    ariaLabel: "Arrow down",
    testId: "key-arrow-down",
    onPress: (api) => api.onArrow("down"),
  },
  {
    label: "←",
    ariaLabel: "Arrow left",
    testId: "key-arrow-left",
    onPress: (api) => api.onArrow("left"),
  },
  {
    label: "→",
    ariaLabel: "Arrow right",
    testId: "key-arrow-right",
    onPress: (api) => api.onArrow("right"),
  },
  {
    label: "/",
    ariaLabel: "Slash",
    testId: "key-slash",
    onPress: (api) => api.onSlash(),
  },
  {
    label: "Enter",
    ariaLabel: "Enter",
    testId: "key-enter",
    className: "enter-key",
    onPress: (api) => api.onEnter(),
  },
];

/**
 * Persistent thumb-friendly keyboard for the session page.
 *
 * Sends the correct escape sequences for arrow keys (ESC [ A/B/C/D),
 * Tab, Enter, Escape, and a slash. Ctrl exposes explicit Ctrl-C/Ctrl-D
 * actions because mobile software keyboards usually do not have a real
 * Ctrl modifier.
 */
export default function MobileKeyboard(props: Props) {
  const [ctrlActive, setCtrlActive] = useState(false);

  function pressKey(key: KeyDef) {
    if (key.testId === "key-ctrl") {
      setCtrlActive((active) => !active);
      return;
    }
    if (ctrlActive) setCtrlActive(false);
    key.onPress(props, ctrlActive);
  }

  function pressCtrl(value: string) {
    props.onCtrl(value);
    setCtrlActive(false);
  }

  return (
    <div
      className={clsx(
        "sticky bottom-0 left-0 right-0 z-20",
        "border-t border-neutral-800 bg-neutral-950/95 backdrop-blur",
        "px-2 py-2",
      )}
      role="toolbar"
      aria-label="Terminal helper keys"
    >
      {ctrlActive && (
        <div className="mb-2 grid grid-cols-2 gap-1.5 sm:gap-2">
          {CTRL_KEYS.map((key) => (
            <button
              key={key.testId}
              type="button"
              data-testid={key.testId}
              aria-label={key.ariaLabel}
              onClick={() => pressCtrl(key.value)}
              className={clsx(
                "min-h-11 inline-flex select-none items-center justify-center",
                "rounded-md border border-emerald-500 bg-emerald-600",
                "px-2 py-2 text-base font-semibold text-neutral-950",
                "transition-colors active:scale-[0.97]",
                "focus:outline-none focus:ring-2 focus:ring-emerald-500",
              )}
            >
              Ctrl-{key.label}
            </button>
          ))}
        </div>
      )}
      <div
        className={clsx(
          "grid grid-cols-9 gap-1.5",
          "sm:gap-2",
        )}
      >
        {KEYS.map((key) => {
          const active = key.isActive?.(ctrlActive) ?? false;
          return (
            <button
              key={key.testId}
              type="button"
              data-testid={key.testId}
              aria-label={key.ariaLabel}
              aria-pressed={key.testId === "key-ctrl" ? ctrlActive : undefined}
              onClick={() => pressKey(key)}
              className={clsx(
                "min-h-12 inline-flex select-none items-center justify-center",
                "rounded-md border px-2 py-2 text-base font-semibold",
                "transition-colors active:scale-[0.97]",
                "focus:outline-none focus:ring-2 focus:ring-emerald-500",
                active
                  ? "border-emerald-500 bg-emerald-600 text-neutral-950"
                  : "border-neutral-700 bg-neutral-900 text-neutral-100 hover:bg-neutral-800",
                key.className,
              )}
            >
              {key.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Encode a Ctrl-letter combination as a single control byte (0x01 .. 0x1a).
 * Uppercase letters map to the same byte as their lowercase counterpart;
 * we always send the lowercase form to keep behaviour predictable.
 */
export function encodeCtrl(letter: string): string {
  const ch = letter.toLowerCase();
  if (ch.length !== 1) return "";
  const code = ch.charCodeAt(0);
  if (code < 0x61 || code > 0x7a) return "";
  return String.fromCharCode(code - 0x60);
}

/** Encode an arrow key into the matching VT100 escape sequence. */
export function encodeArrow(dir: ArrowDir): string {
  return ARROW_DATA[dir];
}
