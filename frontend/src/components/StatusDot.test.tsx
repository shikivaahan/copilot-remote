import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import StatusDot from "./StatusDot";

describe("StatusDot", () => {
  it("renders a green dot with the running label for 'running'", () => {
    render(<StatusDot status="running" />);
    const wrapper = screen.getByRole("status");
    expect(wrapper).toHaveAttribute("aria-label", "status: running");
    expect(wrapper).toHaveTextContent(/running/i);
    const dot = wrapper.querySelector("span > span");
    expect(dot).not.toBeNull();
    expect(dot!.className).toMatch(/bg-emerald/);
  });

  it("renders a yellow dot with the exited label for 'exited'", () => {
    render(<StatusDot status="exited" />);
    const wrapper = screen.getByRole("status");
    expect(wrapper).toHaveAttribute("aria-label", "status: exited");
    expect(wrapper).toHaveTextContent(/exited/i);
    const dot = wrapper.querySelector("span > span");
    expect(dot).not.toBeNull();
    expect(dot!.className).toMatch(/bg-amber/);
  });

  it("renders a red dot with the errored label for 'errored'", () => {
    render(<StatusDot status="errored" />);
    const wrapper = screen.getByRole("status");
    expect(wrapper).toHaveAttribute("aria-label", "status: errored");
    expect(wrapper).toHaveTextContent(/errored/i);
    const dot = wrapper.querySelector("span > span");
    expect(dot).not.toBeNull();
    expect(dot!.className).toMatch(/bg-rose/);
  });

  it("uses the title override for the aria-label and tooltip", () => {
    render(<StatusDot status="running" title="Healthy" />);
    const wrapper = screen.getByRole("status");
    expect(wrapper).toHaveAttribute("aria-label", "status: Healthy");
    const dot = wrapper.querySelector("span > span");
    expect(dot).toHaveAttribute("title", "Healthy");
  });

  it("hides the inline text label when hideLabel is set", () => {
    render(<StatusDot status="running" hideLabel />);
    const wrapper = screen.getByRole("status");
    expect(wrapper).not.toHaveTextContent(/running/i);
  });
});
