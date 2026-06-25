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

  it("toggles Ctrl mode and exposes Ctrl-C/Ctrl-D actions", () => {
    const h = makeHandlers();
    render(<MobileKeyboard {...h} />);

    fireEvent.click(screen.getByTestId("key-ctrl"));
    expect(screen.getByTestId("key-ctrl")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByTestId("key-ctrl-c")).toBeInTheDocument();
    expect(screen.getByTestId("key-ctrl-d")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("key-ctrl-c"));
    expect(h.onCtrl).toHaveBeenCalledTimes(1);
    expect(h.onCtrl).toHaveBeenCalledWith("c");
    expect(screen.getByTestId("key-ctrl")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("sends Ctrl-D from the Ctrl action row", () => {
    const h = makeHandlers();
    render(<MobileKeyboard {...h} />);

    fireEvent.click(screen.getByTestId("key-ctrl"));
    fireEvent.click(screen.getByTestId("key-ctrl-d"));
    expect(h.onCtrl).toHaveBeenCalledTimes(1);
    expect(h.onCtrl).toHaveBeenCalledWith("d");
  });

  it("pressing a normal key while Ctrl mode is active clears Ctrl and sends the normal key", () => {
    const h = makeHandlers();
    render(<MobileKeyboard {...h} />);
    fireEvent.click(screen.getByTestId("key-ctrl"));
    fireEvent.click(screen.getByTestId("key-arrow-up"));
    expect(h.onCtrl).not.toHaveBeenCalled();
    expect(h.onArrow).toHaveBeenCalledWith("up");
    expect(screen.getByTestId("key-ctrl")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});
