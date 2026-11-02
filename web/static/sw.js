const STATIC_CACHE = 'my-library-static-v1';
const BOOK_CACHE = 'my-library-books-v1';
const STATIC_ASSETS = [
  '/static/css/style.css',
  '/static/css/reader.css',
  '/static/css/account.css',
  '/static/js/app.js',
  '/static/js/reader.js',
  '/static/js/home-features.js',
  '/static/js/profile-features.js',
  '/static/js/profile-advanced.js',
  '/static/js/reader-notes.js',
  '/static/js/pwa.js',
  '/static/manifest.webmanifest',
  '/static/icon.svg'
];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(STATIC_CACHE).then(cache => cache.addAll(STATIC_ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => ![STATIC_CACHE, BOOK_CACHE].includes(key)).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/admin') || url.pathname.startsWith('/profile')) return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).then(response => {
      if (response.ok && (url.pathname === '/' || url.pathname.startsWith('/read/') || url.pathname.startsWith('/authors/'))) {
        caches.open(STATIC_CACHE).then(cache => cache.put(request, response.clone()));
      }
      return response;
    }).catch(async () => (await caches.match(request)) || (await caches.match('/')) || new Response('Вы не в сети. Откройте сохранённую страницу после подключения к интернету.', {status:503, headers:{'Content-Type':'text/plain; charset=utf-8'}})));
    return;
  }
  if (url.pathname.startsWith('/static/uploads/')) {
    event.respondWith((async () => {
      const cache = await caches.open(BOOK_CACHE);
      try {
        const response = await fetch(request);
        const length = Number(response.headers.get('content-length') || 0);
        if (response.ok && (!length || length <= 30 * 1024 * 1024)) await cache.put(request, response.clone());
        return response;
      } catch {
        return (await cache.match(request)) || new Response('Этот файл ещё не сохранён для офлайн-чтения.', {status:503, headers:{'Content-Type':'text/plain; charset=utf-8'}});
      }
    })());
    return;
  }
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(caches.match(request).then(cached => cached || fetch(request).then(response => {
      if (response.ok) caches.open(STATIC_CACHE).then(cache => cache.put(request, response.clone()));
      return response;
    })));
  }
});
