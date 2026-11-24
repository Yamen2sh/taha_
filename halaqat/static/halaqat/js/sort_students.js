/*
 * لوحة فرز الطلاب بالسحب والإفلات (لوحة التحكم).
 * سحب مبني على Pointer Events ليعمل بالماوس واللمس والقلم بلا مكتبات خارجية:
 *   • ماوس: اسحب من أي مكان في البطاقة.
 *   • لمس/قلم: اسحب من المقبض ⠿ فوراً، أو اضغط على البطاقة ضغطة مطوّلة ثم اسحب (حتى يبقى التمرير سلساً).
 *
 * جديد:
 *   • «الحاوية الفارغة» (data-circle="park"): تُخزَّن فيها بطاقات الطلاب مؤقتاً (parked) فتُخفى من الحضور
 *     والتسميع، والكوادر الذين بلا حلقات تُعرض فيها بلون مختلف. تُنبّه قبل مغادرة الصفحة إن لم تكن فارغة.
 *   • إضافة طالب/أستاذ/حلقة من نفس الصفحة (POST صغير) ثم تُدرج البطاقة فوراً.
 *   • الحفظ يمرّ عبر TahaSync.post: يُحفظ محلياً ويُرسل تلقائياً إن انقطع الاتصال.
 */
(function () {
  'use strict';

  const board = document.getElementById('dn-board');
  if (!board) return;
  const MOVE_URL = board.dataset.moveUrl;
  const ADD_URL = board.dataset.addUrl;
  const $find = document.getElementById('dn-find');
  const $undo = document.getElementById('dn-undo');
  const $status = document.getElementById('dn-status');
  const $parkWarn = document.getElementById('dn-park-warn');

  const HOLD_MS = 280;
  const START_PX = 4;
  const CANCEL_PX = 9;
  const norm = s => (window.StudentIndex && window.StudentIndex.norm) ? window.StudentIndex.norm(s) : String(s).toLowerCase();
  const collator = new Intl.Collator('ar');
  const toast = (m, t) => { if (typeof window.showToast === 'function') window.showToast(m, t || 'info', 3500); };
  const post = (url, data, opts) => window.TahaSync
    ? window.TahaSync.post(url, data, opts)
    : fetch(url, {method: 'POST', headers: {'X-CSRFToken': getCsrf(), 'X-Requested-With': 'XMLHttpRequest'},
                  body: new URLSearchParams(data).toString()}).then(r => r.json());

  const cols = () => [...board.querySelectorAll('.dn-col')];
  const colById = id => board.querySelector('.dn-col[data-circle="' + id + '"]');
  const listOf = col => col.querySelector('[data-list]');
  const nameOf = col => col.dataset.name;
  const stdName = card => card.dataset.name;
  const isPark = col => col.dataset.circle === 'park';
  let parked = parseInt(board.dataset.parkedCount, 10) || 0;

  function recount(col) {
    const n = listOf(col).querySelectorAll('.dn-card').length;
    col.querySelector('[data-count]').textContent = n;
    col.classList.toggle('has-cards', n > 0);
    if (isPark(col)) {
      parked = n;
      board.dataset.parkedCount = n;
      if ($parkWarn) {
        $parkWarn.classList.toggle('ok', n === 0);
        $parkWarn.textContent = n
          ? '⚠️ الحاوية غير فارغة — وزّع الطلاب على الحلقات قبل مغادرة الصفحة'
          : '✅ الحاوية فارغة';
      }
      document.title = n ? '⚠️ (' + n + ') فرز الطلاب' : 'فرز الطلاب — مسجد طه';
    }
  }

  function insertSorted(list, card) {
    const name = stdName(card);
    const next = [...list.querySelectorAll('.dn-card')].find(c => c !== card && collator.compare(stdName(c), name) > 0);
    if (next) list.insertBefore(card, next); else list.appendChild(card);
  }

  function setStatus(msg) {
    $status.textContent = msg || $status.dataset.default;
  }

  /* ───────── تنبيه قبل مغادرة الصفحة إن كانت الحاوية غير فارغة ───────── */
  let leaving = false;
  window.addEventListener('beforeunload', e => {
    if (parked > 0 && !leaving) {
      e.preventDefault();
      e.returnValue = 'الحاوية الفارغة ليست فارغة — وزّع الطلاب على الحلقات أولاً.';
      return e.returnValue;
    }
  });
  // التبويبات الداخلية/التنقّل عبر روابط JS: نسأل تأكيداً بدل تحذير المتصفح للروابط الداخلية
  document.addEventListener('click', e => {
    const a = e.target.closest('a[href]');
    if (!a || parked === 0) return;
    if (a.target === '_blank' || a.hasAttribute('download')) return;
    if (!confirm('الحاوية الفارغة ليست فارغة (' + parked + ' طالباً).\nهل تريد المغادرة دون توزيعهم؟')) {
      e.preventDefault();
    } else { leaving = true; }
  }, true);

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

  /* ───────── تنفيذ النقل (تفاؤلي) ───────── */
  async function doMove(card, fromCol, toCol, isUndo) {
    const id = card.dataset.student;
    const fromIsPark = isPark(fromCol), toIsPark = isPark(toCol);
    insertSorted(listOf(toCol), card);
    recount(fromCol); recount(toCol);
    card.classList.toggle('dn-card-park', toIsPark);
    card.classList.add('is-saving');
    try {
      const data = await post(MOVE_URL, {student_id: id, circle_id: toIsPark ? 'park' : toCol.dataset.circle},
                              {label: 'نقل طالب', key: 'move:' + id});
      if (!isUndo) {
        undoStack.push({id, name: stdName(card), fromCircle: fromCol.dataset.circle, fromName: nameOf(fromCol)});
        if (undoStack.length > 30) undoStack.shift();
        syncUndo();
      }
      card.classList.add('flash');
      setTimeout(() => card.classList.remove('flash'), 1500);
      const verb = toIsPark ? 'وُضع في الحاوية الفارغة' : `${isUndo ? 'أُعيد' : 'نُقل'} إلى ${nameOf(toCol)}`;
      const msg = `✅ «${stdName(card)}» ${verb}`;
      setStatus(data.queued ? '📴 ' + msg + ' — سيُرسل عند رجوع الاتصال' : msg);
      toast(msg, 'success');
      // تحديث الفهرس المحلي فوراً
      if (window.StudentIndex) {
        const c = window.StudentIndex.get(id);
        window.StudentIndex.putLocal(id, {circle_id: toIsPark ? null : toCol.dataset.circle});
        if (c) { /* لا شيء إضافي */ }
      }
      return true;
    } catch (e) {
      insertSorted(listOf(fromCol), card);
      recount(fromCol); recount(toCol);
      card.classList.toggle('dn-card-park', fromIsPark);
      toast('❌ ' + e.message, 'error');
      setStatus('❌ ' + e.message);
      return false;
    } finally {
      card.classList.remove('is-saving');
    }
  }

  /* ───────── السحب (بطاقات الطلاب والأساتذة) ───────── */
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

  function tick() {
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
    if (!target) return;
    if (d.kind === 'teacher') {
      if (target === d.from) return;
      linkTeacher(d.card, target);
    } else if (target !== d.from) {
      doMove(d.card, d.from, target, false);
    }
  }

  /* ───────── ربط أستاذ بحلقة بالسحب (أساسي، أو مؤقت ليوم واحد بالسحب إلى حاوية أخرى) ───────── */
  async function linkTeacher(tcard, toCol) {
    const tid = tcard.dataset.teacher, tname = tcard.dataset.name;
    if (isPark(toCol)) { toast('الحاوية الفارغة للطلاب فقط — اسحب الأستاذ إلى حلقة', 'warn'); return; }
    const cid = toCol.dataset.circle;
    const fromFree = !!tcard.closest('.dn-park-teachers') || tcard.classList.contains('free');
    // أستاذ مسحوب من حلقة أخرى: المتصفح يسأل — موافق = ربط دائم، إلغاء = بديل لليوم فقط
    const temporary = !fromFree && tcard.closest('.dn-col') !== toCol
      ? !confirm(`ربط «${tname}» بـ ${nameOf(toCol)}؟\n\n«موافق» = ربط دائم (يبقى أستاذاً للحلقة)\n«إلغاء» = أستاذ بديل لهذا اليوم فقط`)
      : false;
    const body = {kind: 'link', circle_id: cid, teacher_id: tid};
    if (temporary) { body.temporary = '1'; body.date = new Date().toISOString().slice(0, 10); }
    try {
      const data = await post(ADD_URL, body, {label: 'ربط أستاذ'});
      updateTeacherHeader(toCol, tname);
      // انقل بطاقة الأستاذ بصرياً إلى الحلقة
      const head = toCol.querySelector('.dn-head');
      let card = toCol.querySelector('.dn-teacher-card');
      if (!card) {
        card = document.createElement('div');
        card.className = 'dn-teacher-card';
        card.innerHTML = '<span class="dn-tgrip" aria-hidden="true">⠿</span><span class="dn-tname"></span><span class="dn-trole">أستاذ الحلقة</span>';
        head.insertAdjacentElement('afterend', card);
        card.dataset.teacher = tid; card.dataset.name = tname;
      }
      card.dataset.teacher = tid; card.dataset.name = tname;
      card.querySelector('.dn-tname').textContent = '👨‍🏫 ' + tname;
      card.classList.remove('free', 'temp');
      if (temporary) { card.classList.add('temp'); card.querySelector('.dn-trole').textContent = 'بديل اليوم فقط'; }
      toast(`✅ رُبط «${tname}» بـ ${nameOf(toCol)}${temporary ? ' (مؤقت ليوم واحد)' : ''}`, 'success');
      setStatus(`🔗 ${tname} ← ${nameOf(toCol)}`);
    } catch (e) { toast('❌ ' + e.message, 'error'); }
  }

  function updateTeacherHeader(col, name) {
    let el = col.querySelector('.dn-teacher');
    if (el) el.textContent = name;
  }

  let dragKind = 'student';
  board.addEventListener('pointerdown', e => {
    if (drag) return;
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    const tcard = e.target.closest('.dn-teacher-card');
    const card = tcard || e.target.closest('.dn-card');
    if (!card || card.classList.contains('is-saving')) return;
    const onGrip = !!e.target.closest('.dn-grip, .dn-tgrip');
    drag = {
      card, kind: tcard ? 'teacher' : 'student',
      from: card.closest('.dn-col'), pid: e.pointerId, type: e.pointerType,
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
      if (d.timer) {
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
  board.addEventListener('contextmenu', e => { if (e.target.closest('.dn-card, .dn-teacher-card')) e.preventDefault(); });
  board.addEventListener('dragstart', e => e.preventDefault());
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && drag && drag.active) finish(false); });

  /* ───────── إضافة سريعة (طالب / أستاذ / حلقة) ───────── */
  const $addToggle = document.getElementById('dn-add-toggle');
  const $addbar = document.getElementById('dn-addbar');
  $addToggle.addEventListener('click', () => { $addbar.hidden = !$addbar.hidden; });

  $addbar.addEventListener('click', async e => {
    const btn = e.target.closest('.dn-addbtn');
    if (!btn) return;
    const form = btn.closest('.dn-addform');
    const kind = form.dataset.kind;
    const get = n => (form.querySelector('[name="' + n + '"]') || {}).value || '';
    const name = get('name').trim();
    if (!name) { form.querySelector('[name="name"]').focus(); return; }
    const body = {kind, name};
    if (kind === 'student') { body.birth_date = get('birth_date'); body.circle_id = get('circle_id'); }
    if (kind === 'teacher') body.phone = get('phone');
    if (kind === 'circle') body.teacher_id = get('teacher_id');
    btn.disabled = true;
    try {
      const data = await post(ADD_URL, body, {label: 'إضافة ' + name});
      if (kind === 'student') addStudentCard(data.student, body.circle_id);
      if (kind === 'teacher') addTeacherCard(data.teacher);
      if (kind === 'circle') addCircleBoard(data.circle);
      form.querySelector('[name="name"]').value = '';
      if (kind === 'student') form.querySelector('[name="birth_date"]').value = '';
      toast('✅ أُضيف «' + name + '»', 'success');
    } catch (err) {
      toast('❌ ' + (err.message || 'تعذّرت الإضافة'), 'error');
    } finally {
      btn.disabled = false;
    }
  });

  /* ── إضافة سريعة من الحاوية الفارغة (طالب/أستاذ) بلا فتح شريط الإضافة ── */
  document.addEventListener('click', async e => {
    const stBtn = e.target.closest('[data-add-student-circle]');
    if (stBtn) {
      const circleId = stBtn.dataset.addStudentCircle;
      const name = (prompt('اسم الطالب الجديد:') || '').trim();
      if (!name) return;
      stBtn.disabled = true;
      try {
        const data = await post(ADD_URL, {kind: 'student', name, circle_id: circleId}, {label: 'إضافة ' + name});
        addStudentCard(data.student, circleId);
        toast('✅ أُضيف «' + name + '»', 'success');
      } catch (err) { toast('❌ ' + (err.message || 'تعذّرت الإضافة'), 'error'); }
      finally { stBtn.disabled = false; }
      return;
    }
    const tBtn = e.target.closest('[data-add-teacher]');
    if (tBtn) {
      const name = (prompt('اسم الأستاذ/الكادر الجديد:') || '').trim();
      if (!name) return;
      tBtn.disabled = true;
      try {
        const data = await post(ADD_URL, {kind: 'teacher', name}, {label: 'إضافة ' + name});
        addTeacherCard(data.teacher);
        toast('✅ أُضيف «' + name + '»', 'success');
      } catch (err) { toast('❌ ' + (err.message || 'تعذّرت الإضافة'), 'error'); }
      finally { tBtn.disabled = false; }
    }
  });

  function studentCardEl(s) {
    const el = document.createElement('div');
    el.className = 'dn-card' + (s.parked ? ' dn-card-park' : '');
    el.dataset.student = s.id;
    el.dataset.name = s.name;
    el.innerHTML = '<span class="dn-grip" aria-hidden="true">⠿</span><span class="dn-name"></span>';
    el.querySelector('.dn-name').textContent = s.name;
    if (s.last_page) {
      const t = document.createElement('span');
      t.className = 'mini-tag page'; t.textContent = 'ص ' + s.last_page; t.title = 'آخر صفحة مسمّعة';
      el.appendChild(t);
    }
    if (s.birth_year) {
      const t = document.createElement('span');
      t.className = 'mini-tag birth'; t.textContent = s.birth_year; t.title = 'سنة الميلاد';
      el.appendChild(t);
    }
    return el;
  }

  function addStudentCard(s, circleId) {
    const col = colById(circleId === 'park' ? 'park' : circleId);
    if (!col) return;
    const card = studentCardEl(s);
    insertSorted(listOf(col), card);
    recount(col);
    if (s.last_page) { /* وسم جاهز */ }
  }

  function addTeacherCard(t) {
    const park = colById('park');
    const box = park.querySelector('[data-park-teachers]');
    const el = document.createElement('div');
    el.className = 'dn-teacher-card free';
    el.dataset.teacher = t.id;
    el.dataset.name = t.name;
    el.innerHTML = '<span class="dn-tgrip" aria-hidden="true">⠿</span><span class="dn-tname"></span><span class="dn-trole">بلا حلقة</span>';
    el.querySelector('.dn-tname').textContent = '👨‍🏫 ' + t.name;
    box.querySelector('.dn-tempty')?.setAttribute('hidden', '');
    box.appendChild(el);
    // أضِفه إلى قوائم اختيار الأستاذ في نماذج الإضافة
    document.querySelectorAll('.dn-addform[data-kind="circle"] select').forEach(sel => {
      const o = document.createElement('option');
      o.value = t.id; o.textContent = t.name;
      sel.appendChild(o);
    });
  }

  function addCircleBoard(c) {
    const park = colById('park');
    const sec = document.createElement('section');
    sec.className = 'dn-col';
    sec.dataset.circle = c.id;
    sec.dataset.name = c.name;
    sec.innerHTML = `
      <header class="dn-head">
        <div><div class="dn-title"></div><div class="dn-teacher"></div></div>
        <span class="dn-count" data-count>0</span>
      </header>
      ${c.teacher ? `<div class="dn-teacher-card" data-teacher="${c.teacher_id}" data-name="${c.teacher}">
        <span class="dn-tgrip" aria-hidden="true">⠿</span>
        <span class="dn-tname"></span><span class="dn-trole">أستاذ الحلقة</span></div>` : ''}
      <div class="dn-list" data-list><div class="dn-empty">اسحب طلاباً إلى هنا</div></div>`;
    sec.querySelector('.dn-title').textContent = c.name;
    sec.querySelector('.dn-teacher').textContent = c.teacher || 'بلا أستاذ';
    if (c.teacher) sec.querySelector('.dn-tname').textContent = '👨‍🏫 ' + c.teacher;
    park.parentNode.insertBefore(sec, park);
    // أضِف الحلقة إلى قائمة اختيار الحلقة في نموذج إضافة طالب
    const sel = document.querySelector('.dn-addform[data-kind="student"] select');
    if (sel) {
      const o = document.createElement('option');
      o.value = c.id; o.textContent = c.name;
      sel.appendChild(o);
    }
    $status.dataset.default = $status.dataset.default.replace(/(\d+) حلقة/, m => {
      const n = parseInt(m, 10) + 1;
      return n + ' حلقة';
    });
  }

  /* ───────── بحث (طلاب وأساتذة) ───────── */
  $find.addEventListener('input', () => {
    const words = norm($find.value.trim()).split(' ').filter(Boolean);
    let hits = 0, first = null;
    board.querySelectorAll('.dn-card, .dn-teacher-card').forEach(c => {
      const n = norm(stdName(c));
      const ok = !words.length || words.every(w => n.includes(w));
      c.classList.toggle('is-hidden', !ok);
      c.classList.toggle('is-hit', !!words.length && ok);
      if (words.length && ok) { hits++; if (!first) first = c; }
    });
    cols().forEach(col => col.classList.toggle('is-dim', !!words.length && !col.querySelector('.is-hit')));
    setStatus(words.length ? (hits ? `${hits} نتيجة` : 'لا توجد نتائج') : '');
    if (first) first.scrollIntoView({block: 'center', behavior: 'smooth'});
  });

  /* مؤشرات أولية */
  cols().forEach(recount);
})();
