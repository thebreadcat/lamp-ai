const CACHE = "lamp-shell-v12";
const PRECACHE = [
  "/",
  "/manifest.json",
  "/sw.js",
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

function shouldPrecache(pathname) {
  return pathname === "/" || pathname === "/manifest.json" || pathname === "/sw.js";
}

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) return;
  if (e.request.method !== "GET") return;
  if (url.origin !== self.location.origin) return;

  e.respondWith(
    (async () => {
      try {
        const res = await fetch(e.request);
        if (res.ok && shouldPrecache(url.pathname)) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        }
        return res;
      } catch (_) {
        const cached = await caches.match(e.request);
        return cached || caches.match("/");
      }
    })()
  );
});

let lastSeenId = 0;

async function pollNotifications() {
  try {
    const r = await fetch("/api/notifications?unread=1", { credentials: "include" });
    if (!r.ok) return;
    const data = await r.json();
    const list = data.notifications || [];
    const unseen = list.filter((n) => n.id > lastSeenId);
    for (const n of unseen) {
      lastSeenId = Math.max(lastSeenId, n.id);
      await self.registration.showNotification(n.title || n.app || "Lamp", {
        body: n.message || "",
        icon: "/icon-192.png",
        tag: `lamp-${n.id}`,
        data: { url: "/#/notifications" },
      });
    }
    if (list.length) lastSeenId = Math.max(lastSeenId, list[0].id);
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
