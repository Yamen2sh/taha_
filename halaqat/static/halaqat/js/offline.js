/*
 * العمل دون اتصال + تقليل الطلبات (TahaSync)
 * ─────────────────────────────────────────────
 * • أي حفظ (حضور / تسميع / نقل طالب / ربط أستاذ) يمرّ عبر TahaSync.post:
 *     – متصل: طلب واحد كالمعتاد.
 *     – غير متصل (أو فشل الشبكة): يُحفظ الطلب في طابور محلي (localStorage) وتُكمل الواجهة
 *       عملها كأنه حُفظ، ثم يُرسَل تلقائياً عند رجوع الاتصال (بالترتيب، وبلا تكرار).
 * • سجلّ مؤشر صغير أعلى الصفحة يبيّن حالة الاتصال وعدد العمليات المعلّقة.
 * • تخزين مؤقت لصفحات التنقّل عبر Service Worker لتبقى التبويبات تعمل دون اتصال.
 * • StudentIndex يحفظ قوائم الطلاب محلياً، فتُعاد رسم القوائم فوراً بلا طلب.
 */
(function () {
  'use strict';

  const Q_KEY = 'taha_sync_queue_v1';
  const toast = (m, t) => { if (window.showToast) window.showToast(m, t || 'info', 5000); };
  const csrf = () => (typeof window.getCsrf === 'function' ? window.getCsrf() : '');

  /* ───────── الطابور المحلي ───────── */
  function readQueue() {
    try { return JSON.parse(localStorage.getItem(Q_KEY) || '[]'); } catch (e) { return []; }
  }
  function writeQueue(q) {
    let ok = true;
    try { localStorage.setItem(Q_KEY, JSON.stringify(q)); }
    catch (e) {
      ok = false;
      // المساحة ممتلئة؟ نحرّر صفحات HTML المحفوظة (الأثقل) ونعيد المحاولة — العمليات أهم
      try {
        Object.keys(localStorage).filter(k => k.startsWith('taha_cache_v1:')).forEach(k => localStorage.removeItem(k));
        localStorage.setItem(Q_KEY, JSON.stringify(q));
        ok = true;
      } catch (e2) { ok = false; }
    }
    if (!ok) toast('⚠️ تعذّر حفظ العملية محلياً — أبقِ الصفحة مفتوحة حتى يعود الاتصال', 'error', 8000);
    renderBadge();
  }
  function enqueue(url, body, opts) {
    const q = readQueue();
    const item = {
      id: (Date.now() + '-' + Math.random().toString(36).slice(2, 8)),
      url, body,
      key: opts && opts.key ? opts.key : null,
      label: (opts && opts.label) || 'عملية محفوظة',
      client_uid: (opts && opts.client_uid) || null,
      at: Date.now(),
    };
    if (item.key) {                                  // آخر قيمة لنفس المفتاح تكفي (حضور مثلاً)
      const i = q.findIndex(x => x.key === item.key);
      if (i >= 0) { q[i] = Object.assign({}, item, {id: q[i].id}); writeQueue(q); return item; }
    }
    q.push(item);
    writeQueue(q);
    return item;
  }

  let flushing = false;
  async function flush() {
    if (flushing || !navigator.onLine) return;
    let q = readQueue();
    if (!q.length) return;
    flushing = true;
    let sent = 0;
    try {
      while (q.length) {
        const item = q[0];
        const body = new URLSearchParams(item.body);
        if (item.client_uid) body.set('client_uid', item.client_uid);
        let res;
        try {
          res = await fetch(item.url, {
            method: 'POST',
            headers: {'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest',
                      'Content-Type': 'application/x-www-form-urlencoded'},
            body: body.toString(),
          });
        } catch (e) { break; }                     // الشبكة انقطعت ثانية → نبقى في الطابور
        if (res.status === 403 || res.status === 400 || res.ok) {
          q.shift(); writeQueue(q); sent++;        // حُفظت (أو مرفوضة نهائياً) → لا نعيدها
        } else { break; }
      }
    } finally {
      flushing = false;
      renderBadge();
      if (sent) {
        toast(`✅ تم إرسال ${sent} عملية محفوظة بعد رجوع الاتصال`, 'success');
        document.dispatchEvent(new CustomEvent('taha:synced', {detail: {count: sent}}));
      }
    }
  }

  /* ───────── إرسال مع طابور احتياطي ───────── */
  async function post(url, payload, opts) {
    const body = payload instanceof URLSearchParams ? payload.toString() : new URLSearchParams(payload).toString();
    if (!navigator.onLine) {
      enqueue(url, body, opts);
      return {ok: true, queued: true};
    }
    let res;
    try {
      res = await fetch(url, {
        method: 'POST',
        headers: {'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest',
                  'Content-Type': 'application/x-www-form-urlencoded'},
        body,
      });
    } catch (e) {
      // فشل شبكة (لا استجابة): نحفظها محلياً ونكمل
      enqueue(url, body, opts);
      return {ok: true, queued: true};
    }
    let json = null;
    try { json = await res.json(); } catch (e) { json = null; }
    if (!res.ok || (json && json.ok === false)) {
      const msg = (json && json.error) || 'تعذّر الحفظ';
      const err = new Error(msg);
      err.status = res.status;
      throw err;
    }
    return json || {ok: true};
  }

  /* ───────── مؤشر الحالة ───────── */
  function renderBadge() {
    let el = document.getElementById('sync-badge');
    if (!el) {
      el = document.createElement('div');
      el.id = 'sync-badge';
      el.className = 'sync-badge';
      el.setAttribute('role', 'status');
      document.body.appendChild(el);
    }
    const pending = readQueue().length;
    const online = navigator.onLine;
    el.className = 'sync-badge' + (online ? '' : ' offline') + (pending ? ' pending' : '');
    if (!online) {
      el.innerHTML = `📴 بلا اتصال${pending ? ` · ${pending} بانتظار الإرسال` : ''}`;
      el.title = 'التعديلات تُحفظ على هذا الجهاز وتُرسل تلقائياً عند رجوع الاتصال';
      el.hidden = false;
    } else if (pending) {
      el.innerHTML = `⏳ ${pending} عملية بانتظار الإرسال <button type="button">إرسال الآن</button>`;
      el.hidden = false;
      el.querySelector('button').onclick = flush;
    } else {
      el.hidden = true;
    }
  }

  /* ───────── Service Worker: تخزين صفحات التنقّل ───────── */
  function registerSW() {
    if (!('serviceWorker' in navigator)) return;
    navigator.serviceWorker.register('/sw.js', {scope: '/'}).then(reg => {
      // ابحث عن نسخة جديدة من الـSW عند كل تحميل، وأعِد تحميل الصفحة مرة واحدة
      // عند توفّرها — حتى لا يبقى المتصفح على ملفات JS/CSS قديمة بعد النشر.
      const activate = () => reg.update().catch(() => {});
      activate();
      reg.addEventListener('updatefound', () => {
        const nw = reg.installing;
        if (!nw) return;
        nw.addEventListener('statechange', () => {
          if (nw.state === 'installed' && navigator.serviceWorker.controller &&
              !sessionStorage.getItem('sw_reloaded')) {
            sessionStorage.setItem('sw_reloaded', '1');
            location.reload();
          }
        });
      });
    }).catch(() => {});
  }

  /* ───────── بدء التشغيل ───────── */
  window.addEventListener('online', () => { renderBadge(); flush(); });
  window.addEventListener('offline', () => { renderBadge(); toast('📴 انقطع الاتصال — سيُحفظ عملك على الجهاز ويُرسل تلقائياً', 'warn', 6000); });
  document.addEventListener('DOMContentLoaded', () => {
    renderBadge();
    registerSW();
    setTimeout(flush, 1500);
    setInterval(flush, 45000);
  });
  window.addEventListener('load', renderBadge);

  /* تحديث قسري: امسح كاش الملفات وأعِد التحميل (يُستعمل عند التصحيح من الكونسول). */
  async function hardRefresh() {
    try {
      if ('caches' in window) {
        const keys = await caches.keys();
        await Promise.all(keys.map(k => caches.delete(k)));
      }
      sessionStorage.removeItem('sw_reloaded');
    } catch (e) { /* تجاهل */ }
    location.reload();
  }

  window.TahaSync = {
    post, flush, enqueue, hardRefresh,
    pending: () => readQueue().length,
    isOnline: () => navigator.onLine,
    status: () => ({online: navigator.onLine, pending: readQueue().length}),
  };
})();
