/*
 * ربط الأساتذة بالحلقات — واجهة أفقية بسيطة:
 *   • اختيار أستاذ أساسي ثم «ربط دائم».
 *   • ربط مؤقت: أستاذ بديل ليوم واحد فقط، يرجع الأساسي تلقائياً بعد انتهاء اليوم.
 *   • إضافة أستاذ جديد بسرعة من داخل البطاقة.
 * كل الحفظ يمرّ عبر TahaSync.post (يُحفظ محلياً ويُرسل تلقائياً عند انقطاع الاتصال).
 */
(function () {
  'use strict';
  const board = document.getElementById('tl-board');
  if (!board) return;
  const URL = board.dataset.linkUrl;
  const TODAY = board.dataset.today;
  const toast = (m, t) => { if (window.showToast) window.showToast(m, t || 'success', 3500); };
  const post = (data, opts) => window.TahaSync
    ? window.TahaSync.post(URL, data, opts)
    : fetch(URL, {method: 'POST', headers: {'X-CSRFToken': getCsrf(), 'X-Requested-With': 'XMLHttpRequest'},
                  body: new URLSearchParams(data).toString()}).then(r => r.json());

  function refreshCard(card, c) {
    const main = card.querySelector('[data-main]');
    if (c.teacher) {
      main.innerHTML = `<a href="/teachers/${c.teacher_id}/profile/" class="student-link">${c.teacher}</a>`;
      card.querySelector('[data-role="teacher"]').value = c.teacher_id;
      card.querySelector('.tl-head').classList.remove('no-teacher');
    } else {
      main.innerHTML = '<span class="tl-none">بلا أستاذ</span>';
      card.querySelector('[data-role="teacher"]').value = '';
    }
    const isToday = c.substitute_date === TODAY;
    card.classList.toggle('is-temp', !!isToday);
    const badge = card.querySelector('[data-badge]');
    if (badge) {
      badge.hidden = !isToday;
      badge.textContent = isToday && c.substitute ? '⏱ بديل اليوم: ' + c.substitute : '';
    }
    card.dataset.sub = c.substitute_id || '';
    card.dataset.subDate = c.substitute_date || '';
    // حدّث خيار البديل
    const subSel = card.querySelector('[data-role="sub"]');
    if (subSel) subSel.value = c.substitute_id || '';
    if (c.substitute_date) card.querySelector('[data-role="date"]').value = c.substitute_date;
  }

  async function send(card, body, label) {
    const btns = card.querySelectorAll('button');
    btns.forEach(b => { b.disabled = true; });
    try {
      const data = await post(body, {label});
      refreshCard(card, data.circle);
      toast('✅ ' + label + (data.queued ? ' (سيُرسل عند رجوع الاتصال)' : ''), 'success');
    } catch (err) {
      toast('❌ ' + (err.message || 'تعذّر الحفظ'), 'error');
    } finally {
      btns.forEach(b => { b.disabled = false; });
    }
  }

  board.addEventListener('click', e => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const card = btn.closest('.tl-card');
    if (!card) return;
    const cid = card.dataset.circle;
    const cname = card.dataset.name;
    const tSel = card.querySelector('[data-role="teacher"]');
    const sSel = card.querySelector('[data-role="sub"]');
    const dInp = card.querySelector('[data-role="date"]');
    const act = btn.dataset.act;

    if (act === 'permanent') {
      const tid = tSel.value;
      const tname = tid ? tSel.options[tSel.selectedIndex].textContent : 'بلا أستاذ';
      send(card, {circle_id: cid, mode: 'permanent', teacher_id: tid}, `ربط «${tname}» بـ «${cname}»`);
    } else if (act === 'clear') {
      if (!confirm(`إزالة أستاذ «${cname}»؟`)) return;
      send(card, {circle_id: cid, mode: 'clear'}, `إزالة أستاذ «${cname}»`);
    } else if (act === 'temporary') {
      const tid = sSel.value;
      if (!tid) {
        if (!confirm('إلغاء الربط المؤقت لهذه الحلقة؟')) return;
        send(card, {circle_id: cid, mode: 'temporary', teacher_id: '', date: dInp.value}, `إلغاء الربط المؤقت «${cname}»`);
        return;
      }
      const tname = sSel.options[sSel.selectedIndex].textContent;
      send(card, {circle_id: cid, mode: 'temporary', teacher_id: tid, date: dInp.value},
           `ربط مؤقت: «${tname}» → «${cname}» يوم ${dInp.value}`);
    } else if (act === 'new') {
      const input = card.querySelector('[data-role="new-teacher"]');
      const name = input.value.trim();
      if (!name) { input.focus(); return; }
      // نضيف الأستاذ كأستاذ أساسي ثم نحدّث كل القوائم
      send(card, {circle_id: cid, mode: 'permanent', new_teacher_name: name}, `إضافة وربط أستاذ جديد «${name}»`)
        .then(() => {
          document.querySelectorAll('.tl-card select[data-role="teacher"], .tl-card select[data-role="sub"]').forEach(sel => {
            if (![...sel.options].some(o => o.textContent === name)) {
              const o = document.createElement('option');
              o.value = card.dataset.newId || ''; o.textContent = name;
              sel.appendChild(o);
            }
          });
          input.value = '';
        });
    }
  });

  const $find = document.getElementById('tl-find');
  $find?.addEventListener('input', () => {
    const q = $find.value.trim();
    board.querySelectorAll('.tl-card').forEach(card => {
      const hay = (card.dataset.name + ' ' + [...card.querySelectorAll('option')].map(o => o.textContent).join(' '));
      card.style.display = !q || hay.includes(q) ? '' : 'none';
    });
  });
})();
