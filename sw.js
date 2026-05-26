const CACHE = "lamp-shell-v17";
const PRECACHE = [
  "/manifest.json",
  "/favicon.svg",
  "/lamp-icons.js",
  "/assets/fontawesome/css/all.min.css",
  "/assets/fontawesome/webfonts/fa-solid-900.woff2",
  "/assets/fontawesome/webfonts/fa-regular-400.woff2",
];

async function cacheUrl(cache, url) {
  try {
    const r = await fetch(url, { cache: "no-store" });
    if (r.ok) await cache.put(url, r);
  } catch (_) {}
}

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then(async (cache) => {
      for (const url of PRECACHE) await cacheUrl(cache, url);
      for (const url of ["/icon-192.png", "/icon-512.png"]) await cacheUrl(cache, url);
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

function isAppShellRequest(request, url) {
  if (request.mode === "navigate") return true;
  return url.pathname === "/" || url.pathname === "/index.html";
}

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) return;
  if (e.request.method !== "GET") return;
  if (url.origin !== self.location.origin) return;

  if (isAppShellRequest(e.request, url)) {
    e.respondWith(
      (async () => {
        try {
          const res = await fetch(e.request, { cache: "no-store" });
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
          }
          return res;
        } catch (_) {
          return (await caches.match(e.request)) || (await caches.match("/"));
        }
      })()
    );
    return;
  }

  e.respondWith(
    (async () => {
      try {
        const res = await fetch(e.request);
        if (res.ok && (url.pathname === "/manifest.json" || url.pathname === "/sw.js")) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        }
        return res;
      } catch (_) {
        const cached = await caches.match(e.request);
        return cached || undefined;
      }
    })()
  );
});

let lastSeenId = 0;
let notifBootstrapped = false;

function meaningfulNotifications(list) {
  return (list || []).filter((n) => ((n.title || "") + (n.message || "")).trim());
}

async function pollNotifications() {
  try {
    const r = await fetch("/api/notifications?unread=1", { credentials: "include" });
    if (!r.ok) return;
    const data = await r.json();
    const list = meaningfulNotifications(data.notifications);
    if (!notifBootstrapped) {
      lastSeenId = list.reduce((m, n) => Math.max(m, n.id || 0), 0);
      notifBootstrapped = true;
    } else {
      const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      const appVisible = clients.some((c) => c.visibilityState === "visible");
      const unseen = list.filter((n) => n.id > lastSeenId);
      if (!appVisible) {
        for (const n of unseen) {
          lastSeenId = Math.max(lastSeenId, n.id);
          await self.registration.showNotification(n.title || "Lamp", {
            body: n.message || n.app || "",
            icon: "/icon-192.png",
            tag: `lamp-${n.id}`,
            data: { url: "/#/notifications" },
          });
        }
      } else if (unseen.length) {
        lastSeenId = Math.max(lastSeenId, ...unseen.map((n) => n.id));
      }
    }
    const clients = await self.clients.matchAll({ type: "window" });
    clients.forEach((c) => c.postMessage({ type: "notif-count", count: list.length }));
  } catch (_) {}
}

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(
    self.clients.matchAll({ type: "window" }).then((list) => {
      if (list.length) {
        list[0].focus();
        list[0].navigate(url);
        return;
      }
      return self.clients.openWindow(url);
    })
  );
});

setInterval(pollNotifications, 30000);
pollNotifications();
