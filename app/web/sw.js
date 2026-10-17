/* 家庭工作台 · 离线壳（P6 多端接入）
 *
 * 只缓存「壳」：离线页 + 图标。**绝不缓存 /api/* 和首页 HTML**：
 *  - 首页带登录态与家庭数据，缓存会让旁人绕过 PIN 看到状态（08 §3 旁观泄露）；
 *  - 旧读数不能冒充当前状态（08 红线），所以状态永远实时取，断网就诚实说连不上。
 *
 * 策略：导航请求网络优先，失败才回离线页；静态资源网络优先、失败用缓存；API 一律不拦。
 */
const CACHE = 'wb-shell-v2';
const SHELL = ['/offline.html', '/icon-192.png', '/icon-512.png', '/apple-touch-icon.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/')) return;                  // 状态永远实时取，不缓存

  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(() => caches.match('/offline.html')));
    return;
  }
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.ok && !url.pathname.startsWith('/api/')) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      })
      .catch(() => caches.match(req).then((r) => r || caches.match('/offline.html')))
  );
});
