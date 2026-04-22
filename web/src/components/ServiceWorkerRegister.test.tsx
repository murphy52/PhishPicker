import { render, waitFor } from "@testing-library/react";
import { ServiceWorkerRegister } from "./ServiceWorkerRegister";

afterEach(() => {
  // jsdom has no serviceWorker; tests install/remove a stub.
  // @ts-expect-error — test cleanup
  delete navigator.serviceWorker;
});

test("registers /sw.js when serviceWorker is supported", async () => {
  const register = vi.fn().mockResolvedValue({});
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: { register },
  });
  render(<ServiceWorkerRegister />);
  await waitFor(() => expect(register).toHaveBeenCalledWith("/sw.js"));
});

test("is a no-op when serviceWorker API is absent", () => {
  expect(() => render(<ServiceWorkerRegister />)).not.toThrow();
});

test("swallows registration failures", async () => {
  const register = vi.fn().mockRejectedValue(new Error("test"));
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: { register },
  });
  render(<ServiceWorkerRegister />);
  await waitFor(() =>
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining("service worker"),
      expect.any(Error),
    ),
  );
  warn.mockRestore();
});
