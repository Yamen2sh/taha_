/*
 * صفحة التسميع: تسجيل ما سمّعه كل طالب من القرآن الكريم (سورة/آية → سورة/آية) حلقةً حلقة.
 * تعتمد على: getCsrf / showToast / setBtnLoading (base.html) وعلى قائمة السور المضمَّنة في الصفحة (surahs-data).
 */
(function () {
  'use strict';

  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  const root = $('rc-root');
  if (!root) return;
  const SURAHS = JSON.parse($('surahs-data').textContent);          // [{n, name, ayahs}]
  const BY_N = {}, OFFSET = {};
  let acc = 0;
  SURAHS.forEach(s => { BY_N[s.n] = s; OFFSET[s.n] = acc; acc += s.ayahs; });

  const PAGE_DATE = root.dataset.date, TODAY = root.dataset.today;
  const U = {info: root.dataset.infoUrl, add: root.dataset.addUrl, update: root.dataset.updateUrl, del: root.dataset.deleteUrl};
  const urlOf = (tpl, id) => tpl.replace('/0/', '/' + id + '/');

  let cur = null;                // آخر بيانات للطالب المفتوح: {student, last, history, total, day}
  let editingId = null;          // معرّف التسميع قيد التعديل (null = إضافة)
  let toTouched = false;         // هل غيّر المستخدم «إلى سورة» يدوياً؟ (وإلا تتبع «من سورة»)
  let opening = false;

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

  const absIdx = (s, a) => OFFSET[s] + a;
  const span = r => absIdx(r.ts, r.ta) - absIdx(r.fs, r.fa) + 1;
  function fmt(r) {
    const a = BY_N[r.fs].name, b = BY_N[r.ts].name;
    if (r.fs === r.ts) {
      if (r.fa === r.ta) return `${a} (${r.fa})`;
      if (r.fa === 1 && r.ta === BY_N[r.fs].ayahs) return `${a} (كاملة)`;
      return `${a} (${r.fa}–${r.ta})`;
    }
    return `${a} (${r.fa}) ← ${b} (${r.ta})`;
  }

  /* مجموعات الأزرار (نوع التسميع / التقدير) */
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

  /* ───────── السور والآيات ───────── */
  const opts = SURAHS.map(s => `<option value="${s.n}">${s.n} · ${esc(s.name)}</option>`).join('');
  $('rc-from-surah').innerHTML = opts;
  $('rc-to-surah').innerHTML = opts;

  function readRange() {
    return {
      fs: parseInt($('rc-from-surah').value, 10), fa: parseInt($('rc-from-ayah').value, 10),
      ts: parseInt($('rc-to-surah').value, 10), ta: parseInt($('rc-to-ayah').value, 10),
    };
  }
  function validate(r) {
    if (!(r.fa >= 1 && r.fa <= BY_N[r.fs].ayahs)) return `آية البداية يجب أن تكون بين 1 و${BY_N[r.fs].ayahs}`;
    if (!(r.ta >= 1 && r.ta <= BY_N[r.ts].ayahs)) return `آية النهاية يجب أن تكون بين 1 و${BY_N[r.ts].ayahs}`;
    if (absIdx(r.ts, r.ta) < absIdx(r.fs, r.fa)) return 'نهاية المقطع قبل بدايته';
    return '';
  }
  function refresh() {
    const r = readRange();
    $('rc-from-ayah').max = BY_N[r.fs].ayahs;
    $('rc-to-ayah').max = BY_N[r.ts].ayahs;
    $('rc-from-max').textContent = `(1–${BY_N[r.fs].ayahs})`;
    $('rc-to-max').textContent = `(1–${BY_N[r.ts].ayahs})`;
    const box = $('rc-preview');
    if (!(r.fa > 0 && r.ta > 0)) { box.className = 'rc-preview'; box.textContent = ''; return; }
    const err = validate(r);
    if (err) { box.className = 'rc-preview bad'; box.textContent = '⚠️ ' + err; return; }
    box.className = 'rc-preview ok';
    box.innerHTML = `📖 <b>${esc(fmt(r))}</b> · ${span(r)} آية`;
  }

  $('rc-from-surah').addEventListener('change', () => {
    if (!toTouched) $('rc-to-surah').value = $('rc-from-surah').value;
    refresh();
  });
  $('rc-to-surah').addEventListener('change', () => { toTouched = true; refresh(); });
  ['rc-from-ayah', 'rc-to-ayah'].forEach(id => $(id).addEventListener('input', refresh));

  $('rc-whole').addEventListener('click', () => {
    const fs = $('rc-from-surah').value;
    $('rc-to-surah').value = fs;
    $('rc-from-ayah').value = 1;
    $('rc-to-ayah').value = BY_N[fs].ayahs;
    toTouched = false;
    refresh();
  });

  $('rc-continue').addEventListener('click', () => {
    const nxt = nextAfterLast();
    if (!nxt) return;
    $('rc-from-surah').value = nxt.s;
    $('rc-to-surah').value = nxt.s;
    $('rc-from-ayah').value = nxt.a;
    $('rc-to-ayah').value = '';
    toTouched = false;
    segSet($('rc-kind'), 'new');
    refresh();
    $('rc-to-ayah').focus();
  });

  /* الآية التي تلي آخر ما سُمِّع (للتكملة) */
  function nextAfterLast() {
    const l = cur && cur.last;
    if (!l) return null;
    if (l.to_ayah < BY_N[l.to_surah].ayahs) return {s: l.to_surah, a: l.to_ayah + 1};
    if (l.to_surah < 114) return {s: l.to_surah + 1, a: 1};
    return null;
  }

  /* ───────── النافذة ───────── */
  function resetForm() {
    editingId = null;
    toTouched = false;
    $('rc-edit-banner').hidden = true;
    $('rc-save').innerHTML = '💾 حفظ التسميع';
    const s = cur && cur.last ? cur.last.to_surah : 1;
    $('rc-from-surah').value = s;
    $('rc-to-surah').value = s;
    $('rc-from-ayah').value = '';
    $('rc-to-ayah').value = '';
    $('rc-notes').value = '';
    $('rc-date').value = PAGE_DATE;
    segSet($('rc-kind'), 'new');
    segSet($('rc-grade'), '');
    refresh();
  }

  function renderSheet() {
    $('rc-title').textContent = cur.student.name;
    const c = cur.student.circle;
    $('rc-sub').textContent = (c.startsWith('حلقة') ? c : 'حلقة ' + c) + (cur.total ? ` · ${cur.total} تسميع مسجّل` : '');
    $('rc-continue').hidden = !nextAfterLast();
    renderHistory();
  }

  function renderHistory() {
    const h = cur.history;
    $('rc-total').textContent = cur.total > h.length ? `(آخر ${h.length} من ${cur.total})` : (cur.total ? `(${cur.total})` : '');
    $('rc-history').innerHTML = h.length ? h.map(x => `
      <div class="rc-h" data-id="${x.id}">
        <div class="rc-h-main"><b>${esc(x.range)}</b> <span class="rc-h-n">${x.ayahs} آية</span></div>
        <div class="rc-h-meta">${esc(x.date_display)} · ${agoText(x.days_ago)} · ${esc(x.kind_display)}${x.grade_display ? ' · ' + esc(x.grade_display) : ''}</div>
        ${x.notes ? `<div class="rc-h-notes">${esc(x.notes)}</div>` : ''}
        <div class="rc-h-actions">
          <button type="button" class="qs-btn" data-act="edit">✏️ تعديل</button>
          <button type="button" class="qs-btn" data-act="del">🗑 حذف</button>
        </div>
      </div>`).join('') : '<p class="rc-empty">لا يوجد سجل بعد.</p>';
  }

  async function openFor(id) {
    if (opening) return;
    opening = true;
    try {
      const d = await api(urlOf(U.info, id) + '?date=' + encodeURIComponent(PAGE_DATE));
      cur = d;
      renderSheet();
      resetForm();
      $('rc-overlay').hidden = false;
      document.body.classList.add('rc-lock');
      $('rc-overlay').scrollTop = 0;
    } catch (e) {
      showToast('❌ ' + e.message, 'error');
    } finally {
      opening = false;
    }
  }

  function closeSheet() {
    $('rc-overlay').hidden = true;
    document.body.classList.remove('rc-lock');
    editingId = null;
  }

  /* ───────── الصف في القائمة ───────── */
  const chip = x => `<span class="rc-chip${x.kind === 'review' ? ' review' : ''}">${esc(x.range)}${x.kind === 'review' ? ' · مراجعة' : ''}${x.grade_display ? ' · ' + esc(x.grade_display) : ''}</span>`;

  function recount() {
    const rows = document.querySelectorAll('#rc-list .rc-row');
    let heard = 0;
    rows.forEach(r => { if (r.querySelector('[data-day] .rc-chip')) heard++; });
    $('rc-heard').textContent = heard;
    $('rc-remaining').textContent = rows.length - heard;
  }

  function updateRow(d) {
    const row = $('rc-row-' + d.student.id);
    if (!row) return;
    row.querySelector('[data-last]').innerHTML = d.last
      ? `آخر تسميع: <b>${esc(d.last.range)}</b> · ${esc(d.last.date_display)} <span class="rc-ago">${agoText(d.last.days_ago)}</span>`
      : '<span class="rc-none">لم يُسمَّع بعد</span>';
    row.querySelector('[data-day]').innerHTML = (d.day || []).map(chip).join('');
    recount();
    return row;
  }

  /* ───────── حفظ / تعديل / حذف ───────── */
  async function save() {
    if (!cur) return;
    const r = readRange();
    if (!(r.fa > 0 && r.ta > 0)) { showToast('⚠️ أدخل آية البداية وآية النهاية', 'warn'); return; }
    const err = validate(r);
    if (err) { showToast('⚠️ ' + err, 'warn'); return; }

    const btn = $('rc-save');
    setBtnLoading(btn, true);
    try {
      const wasEditing = !!editingId;
      const d = await api(wasEditing ? urlOf(U.update, editingId) : urlOf(U.add, cur.student.id), {
        kind: segGet($('rc-kind')) || 'new',
        from_surah: r.fs, from_ayah: r.fa, to_surah: r.ts, to_ayah: r.ta,
        grade: segGet($('rc-grade')), notes: $('rc-notes').value.trim(),
        date: $('rc-date').value || PAGE_DATE, ctx_date: PAGE_DATE,
      });
      cur = d;
      const row = updateRow(d);
      if (wasEditing) {
        showToast('✅ تم حفظ التعديل', 'success');
        renderSheet();
        resetForm();
      } else {
        showToast(`✅ سُجّل تسميع ${d.student.name}`, 'success');
        closeSheet();
        if (row) { row.classList.add('flash'); setTimeout(() => row.classList.remove('flash'), 1600); }
      }
    } catch (e) {
      showToast('❌ ' + e.message, 'error');
    } finally {
      setBtnLoading(btn, false);
    }
  }

  function startEdit(id) {
    const x = cur.history.find(h => String(h.id) === String(id));
    if (!x) return;
    editingId = x.id;
    toTouched = true;
    segSet($('rc-kind'), x.kind);
    $('rc-from-surah').value = x.from_surah;
    $('rc-to-surah').value = x.to_surah;
    $('rc-from-ayah').value = x.from_ayah;
    $('rc-to-ayah').value = x.to_ayah;
    segSet($('rc-grade'), x.grade || '');
    $('rc-notes').value = x.notes || '';
    $('rc-date').value = x.date;
    $('rc-edit-banner').hidden = false;
    $('rc-save').innerHTML = '💾 حفظ التعديل';
    refresh();
    $('rc-overlay').scrollTo({top: 0, behavior: 'smooth'});
  }

  $('rc-history').addEventListener('click', async e => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = btn.closest('.rc-h').dataset.id;
    if (btn.dataset.act === 'edit') { startEdit(id); return; }
    if (!confirm('حذف هذا التسميع؟')) return;
    try {
      const d = await api(urlOf(U.del, id), {ctx_date: PAGE_DATE});
      cur = d;
      updateRow(d);
      renderSheet();
      if (editingId && String(editingId) === String(id)) resetForm();
      showToast('🗑 تم الحذف', 'info');
    } catch (err) {
      showToast('❌ ' + err.message, 'error');
    }
  });

  /* ───────── ربط الأحداث ───────── */
  $('rc-list').addEventListener('click', e => {
    if (e.target.closest('a')) return;                       // رابط الطالب يعمل كالمعتاد
    const row = e.target.closest('.rc-row');
    if (row) openFor(row.dataset.id);                        // الصف كله منطقة نقر كبيرة
  });
  $('rc-save').addEventListener('click', save);
  $('rc-close').addEventListener('click', closeSheet);
  $('rc-cancel-edit').addEventListener('click', resetForm);
  $('rc-overlay').addEventListener('click', e => { if (e.target === $('rc-overlay')) closeSheet(); });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !$('rc-overlay').hidden) closeSheet();
  });
  ['rc-from-ayah', 'rc-to-ayah', 'rc-notes'].forEach(id => $(id).addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); save(); }
  }));
})();
