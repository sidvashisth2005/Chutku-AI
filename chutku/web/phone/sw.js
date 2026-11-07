"use strict";
// Chutku phone app service worker: caches ONLY the app's static files, never /api/* (answers, screens, files).
const CACHE = "chutku-phone-v1";
const STATIC = ["/", "/phone.js", "/phone.css", "/jitter.js", "/manifest.webmanifest", "/icon.png"];
self.addEventListener("install", event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(STATIC))));
self.addEventListener("activate", event => event.waitUntil(caches.keys().then(keys =>
  Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))));
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.pathname.startsWith("/api/") || !STATIC.includes(url.pathname)) return;
  event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
});
