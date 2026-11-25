/*
 * Service Worker: يسمح بالتنقّل بين التبويبات ولو انقطع الاتصال.
 *  • طلبات GET لصفحات HTML: «الشبكة أولاً» — وعند الفشل تُقدَّم آخر نسخة محفوظة على الجهاز.
 *  • ملفات CSS/JS/الخطوط: «الجهاز أولاً» مع تحديث بالخلفية (staleness منخفض).
 * لا يخزّن إلا صفحة HTML ناجحة (200) وبلا بيانات POST.
 */
const PAGE_CACHE = 'taha-pages-v2';   // رفع الإصدار يمسح النسخ القديمة المحفوظة على كل الأجهزة
const ASSET_CACHE = 'taha-assets-v1';
const OFFLINE_HTML = `<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>بلا اتصال — مسجد طه</title>
<style>body{font-family:system-ui,Tahoma,sans-serif;background:#FAF7F2;color:#4A3420;display:flex;
min-height:100vh;align-items:center;justify-content:center;text-align:center;padding:24px;margin:0}
h1{font-size:20px;margin:0 0 10px}p{color:#8a7a63;line-height:1.9;margin:0}
a{display:inline-block;margin-top:16px;background:#B17F4A;color:#fff;text-decoration:none;
padding:10px 18px;border-radius:10px;font-weight:700}</style></head>
<body><div><h1>📴 لا يوجد اتصال بالإنترنت</h1>
<p>يمكنك متابعة التنقّل بين الصفحات التي فتحتها سابقاً.<br>أي تعديل تجريه الآن سيُحفظ على جهازك ويُرسل تلقائياً عند رجوع الاتصال.</p>
<a href="/home/">المحاولة مرة أخرى</a></div></body></html>`;

self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== PAGE_CACHE && k !== ASSET_CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method === 'POST') {
    // تسجيل الخروج/الدخول: امسح الصفحات المحفوظة أولاً كي لا تبقى بيانات الطلاب على جهاز مشترك
    const u = new URL(req.url);
    if (u.origin === location.origin && (u.pathname === '/logout/' || u.pathname === '/')) {
      event.respondWith((async () => {
        try { await caches.delete(PAGE_CACHE); } catch (e) { /* لا يمنع الخروج */ }
        return fetch(req);
      })());
    }
    return;                                               // بقية الحفظ لا يُعترض أبداً (الطابور في offline.js)
  }
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  const isAsset = /\.(css|js|png|jpg|jpeg|svg|webp|ttf|woff2?|ico)$/i.test(url.pathname);

  if (isAsset) {
    event.respondWith((async () => {
      const cache = await caches.open(ASSET_CACHE);
      const hit = await cache.match(req);
      const network = fetch(req).then(res => {
        if (res && res.ok) cache.put(req, res.clone());
        return res;
      }).catch(() => hit);
      return hit || network;
    })());
    return;
  }

  // صفحات: شبكة أولاً ثم آخر نسخة محفوظة
  event.respondWith((async () => {
    try {
      const res = await fetch(req);
      if (res && res.ok && (res.headers.get('content-type') || '').includes('text/html')) {
        const cache = await caches.open(PAGE_CACHE);
        cache.put(req, res.clone());
      }
      return res;
    } catch (e) {
      const cache = await caches.open(PAGE_CACHE);
      const hit = await cache.match(req) || await cache.match(url.pathname);
      if (hit) return hit;
      return new Response(OFFLINE_HTML, {headers: {'Content-Type': 'text/html; charset=utf-8'}});
    }
  })());
});
