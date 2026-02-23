/* Service worker: Web Push notifications for job completion/failure */
self.addEventListener("install", function () {
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(clients.claim());
});

self.addEventListener("push", function (event) {
  if (!event.data) return;
  var data = {};
  try {
    data = event.data.json();
  } catch (e) {
    return;
  }
  var title = data.title || "Stereo-Spot";
  var body = data.body || "";
  var url = data.url || "/";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: body,
      icon: "/static/favicon.png",
      data: { url: url },
    })
  );
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var url = event.notification.data && event.notification.data.url;
  if (url) {
    event.waitUntil(
      clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (windowClients) {
        for (var i = 0; i < windowClients.length; i++) {
          if (windowClients[i].url.indexOf(self.location.origin) === 0 && "focus" in windowClients[i]) {
            windowClients[i].navigate(url);
            return windowClients[i].focus();
          }
        }
        if (clients.openWindow) {
          return clients.openWindow(url);
        }
      })
    );
  }
});
