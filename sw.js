/* ============================================================
   ORBIT — Service Worker
   Кэширует статические файлы интерфейса, чтобы сайт открывался
   даже без сети (сами задачи всё равно требуют связи с сервером —
   это отдельный уровень, "оффлайн-первый" режим можно добавить позже).
============================================================ */

const CACHE_NAME = 'orbit-shell-v1';
const CORE_ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './icons/icon-192.png',
  './icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;

  // API-запросы (/api/...) никогда не кэшируем — данные должны быть свежими.
  if (req.url.includes('/api/')) {
    return;
  }

  // Для остального: сначала пробуем сеть (чтобы видеть последние правки при
  // разработке), при обрыве связи отдаём то, что есть в кэше.
  event.respondWith(
    fetch(req)
      .then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
        return resp;
      })
      .catch(() => caches.match(req).then((cached) => cached || caches.match('./index.html')))
  );
});
