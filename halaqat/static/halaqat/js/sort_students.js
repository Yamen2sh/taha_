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
  const TCH_MOVE_URL = board.dataset.teacherMoveUrl;
  const DELETE_URL = board.dataset.deleteUrl;
  const CIRCLE_INFO_URL = board.dataset.circleInfoUrl;
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

  // «حاوية» = أي عمود قابل للإفلات: حلقة (.dn-col) أو الحاوية الفارغة (.dn-park)
  const COL_SEL = '.dn-col, .dn-park';
  const cols = () => [...board.querySelectorAll(COL_SEL)];
  const colById = id => board.querySelector('[data-circle="' + id + '"].dn-col, [data-circle="' + id + '"].dn-park');
  const listOf = col => col.querySelector('[data-list]');
  const nameOf = col => col.dataset.name;
  const stdName = card => card.dataset.name;
  const isPark = col => col.dataset.circle === 'park';
  const isTeacherCard = el => !!el && (el.classList.contains('dn-teacher-card') || el.dataset.teacher);
  const isStudentCard = el => !!el && (el.classList.contains('dn-card') || el.dataset.student);
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
    // حذف مؤكَّد عند مغادرة الصفحة (كما طُلب): نستخدم sendBeacon لضمان الإرسال
    flushBasketOnLeave();
    if (parked > 0 && !leaving) {
      e.preventDefault();
      e.returnValue = 'الحاوية الفارغة ليست فارغة — وزّع الطلاب على الحلقات أولاً.';
      return e.returnValue;
    }
  });
  // التبويبات الداخلية/التنقّل عبر روابط JS: نسأل تأكيداً بدل تحذير المتصفح للروابط الداخلية
  document.addEventListener('click', e => {
    const a = e.target.closest('a[href]');
    if (!a) return;
    if (basket.size > 0) {
      // مغادرة الصفحة = تأكيد الحذف (بلا سؤال إضافي)، لكن لا نُغادر قبل الإرسال
      e.preventDefault();
      flushBasketOnLeave();
      leaving = true;
      window.location.href = a.href;
      return;
    }
    if (parked === 0) return;
    if (a.target === '_blank' || a.hasAttribute('download')) return;
    if (!confirm('الحاوية الفارغة ليست فارغة (' + parked + ' طالباً).\nهل تريد المغادرة دون توزيعهم؟')) {
      e.preventDefault();
    } else { leaving = true; }
  }, true);

  /* عند مغادرة الصفحة: يُثبَّت حذف ما في السلة بلا سؤال إضافي.
     sendBeacon يرسل حتى لو أُغلقت الصفحة، والطلبات تُكرَّر آمنة (الحذف بالمُعرِّف). */
  function flushBasketOnLeave() {
    if (basket.size === 0) return;
    const groups = {};
    basketList().forEach(i => { (groups[i.kind] = groups[i.kind] || []).push(i.id); });
    const token = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || getCsrf();
    if (navigator.sendBeacon) {
      Object.keys(groups).forEach(kind => {
        const fd = new FormData();
        fd.append('kind', kind);
        fd.append('ids', groups[kind].join(','));
        fd.append('csrfmiddlewaretoken', token);
        navigator.sendBeacon(DELETE_URL, fd);
      });
      basket.clear();
      return;
    }
    Object.keys(groups).forEach(kind => {
      fetch(DELETE_URL, {
        method: 'POST', keepalive: true,
        headers: {'X-CSRFToken': token, 'X-Requested-With': 'XMLHttpRequest'},
        body: new URLSearchParams({kind, ids: groups[kind].join(',')}).toString(),
      });
    });
    basket.clear();
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
    const ok = await doMove(card, card.closest(COL_SEL), to, true);
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
      // أظهر البطاقة في مكانها الجديد (الحاوية قد تحتاج تمريراً داخلياً)
      try { card.scrollIntoView({block: 'nearest'}); } catch (e) { /* غير مدعوم */ }
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

  /* ═════ تحديد العمود الهدف ═════
     لا نعتمد على elementFromPoint وحده (يخيب عند حدود العمود وشبح السحب)،
     بل نجمع ثلاثة مصادر ونأخذ أولها:
       1) pointerenter على العمود أثناء السحب (pointer-events:none على الشبح يسمح بذلك).
       2) elementFromPoint كخطة ثانية.
       3) حدود المستطيلات كخطة أخيرة.
  */
  function colFromPoint(x, y) {
    let el = null;
    try { el = document.elementFromPoint(x, y); } catch (e) { el = null; }
    if (el) {
      const c = el.closest(COL_SEL);
      if (c) return c;
    }
    return cols().find(c => {
      const r = c.getBoundingClientRect();
      return x >= r.left && x <= r.right && y >= r.top && y <= r.bottom;
    }) || null;
  }

  /* تحريك شبح السحب ليتبع المؤشر */
  function place(d) {
    if (!d || !d.ghost) return;
    d.ghost.style.transform =
      `translate(${Math.round(d.x - d.ox)}px, ${Math.round(d.y - d.oy)}px) rotate(1.5deg)`;
  }

  function hover(d) {
    // الأولوية للعمود الذي دخل المؤشر حدوده فعلاً (أدق من النقطة)
    const col = d.enterOver || colFromPoint(d.x, d.y);
    if (col === d.over) return;
    if (d.over) d.over.classList.remove('is-over');
    d.over = col;
    if (col) col.classList.add('is-over');
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
    document.querySelectorAll('.dn-ghost').forEach(g0 => g0.remove());   // شبح عالق من محاولة سابقة
    const g = d.card.cloneNode(true);
    g.classList.add('dn-ghost');
    g.classList.remove('is-hit', 'flash');
    g.style.width = r.width + 'px';
    document.body.appendChild(g);
    d.ghost = g;
    d.enterOver = null;
    dragStartedAt = Date.now();
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
    const target = drop ? (d.enterOver || colFromPoint(d.x, d.y)) : null;
    if (!target) {
      if (drop) toast('أفلتت البطاقة خارج أي حلقة — لم يتغيّر شيء', 'warn');
      return;
    }
    dragStartedAt = Date.now();
    if (d.kind === 'teacher') {
      if (target === d.from) return;
      lastDragAt = Date.now();
      moveTeacher(d.card, target);
    } else if (target !== d.from) {
      lastDragAt = Date.now();
      doMove(d.card, d.from, target, false);
    }
  }

  /* ───────── نقل الأستاذ بين الحلقات (تعديل، لا إضافة) ─────────
     هذه الصفحة لا تُضيف أستاذاً أساسياً ولا بديلاً: الإضافة من «ربط الأساتذة» فقط.
     السحب هنا = نقل: إلى حلقة أخرى (يصبح أستاذها) أو إلى الحاوية الفارغة (بلا حلقة). */
  async function moveTeacher(tcard, toCol) {
    const tid = tcard.dataset.teacher, tname = tcard.dataset.name;
    const fromCol = tcard.closest(COL_SEL);
    const toPark = isPark(toCol);
    if (fromCol === toCol) return;
    if (toPark) {
      const ok = confirm(`إخراج «${tname}» من حلقته (${nameOf(fromCol)})؟\n\nسيصبح بلا حلقة ويظهر في «الحاوية الفارغة».` +
                         `\nلا يُحذف من النظام.`);
      if (!ok) return;
    }
    tcard.classList.add('is-saving');
    try {
      const data = await post(TCH_MOVE_URL,
        {teacher_id: tid, circle_id: toPark ? 'park' : toCol.dataset.circle},
        {label: 'نقل أستاذ', key: 'tmv:' + tid});
      // أكّد بصرياً: انقل البطاقة إلى مكانها الجديد
      const parkBox = document.querySelector('[data-park-teachers]');
      if (toPark) {
        tcard.classList.add('free');
        tcard.querySelector('.dn-trole').textContent = 'بلا حلقة';
        parkBox.appendChild(tcard);
        parkBox.querySelector('.dn-tempty')?.setAttribute('hidden', '');
        // الحلقة القديمة يبقى رأسها بلا أستاذ
        const oldTitle = fromCol.querySelector('.dn-teacher');
        if (oldTitle) oldTitle.textContent = 'بلا أستاذ';
      } else {
        tcard.classList.remove('free', 'temp');
        tcard.querySelector('.dn-trole').textContent = 'أستاذ الحلقة';
        const head = toCol.querySelector('.dn-head');
        let card = toCol.querySelector('.dn-teacher-card');
        if (!card) {
          card = tcard;
          head.insertAdjacentElement('afterend', card);
        } else {
          // الحلقة كان لها أستاذ: بطاقته صارت «بلا حلقة» في الحاوية
          const displaced = card;
          card.replaceWith(tcard);
          displaced.classList.add('free');
          displaced.querySelector('.dn-trole').textContent = 'بلا حلقة';
          parkBox.appendChild(displaced);
          parkBox.querySelector('.dn-tempty')?.setAttribute('hidden', '');
        }
        updateTeacherHeader(toCol, tname);
        // إزالة بطاقة الأستاذ القديم من الحلقات الأخرى التي كان أستاذها لها
        (data.cleared || []).forEach(cid => {
          const c = colById(cid);
          if (!c) return;
          const t = c.querySelector('.dn-teacher');
          if (t) t.textContent = 'بلا أستاذ';
        });
        if (data.from && data.from !== Number(toCol.dataset.circle)) {
          const oldCol = colById(data.from);
          if (oldCol) { const t = oldCol.querySelector('.dn-teacher'); if (t) t.textContent = 'بلا أستاذ'; }
        }
      }
      tcard.dataset.where = toPark ? 'park' : toCol.dataset.circle;
      const msg = toPark ? `↩ «${tname}» صار بلا حلقة` : `🔗 «${tname}» ← ${nameOf(toCol)}`;
      toast('✅ ' + msg, 'success');
      setStatus(msg);
    } catch (e) {
      toast('❌ ' + e.message, 'error');
    } finally {
      tcard.classList.remove('is-saving');
    }
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
      from: card.closest(COL_SEL), pid: e.pointerId, type: e.pointerType,
      sx: e.clientX, sy: e.clientY, x: e.clientX, y: e.clientY,
      ox: 0, oy: 0, active: false, timer: null, ghost: null, over: null, enterOver: null, raf: 0,
    };
    if (e.pointerType !== 'mouse' && !onGrip) {
      const d = drag;
      d.timer = setTimeout(() => { d.timer = null; if (drag === d) begin(); }, HOLD_MS);
    }
  });

  /* العمود الذي يدخله المؤشر أثناء السحب — أدق وسيلة لتحديد الهدف
     (شبح السحب عليه pointer-events:none فلا يحجب الأحداث عن الأعمدة). */
  board.addEventListener('pointerover', e => {
    if (!drag || !drag.active) return;
    const col = e.target.closest(COL_SEL);
    if (col && col !== drag.enterOver) {
      drag.enterOver = col;
      hover(drag);
    }
  });
  board.addEventListener('pointerleave', e => {
    if (!drag || !drag.active) return;
    const col = e.target.closest(COL_SEL);
    if (col && drag.enterOver === col && !col.contains(e.relatedTarget)) {
      drag.enterOver = null;
      hover(drag);
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
  document.addEventListener('pointercancel', e => {
    if (!drag || e.pointerId !== drag.pid) return;
    const wasActive = drag.active;
    finish(false);
    if (wasActive) toast('↩ أُلغي السحب — اسحب من المقبض ⠿ أو اضغط مطوّلاً', 'warn');
  });
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
    const kind = form.dataset.formKind || form.dataset.kind;
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
  /* إضافة مباشرة داخل الحاوية: نُظهر حقلاً صغيراً مكان الزر بدل نافذة prompt
     (بعض المتصفحات/الإضافات تحجب prompt، وكانت الإضافة تبدو معطّلة). */
  function inlineAdd(btn, {kind, label, circleId}) {
    if (btn.disabled || btn.closest('.dn-inline-add')) return;
    const box = document.createElement('div');
    box.className = 'dn-inline-add';
    const inp = document.createElement('input');
    inp.type = 'text';
    inp.placeholder = label;
    inp.setAttribute('aria-label', label);
    const ok = document.createElement('button');
    ok.type = 'button'; ok.className = 'dn-inline-ok'; ok.textContent = 'إضافة';
    const no = document.createElement('button');
    no.type = 'button'; no.className = 'dn-inline-no'; no.textContent = '✕'; no.title = 'إلغاء';
    box.append(inp, ok, no);
    btn.parentNode.insertBefore(box, btn);
    btn.hidden = true;
    inp.focus();

    const close = () => { box.remove(); btn.hidden = false; };
    no.addEventListener('click', close);
    inp.addEventListener('keydown', ev => {
      if (ev.key === 'Escape') close();
      if (ev.key === 'Enter') { ev.preventDefault(); submit(); }
    });

    async function submit() {
      const name = inp.value.trim();
      if (!name) { inp.focus(); return; }
      ok.disabled = true; inp.disabled = true;
      try {
        const body = {kind, name};
        if (kind === 'student') body.circle_id = circleId;
        const data = await post(ADD_URL, body, {label: 'إضافة ' + name});
        if (kind === 'student') addStudentCard(data.student, circleId);
        else addTeacherCard(data.teacher);
        toast('✅ أُضيف «' + name + '»', 'success');
        setStatus('✅ أُضيف «' + name + '»');
        close();
      } catch (err) {
        toast('❌ ' + (err.message || 'تعذّرت الإضافة'), 'error');
        ok.disabled = false; inp.disabled = false; inp.focus();
      }
    }
    ok.addEventListener('click', submit);
  }

  document.addEventListener('click', e => {
    const stBtn = e.target.closest('[data-add-student-circle]');
    if (stBtn) {
      inlineAdd(stBtn, {kind: 'student', label: 'اسم الطالب…', circleId: stBtn.dataset.addStudentCircle});
      return;
    }
    const tBtn = e.target.closest('[data-add-teacher]');
    if (tBtn) {
      inlineAdd(tBtn, {kind: 'teacher', label: 'اسم الأستاذ/الكادر…'});
    }
  });

  /* زر «＋ إضافة» في الشريط: يفتح شريط الإضافة ويُركّز على اسم الطالب */
  $addToggle.addEventListener('click', () => {
    if (!$addbar.hidden) {
      const f = $addbar.querySelector('.dn-addform [name="name"]');
      if (f) f.focus();
    }
  });

  function studentCardEl(s) {
    const el = document.createElement('div');
    el.className = 'dn-card' + (s.parked ? ' dn-card-park' : '');
    el.dataset.kind = 'student';
    el.dataset.student = s.id;
    el.dataset.name = s.name;
    el.innerHTML = '<span class="dn-grip" aria-hidden="true">⠿</span>' +
      '<span class="dn-ring" data-ring style="--rate:0;--ring:#7A5AA8;--ink:#4d3471" title="لا سجلات حضور بعد">' +
      '<span class="dn-ring-txt">جديد</span></span><span class="dn-name"></span>';
    const nm = el.querySelector('.dn-name');
    nm.textContent = s.name;
    // الطالب المُضاف الآن بلا سجلات قبل الشهر ⇒ تظهر «جديد»
    if (s.is_new !== false) {
      const b = document.createElement('span');
      b.className = 'new-badge';
      b.textContent = 'جديد';
      b.title = 'لا يملك سجلات قبل بداية الشهر — فهو جديد';
      nm.appendChild(b);
    }
    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'dn-del';
    x.dataset.delStudent = s.id;
    x.dataset.name = s.name;
    x.textContent = '✕';
    x.title = 'وضع في سلة الحذف';
    el.appendChild(x);
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
    el.dataset.kind = 'teacher';
    el.dataset.teacher = t.id;
    el.dataset.name = t.name;
    el.innerHTML = '<span class="dn-tgrip" aria-hidden="true">⠿</span><span class="dn-tname"></span><span class="dn-trole">بلا حلقة</span>';
    el.querySelector('.dn-tname').textContent = '👨‍🏫 ' + t.name;
    box.querySelector('.dn-tempty')?.setAttribute('hidden', '');
    box.appendChild(el);
    // أضِفه إلى قوائم اختيار الأستاذ في نماذج الإضافة
    document.querySelectorAll('.dn-addform select[name="teacher_id"]').forEach(sel => {
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
      ${c.teacher ? `<div class="dn-teacher-card" data-teacher="${c.teacher_id}">
        <span class="dn-tgrip" aria-hidden="true">⠿</span>
        <span class="dn-tname"></span><span class="dn-trole">أستاذ الحلقة</span></div>` : ''}
      <div class="dn-list" data-list><div class="dn-empty">اسحب طلاباً إلى هنا</div></div>`;
    sec.querySelector('.dn-title').textContent = c.name;
    sec.querySelector('.dn-teacher').textContent = c.teacher || 'بلا أستاذ';
    if (c.teacher) {
      sec.querySelector('.dn-tname').textContent = '👨‍🏫 ' + c.teacher;
      sec.querySelector('.dn-teacher-card').dataset.name = c.teacher;     // dataset: آمن مع الاقتباسات والرموز
    }
    park.parentNode.insertBefore(sec, park);
    // أضِف الحلقة إلى قائمة اختيار الحلقة في نموذج إضافة طالب
    const sel = document.querySelector('.dn-addform select[name="circle_id"]');
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

  /* ═════ بديل مضمون للنقل: انقر البطاقة ثم انقر الحاوية ═════
     إن فشل السحب لأي سبب (متصفح قديم، إيماءة محجوبة، شاشة غير متوقعة) يبقى النقل
     ممكناً بنقرتين: النقرة الأولى تُعلّم البطاقة، والثانية على أي حاوية تنقلها.
     يُلغى بالضغط على Esc أو بالنقر على البطاقة مرة أخرى. */
  let picked = null;
  function clearPick() {
    if (picked) { picked.classList.remove('is-picked'); picked = null; }
    board.classList.remove('is-picking');
  }
  let lastDragAt = 0;      // وقت آخر سحب حقيقي — لتجاهل «click» الذي يليه
  let dragStartedAt = 0;   // وقت بدء السحب (لتمييز نقرة المتصفح التابعة)
  function pickCard(card) {
    clearPick();
    picked = card;
    card.classList.add('is-picked');
    board.classList.add('is-picking');
    const hint = card.dataset.kind === 'teacher'
      ? 'انقر حاويةً لنقل الأستاذ إليها (أو الحاوية الفارغة ليصبح بلا حلقة)'
      : 'انقر حاويةً لنقل الطالب إليها — أو اضغط Esc للإلغاء';
    setStatus('👉 ' + hint);
  }
  board.addEventListener('click', e => {
    if (dragStartedAt && Date.now() - dragStartedAt < 600) { dragStartedAt = 0; return; }  // نقرة تابعة لسحب
    if (e.target.closest('.dn-del, .dn-tdel, .dn-addone, .dn-quickadd, .dn-inline-add')) return;
    const col = e.target.closest(COL_SEL);
    // نقرة على حاوية وهناك بطاقة مُعلَّمة ⇒ تنفيذ النقل
    if (picked && col) {
      const card = picked;
      const from = card.closest(COL_SEL);
      clearPick();
      if (from === col) { setStatus('نفس الحاوية — لم يتغيّر شيء'); return; }
      if (isTeacherCard(card)) moveTeacher(card, col);
      else doMove(card, from, col, false);
      return;
    }
    const card = e.target.closest('.dn-card, .dn-teacher-card');
    if (!card) { if (picked) clearPick(); return; }
    // النقر على بطاقة مُعلَّمة يُلغي التعليم
    if (card === picked) { clearPick(); setStatus(''); return; }
    pickCard(card);
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && picked) { clearPick(); setStatus('أُلغي النقل'); } });

  /* ═════════ سلة الحذف ═════════
     ضغط ✕ لا يحذف شيئاً: يضع العنصر في السلة (يبدو كأنه محذوف) ويُثبَّت الحذف فعلياً
     عند «حفظ الحذف نهائياً» أو عند مغادرة الصفحة (كما طلب المستخدم). */
  const $trash = document.getElementById('dn-trash');
  const $trashBody = document.getElementById('dn-trash-body');
  const $trashCount = document.getElementById('dn-trash-count');
  const $trashFab = document.getElementById('dn-trash-fab');
  const $trashFabN = document.getElementById('dn-trash-fab-n');
  // {key: {kind, id, name, el}}
  const basket = new Map();

  const KIND_LABEL = {student: 'طالب', teacher: 'أستاذ', circle: 'حلقة'};

  function basketList() { return [...basket.values()]; }

  function syncBasket() {
    const n = basket.size;
    $trashCount.textContent = n;
    $trashFabN.textContent = n;
    $trashFab.hidden = n === 0;
    if (n === 0) $trash.hidden = true;
    if (!$find.value.trim()) setStatus(n ? ('🗑 ' + n + ' عنصراً في سلة الحذف') : '');
    renderBasket();
  }

  function renderBasket() {
    $trashBody.innerHTML = '';
    basketList().forEach(item => {
      const row = document.createElement('div');
      row.className = 'dn-trash-item';
      const kind = document.createElement('span');
      kind.className = 'kind ' + item.kind;
      kind.textContent = KIND_LABEL[item.kind] || '';
      const nm = document.createElement('span');
      nm.className = 'nm';
      nm.textContent = item.name;
      row.appendChild(kind); row.appendChild(nm);
      if (item.kind === 'circle' && item.students) {
        const w = document.createElement('span');
        w.className = 'warn';
        w.textContent = '⚠ معها ' + item.students + ' طالباً';
        row.appendChild(w);
      }
      const undo = document.createElement('button');
      undo.type = 'button';
      undo.className = 'undo-one';
      undo.textContent = '↩';
      undo.title = 'استرجاع';
      undo.addEventListener('click', () => restore(item.key));
      row.appendChild(undo);
      $trashBody.appendChild(row);
    });
  }

  async function addToBasket(kind, id, name, el) {
    const key = kind + ':' + id;
    if (basket.has(key)) return;
    el.classList.add('dn-trashed');
    el.dataset.trashKey = key;
    const item = {key, kind, id, name, el, students: 0};
    basket.set(key, item);
    if (kind === 'circle') {
      // تأكيد صريح: كم طالباً سيُحذف مع الحلقة (يُطلب قبل الحذف النهائي)
      try {
        const info = await post(CIRCLE_INFO_URL, {circle_id: id}, {label: 'تفاصيل الحلقة'});
        item.students = info.circle.students;
      } catch (e) { /* يبقى 0 */ }
      // امسح الحلقة بصرياً: بطاقاتها تصبح شبه شفافة
      el.querySelectorAll('.dn-card, .dn-teacher-card').forEach(c => c.classList.add('dn-trashed'));
    }
    syncBasket();
    toast('🗑 «' + name + '» في سلة الحذف — لم يُحذف بعد', 'warn');
  }

  function restore(key) {
    const item = basket.get(key);
    if (!item) return;
    basket.delete(key);
    item.el.classList.remove('dn-trashed');
    delete item.el.dataset.trashKey;
    if (item.kind === 'circle') {
      item.el.querySelectorAll('.dn-trashed').forEach(c => c.classList.remove('dn-trashed'));
    }
    syncBasket();
  }

  function restoreAll() {
    [...basket.keys()].forEach(restore);
  }

  async function commitBasket({force} = {}) {
    if (basket.size === 0) return true;
    const items = basketList();
    const circles = items.filter(i => i.kind === 'circle');
    const withStudents = circles.filter(i => i.students);
    if (!force) {
      let msg = 'حذف ' + items.length + ' عنصراً نهائياً؟';
      if (withStudents.length) {
        msg += '\n\n⚠ حذف هذه الحلقات يحذف طلابها أيضاً:\n' +
          withStudents.map(c => '• ' + c.name + ' (' + c.students + ' طالباً)').join('\n');
      }
      msg += '\n\nلا يمكن التراجع عن الحذف.';
      if (!confirm(msg)) return false;
    }
    // احذف لكل نوع على حدة
    const groups = {};
    items.forEach(i => { (groups[i.kind] = groups[i.kind] || []).push(i.id); });
    try {
      for (const kind of Object.keys(groups)) {
        await post(DELETE_URL, {kind, ids: groups[kind].join(',')}, {label: 'حذف ' + KIND_LABEL[kind]});
      }
      // إزالة العناصر من الصفحة نهائياً
      items.forEach(i => {
        const col = i.el.closest(COL_SEL);
        i.el.remove();
        if (col) recount(col);
      });
      // إن حُذفت حلقات: أزل أعمدةها، وحرّك طلابها المحذوفين
      circles.forEach(c => {
        const col = board.querySelector('[data-circle="' + c.id + '"].dn-col, [data-circle="' + c.id + '"].dn-park');
        if (col) col.remove();
      });
      basket.clear();
      syncBasket();
      $trash.hidden = true;
      toast('✅ تم الحذف النهائي', 'success');
      setStatus('✅ حُذف ' + items.length + ' عنصراً');
      return true;
    } catch (e) {
      toast('❌ ' + e.message, 'error');
      return false;
    }
  }

  // أزرار ✕ داخل اللوحة
  board.addEventListener('click', e => {
    const st = e.target.closest('[data-del-student]');
    const ci = e.target.closest('[data-del-circle]');
    const out = e.target.closest('[data-out-teacher]');
    if (st) {
      const card = st.closest('.dn-card');
      addToBasket('student', st.dataset.delStudent, card.dataset.name, card);
    } else if (ci) {
      const col = ci.closest(COL_SEL);
      addToBasket('circle', ci.dataset.delCircle, ci.dataset.name, col);
    } else if (out) {
      // الأستاذ لا يُحذف من هنا: ✕ = إخراجه من الحلقة إلى الحاوية الفارغة (يصبح بلا حلقة)
      const card = out.closest('.dn-teacher-card');
      moveTeacher(card, colById('park'));
    }
  });

  $trashFab.addEventListener('click', () => { $trash.hidden = !$trash.hidden; });
  document.getElementById('dn-trash-close').addEventListener('click', () => { $trash.hidden = true; });
  document.getElementById('dn-trash-restore').addEventListener('click', restoreAll);
  document.getElementById('dn-trash-exec').addEventListener('click', async () => {
    const btn = document.getElementById('dn-trash-exec');
    btn.disabled = true;
    try { await commitBasket({force: false}); } finally { btn.disabled = false; }
  });

  /* إظهار/إخفاء وسوم السبر */
  (function () {
    const btn = document.getElementById('dn-sabr-toggle');
    if (!btn) return;
    btn.addEventListener('click', () => {
      const off = board.classList.toggle('hide-sabr');
      btn.textContent = off ? '📝 إظهار السبر' : '📝 إخفاء السبر';
    });
  })();

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
