import { render, screen, waitFor } from "@testing-library/react";
import { PushToggle } from "./PushToggle";

function setStandalone(on: boolean) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (q: string) => ({
      matches: on && q.includes("standalone"),
      media: q,
      addEventListener: () => {},
      removeEventListener: () => {},
    }),
  });
}

function installMockPushEnv(opts: {
  permission?: NotificationPermission;
  existingSub?: PushSubscription | null;
} = {}) {
  const { permission = "default", existingSub = null } = opts;
  Object.defineProperty(window, "PushManager", {
    configurable: true,
    value: class {},
  });
  // jsdom doesn't provide Notification — stub just the shape we use.
  Object.defineProperty(window, "Notification", {
    configurable: true,
    value: { permission, requestPermission: vi.fn() },
  });
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: {
      ready: Promise.resolve({
        pushManager: {
          getSubscription: vi.fn().mockResolvedValue(existingSub),
          subscribe: vi.fn(),
        },
      }),
    },
  });
}

afterEach(() => {
  // @ts-expect-error test cleanup
  delete navigator.serviceWorker;
  // @ts-expect-error test cleanup
  delete window.PushManager;
  // @ts-expect-error test cleanup
  delete window.Notification;
});

test("renders nothing when push APIs are unsupported", () => {
  setStandalone(true);
  const { container } = render(<PushToggle />);
  expect(container.firstChild).toBeNull();
});

test("renders nothing when app is not running standalone", async () => {
  setStandalone(false);
  installMockPushEnv();
  const { container } = render(<PushToggle />);
  // Wait a tick for the effect; nothing should appear.
  await new Promise((r) => setTimeout(r, 10));
  expect(container.firstChild).toBeNull();
});

test("shows 'enable' pill when standalone and unsubscribed", async () => {
  setStandalone(true);
  installMockPushEnv({ permission: "default", existingSub: null });
  render(<PushToggle />);
  const pill = await screen.findByTestId("push-toggle");
  expect(pill).toHaveAttribute("data-state", "off");
  expect(pill).toHaveTextContent(/enable/i);
});

test("shows 'on' pill when an existing subscription is present", async () => {
  setStandalone(true);
  installMockPushEnv({
    permission: "granted",
    existingSub: {
      endpoint: "https://push/example",
      unsubscribe: vi.fn(),
    } as unknown as PushSubscription,
  });
  render(<PushToggle />);
  const pill = await screen.findByTestId("push-toggle");
  await waitFor(() => expect(pill).toHaveAttribute("data-state", "on"));
});

test("shows 'blocked' when permission was denied", async () => {
  setStandalone(true);
  installMockPushEnv({ permission: "denied" });
  render(<PushToggle />);
  const pill = await screen.findByTestId("push-toggle");
  expect(pill).toHaveAttribute("data-state", "denied");
  expect(pill).toBeDisabled();
});
