/*
 * فهرس الطلاب المخزَّن محلياً في المتصفح (localStorage / IndexedDB).
 *
 * الهدف: تقليل الطلبات على السيرفر والعمل حتى لو انقطع الاتصال:
 *   • يُحمَّل الفهرس مرة واحدة ويُستخدم للبحث وللأسماء والوسوم (آخر صفحة مسمّعة وتاريخ الميلاد).
 *   • تُحفظ كل «قائمة طلاب حلقة» وكل «غياب/تسميع» في ذاكرة محلية، فتُفتح التبويبات
 *     وتُستعرض البيانات بلا اتصال.
 *   • أي تعديل يجعل الصفحة تعمل دون اتصال (queue متزامن) ثم يُرسَل تلقائياً عند رجوع الشبكة.
 *
 * الاستخدام:
 *   StudentIndex.search('محمد', 15)          → Promise<[{id,name,circle_id,circle_name,last_page,birth,last_on}]>
 *   StudentIndex.get(id) / StudentIndex.byCircle(circleId)
 *   StudentIndex.putLocal(id, {last_page, birth, last_on})
 *   StudentIndex.saveList(circleId, [{id,name,last_page,birth,last_on}])   // قائمة الحلقة كما عُرضت
 *   StudentIndex.list(circleId)                                            // من الذاكرة المحلية
 */
(function () {
  const KEY = 'taha_students_index_v2';
  const LIST_KEY = 'taha_circle_lists_v2';
  const CACHE_PREFIX = 'taha_cache_v1:';
  let data = null;          // {v, students: [[id, name, circle_id, circle_name, last_page, birth, last_on], ...]}
  let refreshing = null;
  const listeners = new Set();

  // توحيد الحروف العربية: أ/إ/آ→ا، ى→ي، ة→ه، حذف التشكيل والتطويل
  function norm(s) {
    return String(s || '')
      .replace(/[ً-ْٰـ]/g, '')
      .replace(/[أإآٱ]/g, 'ا').replace(/ى/g, 'ي').replace(/ة/g, 'ه')
      .replace(/ؤ/g, 'و').replace(/ئ/g, 'ي')
      .replace(/\s+/g, ' ').trim().toLowerCase();
  }

  function load() {
    try { const raw = localStorage.getItem(KEY); if (raw) data = JSON.parse(raw); } catch (e) { data = null; }
    if (data && data.students) data.students.forEach(r => { r[7] = norm(r[1]); });
  }

  function save() {
    try {
      localStorage.setItem(KEY, JSON.stringify({v: data.v, students: data.students.map(r => r.slice(0, 7))}));
    } catch (e) { /* مساحة ممتلئة أو وضع خاص — نكتفي بالذاكرة */ }
  }

  function refresh() {
    if (refreshing) return refreshing;
    if (!navigator.onLine) return Promise.resolve(data);
    const v = data && data.v ? '?v=' + encodeURIComponent(data.v) : '';
    refreshing = fetch('/students/index.json' + v, {headers: {'X-Requested-With': 'XMLHttpRequest'}, credentials: 'same-origin'})
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(j => {
        if (!j.same && j.students) {
          j.students.forEach(r => { r[7] = norm(r[1]); });
          data = j; save();
          listeners.forEach(fn => { try { fn(data); } catch (e) {} });
        }
        return data;
      })
      .catch(() => data)
      .finally(() => { setTimeout(() => { refreshing = null; }, 30000); });
    return refreshing;
  }

  function ready() {
    if (data && data.students) { refresh(); return Promise.resolve(data); }   // تحديث بالخلفية
    return refresh();
  }

  function search(q, limit) {
    limit = limit || 15;
    const nq = norm(q);
    if (!nq) return Promise.resolve([]);
    const words = nq.split(' ');
    return ready().then(d => {
      if (!d || !d.students) return [];
      const out = [];
      for (const r of d.students) {
        const n = r[7];
        if (words.every(w => n.includes(w))) {
          out.push({id: r[0], name: r[1], circle_id: r[2], circle_name: r[3],
                    last_page: r[4], birth: r[5], last_on: r[6],
                    _start: n.startsWith(nq) ? 0 : 1});
        }
      }
      out.sort((a, b) => a._start - b._start || a.name.localeCompare(b.name, 'ar'));
      return out.slice(0, limit);
    });
  }

  function get(id) {
    if (!data || !data.students) return null;
    const r = data.students.find(x => String(x[0]) === String(id));
    return r ? {id: r[0], name: r[1], circle_id: r[2], circle_name: r[3],
                last_page: r[4], birth: r[5], last_on: r[6]} : null;
  }

  /* تحديث وسم الطالب محلياً بعد أي تسميع/تعديل (بلا انتظار السيرفر) */
  function putLocal(id, patch) {
    if (!data || !data.students) return;
    const r = data.students.find(x => String(x[0]) === String(id));
    if (!r) return;
    if (patch.last_page !== undefined) r[4] = patch.last_page;
    if (patch.birth !== undefined) r[5] = patch.birth;
    if (patch.last_on !== undefined) r[6] = patch.last_on;
    if (patch.circle_id !== undefined) r[2] = patch.circle_id;
    save();
  }

  /* ── قوائم الطلاب لكل حلقة (للعمل دون اتصال) ── */
  function saveList(circleId, rows) {
    try {
      const all = JSON.parse(localStorage.getItem(LIST_KEY) || '{}');
      all[circleId] = {at: Date.now(), rows};
      localStorage.setItem(LIST_KEY, JSON.stringify(all));
    } catch (e) { /* تجاهل */ }
  }
  function list(circleId) {
    try {
      const all = JSON.parse(localStorage.getItem(LIST_KEY) || '{}');
      return (all[circleId] || {}).rows || null;
    } catch (e) { return null; }
  }

  /* ── تخزين صفحات كاملة (HTML) لفتحها دون اتصال ── */
  function saveCache(path, html) {
    try { localStorage.setItem(CACHE_PREFIX + path, JSON.stringify({at: Date.now(), html})); } catch (e) {}
  }
  function readCache(path) {
    try {
      const raw = localStorage.getItem(CACHE_PREFIX + path);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  function clear() {
    try {
      localStorage.removeItem(KEY);
      localStorage.removeItem(LIST_KEY);
      Object.keys(localStorage).filter(k => k.startsWith(CACHE_PREFIX)).forEach(k => localStorage.removeItem(k));
    } catch (e) {}
    data = null;
  }

  load();
  window.StudentIndex = {search, refresh, clear, norm, get, putLocal, saveList, list,
                         saveCache, readCache, onUpdate: fn => listeners.add(fn),
                         count: () => (data && data.students ? data.students.length : 0)};
  if (document.readyState !== 'loading') ready(); else document.addEventListener('DOMContentLoaded', ready);
})();
