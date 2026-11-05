// Science Pulse — офлайн-кэш статики (network-first, cache fallback).
const CACHE = 'science-pulse-v1';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  let url;
  try { url = new URL(request.url); } catch (error) { return; }
  if (url.origin !== self.location.origin) return;
  event.respondWith(
    caches.open(CACHE).then((cache) =>
      fetch(request).then((response) => {
        if (response && response.ok) cache.put(request, response.clone());
        return response;
      }).catch(() => cache.match(request))
    )
  );
});
