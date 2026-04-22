// Phishpicker service worker.
//
// Scope: "/" (hosted at /sw.js). Install + activate take control immediately
// so the client doesn't need a reload after registration. push shows a
// native notification; notificationclick focuses an existing app window or
// opens a new one.

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let payload = {};
  if (event.data) {
    try {
      payload = event.data.json();
    } catch {
      payload = { title: "Phishpicker", body: event.data.text() };
    }
  }
  const {
    title = "Phishpicker",
    body = "",
    icon = "/icon-192.png",
    badge = "/icon-192.png",
    tag,
    data,
  } = payload;
  event.waitUntil(
    self.registration.showNotification(title, { body, icon, badge, tag, data }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    (async () => {
      const clients = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });
      for (const c of clients) {
        if ("focus" in c) return c.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })(),
  );
});
