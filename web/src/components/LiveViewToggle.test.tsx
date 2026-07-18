import { fireEvent, render, screen } from "@testing-library/react";
import { LiveViewToggle } from "./LiveViewToggle";

test("marks the active segment and fires onChange", () => {
  const onChange = vi.fn();
  render(<LiveViewToggle value="picks" onChange={onChange} />);
  expect(screen.getByRole("button", { name: /picks/i })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: /vs/i }));
  expect(onChange).toHaveBeenCalledWith("vs");
});
