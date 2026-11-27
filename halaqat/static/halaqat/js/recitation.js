/*
 * «الدورات القرآنية» — نافذة التسميع:
 *   • بالصفحات: من صفحة … إلى صفحة (افتراضياً صفحة واحدة) مع أزرار − / + وتسمية السورة لكل صفحة.
 *   • بأسماء السور (آخر جزأين: الملك ← الناس): اختيار السورة ثم صفحتها الأولى/الثانية/الثالثة…
 * تعتمد على: getCsrf / showToast (base.html) وقائمة السور والصفحات المضمّنة في الصفحة.
 * الحفظ فوري في السيرفر، وتُحدَّث البطاقة (آخر صفحة + وسم الصفحة) تلقائياً بلا إعادة تحميل.
 */
(function () {
  'use strict';

  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  const root = $('rc-root');
  if (!root) return;
  const SURAHS = JSON.parse($('surahs-data').textContent);            // [{n, name, ayahs}]
  const SURAH_SETS = JSON.parse($('surah-choices-data').textContent); // [{n, name, ayahs, pages:[..]}]
  const PAGES = window.QURAN_PAGES || [];                             // [[p, fs, fa, ts, ta], ...]
  const BY_N = {};
  SURAHS.forEach(s => { BY_N[s.n] = s; });
  const PAGE = {};
  PAGES.forEach(r => { PAGE[r[0]] = {fs: r[1], fa: r[2], ts: r[3], ta: r[4]}; });
  const LAST_PAGE = parseInt(root.dataset.lastPage, 10) || 604;
  const SET_BY_N = {};
  SURAH_SETS.forEach(s => { SET_BY_N[s.n] = s; });

  const PAGE_DATE = root.dataset.date, TODAY = root.dataset.today;
  const U = {info: root.dataset.infoUrl, add: root.dataset.addUrl, update: root.dataset.updateUrl, del: root.dataset.deleteUrl};
  const urlOf = (tpl, id) => tpl.replace('/0/', '/' + id + '/');

  let cur = null;              // بيانات الطالب المفتوح
  let editingId = null;        // معرّف التسميع قيد التعديل
  let mode = 'pages';          // pages | surah

  /* ───────── أدوات ───────── */
  async function api(url, body) {
    const opt = {headers: {'X-Requested-With': 'XMLHttpRequest'}};
    if (body !== undefined) {
      opt.method = 'POST';
      opt.headers['X-CSRFToken'] = getCsrf();
      opt.body = new URLSearchParams(body);
    }
    const res = await fetch(url, opt);
    const data = await res.json().catch(() => ({ok: false, error: 'استجابة غير صالحة'}));
    if (!res.ok || data.ok === false) throw new Error(data.error || 'حدث خطأ');
    return data;
  }

  function agoText(n) {
    if (n <= 0) return 'اليوم';
    if (n === 1) return 'أمس';
    if (n === 2) return 'قبل يومين';
    if (n <= 10) return `قبل ${n} أيام`;
    return `قبل ${n} يوماً`;
  }

  const ORD = ['الأولى', 'الثانية', 'الثالثة', 'الرابعة', 'الخامسة', 'السادسة', 'السابعة',
    'الثامنة', 'التاسعة', 'العاشرة', 'الحادية عشرة', 'الثانية عشرة'];
  const ord = n => ORD[n - 1] || ('رقم ' + n);

  /* اسم الصفحة: «ص 5 · البقرة 40» */
  function pageLabel(p) {
    const b = PAGE[p];
    if (!b) return 'ص ' + p;
    const name = (BY_N[b.fs] || {}).name || '';
    return `ص ${p} · ${name} ${b.fa}`;
  }

  function fmtItem(it) {
    if (it.mode === 'surah' && it.surah) return it.range;
    if (it.from_page) return it.to_page && it.to_page !== it.from_page
      ? `صفحة ${it.from_page}–${it.to_page}` : `صفحة ${it.from_page}`;
    return it.range;
  }

  /* مجموعات الأزرار */
  function segSet(el, value) {
    [...el.children].forEach(b => {
      const on = b.dataset.v === value;
      b.classList.toggle('on', on);
      b.setAttribute('aria-checked', on ? 'true' : 'false');
    });
  }
  const segGet = el => { const b = el.querySelector('.on'); return b ? b.dataset.v : ''; };
  ['rc-kind', 'rc-grade'].forEach(id => $(id).addEventListener('click', e => {
    const b = e.target.closest('button[data-v]');
    if (b) segSet($(id), b.dataset.v);
  }));

  /* ───────── الوضع: صفحات / أسماء السور ───────── */
  function setMode(m) {
    mode = m === 'surah' ? 'surah' : 'pages';
    segSet($('rc-mode'), mode);
    $('rc-pages-mode').hidden = mode !== 'pages';
    $('rc-surah-mode').hidden = mode !== 'surah';
    $('rc-page-only').hidden = mode !== 'pages';
    refresh();
  }
  $('rc-mode').addEventListener('click', e => {
    const b = e.target.closest('button[data-v]');
    if (b) setMode(b.dataset.v);
  });

  /* اختيار السورة في وضع أسماء السور (آخر جزأين فقط) */
  $('rc-surah').innerHTML = SURAH_SETS.map(s => `<option value="${s.n}">${esc(s.name)}</option>`).join('');

  function fillSurahPages() {
    const n = parseInt($('rc-surah').value, 10);
    const set = SET_BY_N[n];
    if (!set) return;
    const opts = set.pages.map((p, i) => `<option value="${p}">${ord(i + 1)} — ص ${p}</option>`).join('');
    $('rc-s-p1').innerHTML = opts;
    $('rc-s-p2').innerHTML = opts;
    $('rc-s-p2').value = set.pages[Math.min(1, set.pages.length - 1)];
    $('rc-surah-pages').textContent = set.pages.length > 1
      ? `صفحات ${set.name}: ${set.pages[0]}–${set.pages[set.pages.length - 1]}`
      : `صفحة ${set.name}: ${set.pages[0]}`;
  }
  $('rc-surah').addEventListener('change', () => { fillSurahPages(); refresh(); });
  $('rc-s-p1').addEventListener('change', () => {
    // «إلى» تتبع «من» تلقائياً حتى يغيّرها المستخدم
    if ($('rc-s-p2').value < $('rc-s-p1').value) $('rc-s-p2').value = $('rc-s-p1').value;
    refresh();
  });
  $('rc-s-p2').addEventListener('change', refresh);

  /* ───────── الصفحات ───────── */
  document.querySelectorAll('.rc-step').forEach(btn => btn.addEventListener('click', () => {
    const input = $(btn.dataset.for);
    const v = (parseInt(input.value, 10) || (btn.dataset.for === 'rc-to-page' ? parseInt($('rc-from-page').value, 10) : 0)) + parseInt(btn.dataset.step, 10);
    input.value = Math.max(1, Math.min(LAST_PAGE, v || 1));
    if (btn.dataset.for === 'rc-from-page' && !$('rc-to-page').value) $('rc-to-page').value = input.value;
    refresh();
  }));

  ['rc-from-page', 'rc-to-page'].forEach(id => $(id).addEventListener('input', refresh));

  $('rc-page-only').addEventListener('click', () => {
    $('rc-to-page').value = $('rc-from-page').value;
    refresh();
  });

  $('rc-continue').addEventListener('click', () => {
    const nxt = nextPageAfterLast();
    if (!nxt) return;
    if (nxt.mode === 'surah') {
      setMode('surah');
      $('rc-surah').value = nxt.surah;
      fillSurahPages();
      $('rc-s-p1').value = nxt.page;
      $('rc-s-p2').value = nxt.page;
    } else {
      setMode('pages');
      $('rc-from-page').value = nxt.page;
      $('rc-to-page').value = nxt.page;
    }
    segSet($('rc-kind'), 'new');
    refresh();
  });

  /* الصفحة التي تلي آخر تسميع (للتكملة) — وإن دخلنا آخر جزأين فباسم السورة */
  function nextPageAfterLast() {
    const l = cur && cur.last;
    if (!l) return null;
    const lastPage = l.to_page;
    if (!lastPage) return null;
    const next = lastPage + 1;
    if (next > LAST_PAGE) return null;
    const b = PAGE[next];
    if (b && b.fs >= 67 && SET_BY_N[b.fs]) return {mode: 'surah', surah: b.fs, page: next};
    return {mode: 'pages', page: next};
  }

  /* ───────── المعاينة والتحقق ───────── */
  function currentRange() {
    if (mode === 'surah') {
      const n = parseInt($('rc-surah').value, 10);
      const p1 = parseInt($('rc-s-p1').value, 10), p2 = parseInt($('rc-s-p2').value, 10) || p1;
      return {mode: 'surah', surah: n, from: Math.min(p1, p2), to: Math.max(p1, p2)};
    }
    const f = parseInt($('rc-from-page').value, 10);
    const t = parseInt($('rc-to-page').value, 10) || f;
    return {mode: 'pages', from: f ? Math.min(f, t) : null, to: f ? Math.max(f, t) : null};
  }

  function refresh() {
    const box = $('rc-preview');
    if (mode === 'pages') {
      const r = currentRange();
      $('rc-from-info').textContent = r.from ? pageLabel(r.from) : '';
      $('rc-to-info').textContent = r.to ? pageLabel(r.to) : '';
      if (!r.from) { box.className = 'rc-preview'; box.textContent = ''; return; }
      if (r.from < 1 || r.to > LAST_PAGE) { box.className = 'rc-preview bad'; box.textContent = `⚠️ رقم الصفحة من 1 إلى ${LAST_PAGE}`; return; }
      const b1 = PAGE[r.from], b2 = PAGE[r.to];
      const count = r.to - r.from + 1;
      box.className = 'rc-preview ok';
      box.innerHTML = `📖 <b>صفحة ${r.from === r.to ? r.from : r.from + '–' + r.to}</b> · ${count} صفحة`
        + (b1 && b2 ? ` <span style="color:#9c8a71">(${esc((BY_N[b1.fs] || {}).name || '')} ${b1.fa} ← ${esc((BY_N[b2.ts] || {}).name || '')} ${b2.ta})</span>` : '');
    } else {
      const r = currentRange();
      const set = SET_BY_N[r.surah];
      box.className = 'rc-preview ok';
      const o1 = set ? set.pages.indexOf(r.from) + 1 : 0;
      const o2 = set ? set.pages.indexOf(r.to) + 1 : 0;
      const label = o1 === o2 ? `الصفحة ${ord(o1)}` : `${ord(o1)} و${ord(o2)}`;
      box.innerHTML = `📚 <b>${esc((set || {}).name || '')} — ${label}</b> · ${r.to - r.from + 1} صفحة`;
    }
  }

  /* ───────── النافذة ───────── */
  function resetForm() {
    editingId = null;
    $('rc-edit-banner').hidden = true;
    $('rc-save').innerHTML = '💾 حفظ التسميع';
    setMode('pages');
    const l = cur && cur.last;
    const start = l && l.to_page ? Math.min(LAST_PAGE, l.to_page + 1) : null;
    $('rc-from-page').value = start || '';
    $('rc-to-page').value = start || '';
    if (l && l.to_page && PAGE[start] && PAGE[start].fs >= 67 && SET_BY_N[PAGE[start].fs]) {
      setMode('surah');
      $('rc-surah').value = PAGE[start].fs;
      fillSurahPages();
      $('rc-s-p1').value = start;
      $('rc-s-p2').value = start;
    } else {
      fillSurahPages();
    }
    $('rc-notes').value = '';
    $('rc-date').value = PAGE_DATE;
    segSet($('rc-kind'), 'new');
    segSet($('rc-grade'), '');
    $('rc-continue').hidden = !nextPageAfterLast();
    refresh();
  }

  function renderSheet() {
    $('rc-title').textContent = cur.student.name;
    const c = cur.student.circle || '';
    $('rc-sub').textContent = (c.startsWith('حلقة') ? c : 'حلقة ' + c) + (cur.total ? ` · ${cur.total} تسميع مسجّل` : '');
    renderHistory();
  }

  function renderHistory() {
    const h = cur.history;
    $('rc-total').textContent = cur.total > h.length ? `(آخر ${h.length} من ${cur.total})` : (cur.total ? `(${cur.total})` : '');
    $('rc-history').innerHTML = h.length ? h.map(x => `
      <div class="rc-h" data-id="${x.id}">
        <div class="rc-h-main"><b>${esc(fmtItem(x))}</b> <span class="rc-h-n">${x.pages ? x.pages + ' صفحة' : (x.ayahs + ' آية')}</span></div>
        <div class="rc-h-meta">${esc(x.date_display)} · ${agoText(x.days_ago)} · ${esc(x.kind_display)}${x.grade_display ? ' · ' + esc(x.grade_display) : ''}</div>
        ${x.notes ? `<div class="rc-h-notes">${esc(x.notes)}</div>` : ''}
        <div class="rc-h-actions">
          <button type="button" class="qs-btn" data-edit="${x.id}">✏️ تعديل</button>
          <button type="button" class="qs-btn" data-del="${x.id}">🗑 حذف</button>
        </div>
      </div>`).join('') : '<p class="rc-empty">لا توجد تسميعات مسجّلة بعد لهذا الطالب.</p>';
  }

  function fillFormFromItem(x) {
    editingId = x.id;
    $('rc-edit-banner').hidden = false;
    $('rc-save').innerHTML = '💾 حفظ التعديل';
    if (x.mode === 'surah' && x.surah) {
      setMode('surah');
      $('rc-surah').value = x.surah;
      fillSurahPages();
      $('rc-s-p1').value = x.from_page;
      $('rc-s-p2').value = x.to_page || x.from_page;
    } else {
      setMode('pages');
      $('rc-from-page').value = x.from_page || '';
      $('rc-to-page').value = x.to_page || x.from_page || '';
    }
    segSet($('rc-kind'), x.kind);
    segSet($('rc-grade'), x.grade || '');
    $('rc-notes').value = x.notes || '';
    $('rc-date').value = x.date;
    refresh();
    $('rc-sheet')?.scrollTo?.({top: 0, behavior: 'smooth'});
  }

  $('rc-history').addEventListener('click', async e => {
    const ed = e.target.closest('[data-edit]'), dl = e.target.closest('[data-del]');
    if (ed) {
      const item = cur.history.find(x => String(x.id) === ed.dataset.edit);
      if (item) fillFormFromItem(item);
      return;
    }
    if (dl) {
      if (!confirm('حذف هذا التسميع نهائياً؟')) return;
      try {
        await api(urlOf(U.del, dl.dataset.del), {ctx_date: PAGE_DATE});
        await reload();
        toast('تم الحذف', 'info');
      } catch (err) { toast(err.message, 'error'); }
    }
  });

  $('rc-cancel-edit').addEventListener('click', resetForm);

  /* ───────── الحفظ ───────── */
  const toast = (m, t) => { if (window.showToast) window.showToast(m, t || 'success'); };

  async function save() {
    const r = currentRange();
    if (mode === 'pages' && !r.from) { toast('اختر رقم الصفحة', 'warn'); $('rc-from-page').focus(); return; }
    const body = {
      date: $('rc-date').value || PAGE_DATE,
      kind: segGet($('rc-kind')) || 'new',
      grade: segGet($('rc-grade')) || '',
      notes: $('rc-notes').value || '',
      mode: r.mode,
      from_page: r.from,
      to_page: r.to,
      ctx_date: PAGE_DATE,
    };
    if (!editingId) body.client_uid = (Date.now().toString(36) + Math.random().toString(36).slice(2, 8));
    if (r.mode === 'surah') body.surah = r.surah;
    const btn = $('rc-save');
    btn.disabled = true;
    const orig = btn.innerHTML;
    btn.innerHTML = '<span class="btn-spinner"></span> جاري الحفظ…';
    try {
      const data = await api(urlOf(editingId ? U.update : U.add, editingId || cur.student.id), body);
      applyPayload(data);
      toast(editingId ? 'تم تعديل التسميع ✓' : 'تم حفظ التسميع ✓', 'success');
      resetForm();
      flashRow();
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = editingId ? '💾 حفظ التعديل' : orig;
    }
  }
  $('rc-save').addEventListener('click', save);

  function flashRow() {
    const row = document.getElementById('rc-row-' + cur.student.id);
    if (!row) return;
    row.classList.add('flash');
    setTimeout(() => row.classList.remove('flash'), 1500);
  }

  /* يعكس بيانات السيرفر على البطاقة في القائمة (بلا إعادة تحميل الصفحة) */
  function applyPayload(data) {
    cur = data;
    renderSheet();
    const row = document.getElementById('rc-row-' + data.student.id);
    if (!row) return;
    const lastBox = row.querySelector('[data-last]');
    const dayBox = row.querySelector('[data-day]');
    const l = data.last;
    if (lastBox) {
      lastBox.innerHTML = l
        ? `${esc(fmtItem(l))} · ${esc(l.date_display)} <span class="rc-ago">${agoText(l.days_ago)}</span>`
        : '<span class="rc-none">لم يُسمَّع بعد</span>';
    }
    if (dayBox) {
      dayBox.innerHTML = (data.day || []).map(x =>
        `<span class="rc-chip${x.kind === 'review' ? ' review' : ''}">${esc(fmtItem(x))}${x.grade_display ? ' · ' + esc(x.grade_display) : ''}</span>`).join('');
    }
    // وسم آخر صفحة مسمّعة
    const tags = row.querySelector('.rc-nameline');
    if (tags) {
      let tag = tags.querySelector('.mini-tag.page');
      const page = l ? (l.to_page || null) : null;
      if (page) {
        if (!tag) { tag = document.createElement('span'); tag.className = 'mini-tag page'; tags.appendChild(tag); }
        tag.textContent = '📖 ص ' + page;
        tag.title = 'آخر صفحة مسمّعة';
      } else if (tag) { tag.remove(); }
    }
    // «سُمِّع» في الملخص
    let heard = 0;
    document.querySelectorAll('#rc-list .rc-row').forEach(r => { if (r.querySelector('.rc-day')?.children.length) heard++; });
    const h = document.getElementById('rc-heard');
    if (h) h.textContent = heard;
  }

  async function reload() {
    const data = await api(urlOf(U.info, cur.student.id) + '?date=' + PAGE_DATE);
    applyPayload(data);
  }

  /* ───────── فتح/إغلاق النافذة ───────── */
  async function openSheet(studentId) {
    try {
      const data = await api(urlOf(U.info, studentId) + '?date=' + PAGE_DATE);
      cur = data;
      renderSheet();
      resetForm();
      $('rc-overlay').hidden = false;
      document.body.classList.add('rc-lock');
      $('rc-from-page').focus();
    } catch (err) { toast(err.message, 'error'); }
  }

  function closeSheet() {
    $('rc-overlay').hidden = true;
    document.body.classList.remove('rc-lock');
    cur = null;
  }

  document.getElementById('rc-list')?.addEventListener('click', e => {
    // زر ＋ تسميع فقط (النقر على الصف لا يفتح شيئاً حتى لا يتعارض مع مربعات الحضور)
    const btn = e.target.closest('[data-open]');
    if (btn) openSheet(btn.dataset.open);
  });
  $('rc-close').addEventListener('click', closeSheet);
  $('rc-overlay').addEventListener('click', e => { if (e.target === $('rc-overlay')) closeSheet(); });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !$('rc-overlay').hidden) closeSheet();
  });
  ['rc-from-page', 'rc-to-page', 'rc-notes'].forEach(id => $(id).addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); save(); }
  }));

  fillSurahPages();
})();
