// Service Worker — PWA 离线支持
// CACHE 版本由 postbuild 脚本自动注入 git short hash
const CACHE = 'exam-tutor-f264714';
// 静态资源白名单 — 绝不缓存 API 响应
const STATIC_PREFIXES = ['/assets/', '/icons/'];
const STATIC_EXACT = ['/', '/index.html', '/manifest.json', '/sw.js', '/favicon.svg'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC_EXACT)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const path = new URL(e.request.url).pathname;
  // 白名单：只缓存静态资源
  const isStatic = STATIC_EXACT.includes(path) ||
    STATIC_PREFIXES.some(p => path.startsWith(p));
  if (!isStatic) return; // API / 动态请求直通网络

  e.respondWith(
    caches.match(e.request).then(cached =>
      cached || fetch(e.request).then(resp => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return resp;
      })
    )
  );
});
