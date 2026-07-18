import { act, renderHook } from "@testing-library/react";
import { useLiveView } from "./liveView";

beforeEach(() => localStorage.clear());

test("defaults to the picks view", () => {
  const { result } = renderHook(() => useLiveView());
  expect(result.current[0]).toBe("picks");
});

test("persists the chosen view across remounts", () => {
  const first = renderHook(() => useLiveView());
  act(() => first.result.current[1]("vs"));
  expect(localStorage.getItem("phishpicker:liveView")).toBe("vs");
  const second = renderHook(() => useLiveView());
  expect(second.result.current[0]).toBe("vs");
});
