/* ============================================================
   ORBIT — Service Worker

   Задача: приложение должно открываться без интернета вообще.
   Сами задачи живут в IndexedDB (этим занимается index.html), а здесь
   кэшируется оболочка: разметка, иконки и шрифты.

   Стратегия — «сначала кэш, обновление в фоне». Раньше было наоборот
   (сначала сеть), из-за чего запуск ждал ответа сервера даже при рабочем
   кэше, а на медленной связи это заметная задержка.
============================================================ */

const VERSION = 'v3';
const SHELL_CACHE = `orbit-shell-${VERSION}`;
const FONT_CACHE  = `orbit-fonts-${VERSION}`;

const CORE_ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
  './icon-512-maskable.png',
  './icon-round-192.png',
  './icon-round-512.png',
];

/* ---------- Установка: складываем оболочку в кэш ---------- */
self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    // Иконки могут отсутствовать — тогда addAll() провалил бы установку
    // целиком. Кладём по одному и молча пропускаем то, чего нет.
    await Promise.all(CORE_ASSETS.map(async (url) => {
      try { await cache.add(new Request(url, {cache: 'reload'})); }
      catch (_e) { /* файла нет — не повод ломать установку */ }
    }));
    self.skipWaiting();
  })());
});

/* ---------- Активация: чистим кэши прошлых версий ---------- */
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(
      names
        .filter((n) => n.startsWith('orbit-') && !n.endsWith(VERSION))
        .map((n) => caches.delete(n))
    );
    await self.clients.claim();
  })());
});

self.addEventListener('message', (event) => {
  if (event.data === 'skip-waiting') self.skipWaiting();
});

/* ---------- Перехват запросов ---------- */
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Данные не кэшируем: устаревшие задачи хуже, чем их отсутствие.
  // Об офлайне для них заботится IndexedDB на стороне страницы.
  if (url.pathname.startsWith('/api/')) return;

  // Открытие приложения: отдаём оболочку из кэша сразу, свежую версию
  // подтягиваем в фоне — запуск не зависит от сети.
  if (req.mode === 'navigate') {
    event.respondWith(shellFirst(req));
    return;
  }

  // Шрифты Google: без них офлайн приложение теряет вид.
  if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    event.respondWith(cacheFirst(req, FONT_CACHE));
    return;
  }

  if (url.origin === self.location.origin) {
    event.respondWith(staleWhileRevalidate(req, SHELL_CACHE));
  }
});

/* ---------- Стратегии ---------- */

async function shellFirst(req) {
  const cache = await caches.open(SHELL_CACHE);
  const cached = (await cache.match('./index.html')) || (await cache.match('./'));

  const network = fetch(req)
    .then((resp) => {
      if (resp && resp.ok) cache.put('./index.html', resp.clone());
      return resp;
    })
    .catch(() => null);

  // Есть копия — показываем немедленно, обновление доедет к следующему запуску
  if (cached) { network.catch(() => {}); return cached; }

  const fresh = await network;
  if (fresh) return fresh;

  return new Response(
    '<!doctype html><meta charset="utf-8"><title>Orbit</title>' +
    '<body style="margin:0;display:flex;align-items:center;justify-content:center;' +
    'height:100vh;background:#14161f;color:#b6bccd;font:15px/1.6 system-ui,sans-serif;' +
    'text-align:center;padding:24px">' +
    '<div><div style="font-size:38px;margin-bottom:12px">🪐</div>' +
    'Orbit ещё не сохранён для работы без сети.<br>Откройте приложение один раз с интернетом.</div>',
    {headers: {'Content-Type': 'text/html; charset=utf-8'}}
  );
}

async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  if (cached) return cached;
  try {
    const resp = await fetch(req);
    // Ответы шрифтов приходят непрозрачными (opaque) — их тоже кладём в кэш:
    // прочитать содержимое нельзя, а отдать браузеру повторно можно.
    if (resp && (resp.ok || resp.type === 'opaque')) cache.put(req, resp.clone());
    return resp;
  } catch (_e) {
    return cached || Response.error();
  }
}

async function staleWhileRevalidate(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);

  const network = fetch(req)
    .then((resp) => {
      if (resp && resp.ok) cache.put(req, resp.clone());
      return resp;
    })
    .catch(() => null);

  if (cached) { network.catch(() => {}); return cached; }
  const fresh = await network;
  return fresh || Response.error();
}
