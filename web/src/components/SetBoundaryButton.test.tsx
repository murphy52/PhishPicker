import { render, screen, fireEvent } from "@testing-library/react";
import { SetBoundaryButton } from "./SetBoundaryButton";

test("renders set boundary button", () => {
  render(<SetBoundaryButton currentSet="1" onAdvance={() => {}} />);
  expect(screen.getByRole("button")).toBeInTheDocument();
});

test("shows current set in label", () => {
  render(<SetBoundaryButton currentSet="1" onAdvance={() => {}} />);
  expect(screen.getByText(/set 1/i)).toBeInTheDocument();
});

test("calls onAdvance with next set when clicked", () => {
  const onAdvance = vi.fn();
  render(<SetBoundaryButton currentSet="1" onAdvance={onAdvance} />);
  fireEvent.click(screen.getByRole("button"));
  expect(onAdvance).toHaveBeenCalledWith("2");
});

test("advances from set 2 to encore (uppercase E)", () => {
  const onAdvance = vi.fn();
  render(<SetBoundaryButton currentSet="2" onAdvance={onAdvance} />);
  fireEvent.click(screen.getByRole("button"));
  expect(onAdvance).toHaveBeenCalledWith("E");
});

test("renders nothing when already in encore", () => {
  const { container } = render(
    <SetBoundaryButton currentSet="E" onAdvance={() => {}} />,
  );
  expect(container.firstChild).toBeNull();
});
