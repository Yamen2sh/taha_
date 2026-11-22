/*
 * لوحة فرز الطلاب بالسحب والإفلات (لوحة التحكم).
 * سحب مبني على Pointer Events ليعمل بالماوس واللمس والقلم بلا مكتبات خارجية:
 *   • ماوس: اسحب من أي مكان في البطاقة.
 *   • لمس/قلم: اسحب من المقبض ⠿ فوراً، أو اضغط على البطاقة ضغطة مطوّلة ثم اسحب (حتى يبقى التمرير سلساً).
 * كل إفلات في حلقة مختلفة يُحفظ فوراً في السيرفر؛ ويمكن التراجع عن آخر النقلات.
 */
(function () {
  'use strict';

  const board = document.getElementById('dn-board');
  if (!board) return;
  const MOVE_URL = board.dataset.moveUrl;
  const $find = document.getElementById('dn-find');
  const $undo = document.getElementById('dn-undo');
  const $status = document.getElementById('dn-status');

  const HOLD_MS = 280;        // مدة الضغطة المطوّلة باللمس
  const START_PX = 4;         // حركة الماوس/المقبض قبل بدء السحب
  const CANCEL_PX = 9;        // حركة اللمس قبل انتهاء الضغطة المطوّلة = المستخدم يمرّر الصفحة
  const norm = s => (window.StudentIndex && window.StudentIndex.norm) ? window.StudentIndex.norm(s) : String(s).toLowerCase();
  const collator = new Intl.Collator('ar');
  const toast = (m, t) => { if (typeof window.showToast === 'function') window.showToast(m, t || 'info', 3500); };

  const cols = () => [...board.querySelectorAll('.dn-col')];
  const colById = id => board.querySelector('.dn-col[data-circle="' + id + '"]');
  const listOf = col => col.querySelector('[data-list]');
  const nameOf = col => col.dataset.name;
  const stdName = card => card.dataset.name;

  function recount(col) {
    const n = listOf(col).querySelectorAll('.dn-card').length;
    col.querySelector('[data-count]').textContent = n;
    col.classList.toggle('has-cards', n > 0);
  }

  function insertSorted(list, card) {
    const name = stdName(card);
    const next = [...list.querySelectorAll('.dn-card')].find(c => c !== card && collator.compare(stdName(c), name) > 0);
    if (next) list.insertBefore(card, next); else list.appendChild(card);
  }

  function setStatus(msg) {
    $status.textContent = msg || $status.dataset.default;
  }

  /* ───────── الاتصال بالسيرفر ───────── */
  async function postMove(studentId, circleId) {
    const res = await fetch(MOVE_URL, {
      method: 'POST',
      headers: {'X-CSRFToken': getCsrf(), 'X-Requested-With': 'XMLHttpRequest'},
      body: new URLSearchParams({student_id: studentId, circle_id: circleId}),
    });
    const data = await res.json().catch(() => ({ok: false, error: 'استجابة غير صالحة'}));
    if (!res.ok || data.ok === false) throw new Error(data.error || 'تعذّر حفظ النقل');
    return data;
  }

  /* ───────── التراجع ───────── */
  const undoStack = [];
  function syncUndo() {
    $undo.disabled = undoStack.length === 0;
    const last = undoStack[undoStack.length - 1];
    $undo.title = last ? `التراجع: ${last.name} ← ${last.fromName}` : '';
  }

  async function undo() {
    const m = undoStack.pop();
    syncUndo();
    if (!m) return;
    const card = board.querySelector('.dn-card[data-student="' + m.id + '"]');
    const to = colById(m.fromCircle);
    if (!card || !to) return;
    const ok = await doMove(card, card.closest('.dn-col'), to, true);
    if (!ok) { undoStack.push(m); syncUndo(); }
  }
  $undo.addEventListener('click', undo);
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z' &&
        !/^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement || {}).tagName || '')) {
      e.preventDefault();
      undo();
    }
  });

  /* ───────── تنفيذ النقل (تفاؤلي: نحرّك البطاقة ثم نحفظ، ونُرجعها عند الفشل) ───────── */
  async function doMove(card, fromCol, toCol, isUndo) {
    const id = card.dataset.student;
    insertSorted(listOf(toCol), card);
    recount(fromCol); recount(toCol);
    card.classList.add('is-saving');
    try {
      await postMove(id, toCol.dataset.circle);
      if (!isUndo) {
        undoStack.push({id, name: stdName(card), fromCircle: fromCol.dataset.circle, fromName: nameOf(fromCol)});
        if (undoStack.length > 30) undoStack.shift();
        syncUndo();
      }
      card.classList.add('flash');
      setTimeout(() => card.classList.remove('flash'), 1500);
      const msg = `${isUndo ? '↩ أُعيد' : '✅ نُقل'} «${stdName(card)}» إلى ${nameOf(toCol)}`;
      setStatus(msg);
      toast(msg, 'success');
      return true;
    } catch (e) {
      insertSorted(listOf(fromCol), card);                     // فشل الحفظ → أعد البطاقة لمكانها
      recount(fromCol); recount(toCol);
      toast('❌ ' + e.message, 'error');
      setStatus('❌ ' + e.message);
      return false;
    } finally {
      card.classList.remove('is-saving');
    }
  }

  /* ───────── السحب ───────── */
  let drag = null;

  const colAt = (x, y) => {
    const el = document.elementFromPoint(x, y);
    return el ? el.closest('.dn-col') : null;
  };

  function place(d) {
    d.ghost.style.transform = `translate(${d.x - d.ox}px, ${d.y - d.oy}px) rotate(1.5deg)`;
  }

  function hover(d) {
    const col = colAt(d.x, d.y);
    if (col === d.over) return;
    if (d.over) d.over.classList.remove('is-over');
    d.over = col;
    if (col && col !== d.from) col.classList.add('is-over');
  }

  function tick() {                                            // تمرير تلقائي للصفحة قرب الحافة
    const d = drag;
    if (!d || !d.active) return;
    const edge = 90, vh = window.innerHeight;
    let dy = 0;
    if (d.y < edge) dy = -Math.ceil((edge - d.y) / 5);
    else if (d.y > vh - edge) dy = Math.ceil((d.y - (vh - edge)) / 5);
    if (dy) { window.scrollBy(0, dy); hover(d); }
    d.raf = requestAnimationFrame(tick);
  }

  function begin() {
    const d = drag;
    if (!d || d.active) return;
    const r = d.card.getBoundingClientRect();
    d.active = true;
    d.ox = d.sx - r.left;
    d.oy = d.sy - r.top;
    const g = d.card.cloneNode(true);
    g.classList.add('dn-ghost');
    g.classList.remove('is-hit', 'flash');
    g.style.width = r.width + 'px';
    document.body.appendChild(g);
    d.ghost = g;
    d.card.classList.add('is-dragging');
    document.body.classList.add('dn-dragging');
    try { d.card.setPointerCapture(d.pid); } catch (e) { /* غير مدعوم */ }
    place(d);
    hover(d);
    tick();
    if (d.type === 'touch' && navigator.vibrate) navigator.vibrate(12);
  }

  function finish(drop) {
    const d = drag;
    drag = null;
    if (!d) return;
    if (d.timer) clearTimeout(d.timer);
    if (!d.active) return;
    cancelAnimationFrame(d.raf);
    d.ghost.remove();
    d.card.classList.remove('is-dragging');
    document.body.classList.remove('dn-dragging');
    try { d.card.releasePointerCapture(d.pid); } catch (e) { /* تجاهل */ }
    board.querySelectorAll('.is-over').forEach(c => c.classList.remove('is-over'));
    const target = drop ? colAt(d.x, d.y) : null;
    if (target && target !== d.from) doMove(d.card, d.from, target, false);
  }

  board.addEventListener('pointerdown', e => {
    if (drag) return;
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    const card = e.target.closest('.dn-card');
    if (!card || card.classList.contains('is-saving')) return;
    const onGrip = !!e.target.closest('.dn-grip');
    drag = {
      card, from: card.closest('.dn-col'), pid: e.pointerId, type: e.pointerType,
      sx: e.clientX, sy: e.clientY, x: e.clientX, y: e.clientY,
      ox: 0, oy: 0, active: false, timer: null, ghost: null, over: null, raf: 0,
    };
    if (e.pointerType !== 'mouse' && !onGrip) {
      const d = drag;
      d.timer = setTimeout(() => { d.timer = null; if (drag === d) begin(); }, HOLD_MS);
    }
  });

  document.addEventListener('pointermove', e => {
    const d = drag;
    if (!d || e.pointerId !== d.pid) return;
    d.x = e.clientX; d.y = e.clientY;
    if (!d.active) {
      const moved = Math.hypot(d.x - d.sx, d.y - d.sy);
      if (d.timer) {                                          // لمس: حرّك إصبعه قبل الضغطة المطوّلة = تمرير
        if (moved > CANCEL_PX) { clearTimeout(d.timer); drag = null; }
        return;
      }
      if (moved < START_PX) return;
      begin();
    }
    e.preventDefault();
    place(d);
    hover(d);
  }, {passive: false});

  document.addEventListener('pointerup', e => { if (drag && e.pointerId === drag.pid) finish(true); });
  document.addEventListener('pointercancel', e => { if (drag && e.pointerId === drag.pid) finish(false); });
  document.addEventListener('touchmove', e => { if (drag && drag.active) e.preventDefault(); }, {passive: false});
  board.addEventListener('contextmenu', e => { if (e.target.closest('.dn-card')) e.preventDefault(); });
  board.addEventListener('dragstart', e => e.preventDefault());
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && drag && drag.active) finish(false); });

  /* ───────── بحث عن طالب ───────── */
  $find.addEventListener('input', () => {
    const words = norm($find.value.trim()).split(' ').filter(Boolean);
    let hits = 0, first = null;
    board.querySelectorAll('.dn-card').forEach(c => {
      const n = norm(stdName(c));
      const ok = !words.length || words.every(w => n.includes(w));
      c.classList.toggle('is-hidden', !ok);
      c.classList.toggle('is-hit', !!words.length && ok);
      if (words.length && ok) { hits++; if (!first) first = c; }
    });
    cols().forEach(col => col.classList.toggle('is-dim', !!words.length && !col.querySelector('.dn-card.is-hit')));
    setStatus(words.length ? (hits ? `${hits} نتيجة` : 'لا توجد نتائج') : '');
    if (first) first.scrollIntoView({block: 'center', behavior: 'smooth'});
  });
})();
