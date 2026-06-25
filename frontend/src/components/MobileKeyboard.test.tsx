import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import MobileKeyboard from "./MobileKeyboard";

function makeHandlers() {
  return {
    onKey: vi.fn(),
    onCtrl: vi.fn(),
    onEnter: vi.fn(),
    onArrow: vi.fn(),
    onEsc: vi.fn(),
    onTab: vi.fn(),
    onSlash: vi.fn(),
  };
}

describe("MobileKeyboard", () => {
  it("renders all nine keys", () => {
    const h = makeHandlers();
    render(<MobileKeyboard {...h} />);
    for (const id of [
      "key-esc",
      "key-tab",
      "key-ctrl",
      "key-arrow-up",
      "key-arrow-down",
      "key-arrow-left",
      "key-arrow-right",
      "key-slash",
      "key-enter",
    ]) {
      expect(screen.getByTestId(id)).toBeInTheDocument();
    }
  });

  it("invokes onEsc when Esc is pressed", () => {
    const h = makeHandlers();
    render(<MobileKeyboard {...h} />);
    fireEvent.click(screen.getByTestId("key-esc"));
    expect(h.onEsc).toHaveBeenCalledTimes(1);
  });

  it("invokes onTab when Tab is pressed", () => {
    const h = makeHandlers();
    render(<MobileKeyboard {...h} />);
    fireEvent.click(screen.getByTestId("key-tab"));
    expect(h.onTab).toHaveBeenCalledTimes(1);
  });

  it("invokes onSlash when / is pressed", () => {
    const h = makeHandlers();
    render(<MobileKeyboard {...h} />);
    fireEvent.click(screen.getByTestId("key-slash"));
    expect(h.onSlash).toHaveBeenCalledTimes(1);
  });

  it("invokes onEnter when Enter is pressed", () => {
    const h = makeHandlers();
    render(<MobileKeyboard {...h} />);
    fireEvent.click(screen.getByTestId("key-enter"));
    expect(h.onEnter).toHaveBeenCalledTimes(1);
  });

  it("invokes onArrow('up') when ↑ is pressed", () => {
    const h = makeHandlers();
    render(<MobileKeyboard {...h} />);
    fireEvent.click(screen.getByTestId("key-arrow-up"));
    expect(h.onArrow).toHaveBeenCalledWith("up");
  });

  it("invokes onArrow with the correct direction for each arrow", () => {
    const h = makeHandlers();
    render(<MobileKeyboard {...h} />);
    fireEvent.click(screen.getByTestId("key-arrow-down"));
    fireEvent.click(screen.getByTestId("key-arrow-left"));
    fireEvent.click(screen.getByTestId("key-arrow-right"));
    expect(h.onArrow).toHaveBeenNthCalledWith(1, "down");
    expect(h.onArrow).toHaveBeenNthCalledWith(2, "left");
    expect(h.onArrow).toHaveBeenNthCalledWith(3, "right");
  });

  it("toggles Ctrl mode, sends Ctrl-letter on next press, then deactivates", () => {
    const h = makeHandlers();
    render(<MobileKeyboard {...h} />);

    // No Ctrl pressed yet — pressing a letter key should NOT call onCtrl.
    fireEvent.click(screen.getByTestId("key-slash"));
    expect(h.onCtrl).not.toHaveBeenCalled();

    // Activate Ctrl mode.
    fireEvent.click(screen.getByTestId("key-ctrl"));
    expect(screen.getByTestId("key-ctrl")).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    // Next letter key fires onCtrl and auto-deactivates.
    fireEvent.click(screen.getByTestId("key-slash"));
    expect(h.onCtrl).toHaveBeenCalledTimes(1);
    expect(h.onCtrl).toHaveBeenCalledWith("/");
    expect(screen.getByTestId("key-ctrl")).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    // After auto-deactivation, the same key no longer triggers onCtrl —
    // it falls through to the normal handler (onSlash).
    fireEvent.click(screen.getByTestId("key-slash"));
    expect(h.onCtrl).toHaveBeenCalledTimes(1);
  });

  it("pressing the arrow keys while Ctrl mode is active sends Ctrl-arrow", () => {
    const h = makeHandlers();
    render(<MobileKeyboard {...h} />);
    fireEvent.click(screen.getByTestId("key-ctrl"));
    fireEvent.click(screen.getByTestId("key-arrow-up"));
    expect(h.onCtrl).toHaveBeenCalledWith("↑");
    expect(h.onArrow).not.toHaveBeenCalled();
    expect(screen.getByTestId("key-ctrl")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});
