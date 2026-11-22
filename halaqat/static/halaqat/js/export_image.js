/*
 * تصدير جدول «الحضور — آخر 4 أسابيع» للطالب كصورة PNG.
 * رسم مباشر على Canvas (بلا مكتبات خارجية وبلا طلبات للسيرفر) من بيانات الجدول الظاهر في الصفحة.
 *
 *  • زر [data-export-image]  : يحفظ الصورة على الجهاز.
 *  • زر [data-share-image]   : يفتح قائمة المشاركة (واتساب…) ويظهر فقط على الأجهزة التي تدعم مشاركة الملفات.
 *  • يعمل في صفحة الطالب وفي نافذة الإحصائيات السريعة؛ وتُستدعى AttExport.init(root) بعد إدراج HTML جديد.
 */
(function () {
  'use strict';

  const COLORS = {present: '#5A9367', late: '#D9A441', absent: '#B5544B', excused: '#6B8CAE', none: '#c9c2b6'};
  const LABELS = {present: 'حاضر', late: 'تأخر', absent: 'غياب', excused: 'إذن', none: 'غير مسجّل'};
  const ORDER = ['present', 'late', 'absent', 'excused', 'none'];
  const MONTHS = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر'];
  const INK = '#4A3420', MUTED = '#7a6a55', LINE = '#E8D5B7', BG = '#FAF7F2', PRIMARY = '#B17F4A';
  const FONT = "Dubai, 'Segoe UI', Tahoma, 'Noto Naskh Arabic', Arial, sans-serif";
  const SCALE = 2;                       // دقة مضاعفة لتبدو الصورة حادّة على الهاتف

  const toast = (msg, type) => { if (typeof window.showToast === 'function') window.showToast(msg, type || 'info', 3500); };

  /* ── قراءة بيانات الجدول من الصفحة ── */
  function readCard(card) {
    const cells = [...card.querySelectorAll('.att-grid .dc')].map(el => {
      const mark = el.querySelector('u');
      let status = 'none';
      if (mark) { const m = (mark.className.match(/s-(present|late|absent|excused)/) || [])[1]; if (m) status = m; }
      return {
        day: parseInt(el.textContent, 10) || 0,
        date: el.dataset.date || '',
        status,
        today: el.classList.contains('today'),
      };
    });
    const counts = {present: 0, late: 0, absent: 0, excused: 0, none: 0};
    cells.forEach(c => { counts[c.status]++; });
    return {
      student: card.dataset.student || '',
      circle: card.dataset.circle || '',
      start: card.dataset.start || '', end: card.dataset.end || '',
      cells, counts,
    };
  }

  function roundRect(ctx, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  async function ensureFonts() {
    try {
      if (document.fonts && document.fonts.load) {
        await Promise.all([document.fonts.load("400 16px Dubai"), document.fonts.load("700 16px Dubai")]);
      }
    } catch (e) { /* نكمل بالخط البديل */ }
  }

  /* ── رسم الصورة ── */
  async function draw(data) {
    await ensureFonts();
    const W = 760, PAD = 28, GAP = 8, COLS = 7;
    const cw = (W - PAD * 2 - GAP * (COLS - 1)) / COLS, ch = 66;
    const rows = Math.ceil(data.cells.length / COLS);
    const gridH = rows * ch + (rows - 1) * GAP;

    const headerH = 138, legendH = 40, tilesH = 74, footerH = 46;
    const H = headerH + legendH + gridH + 22 + tilesH + footerH;

    const cv = document.createElement('canvas');
    cv.width = W * SCALE; cv.height = H * SCALE;
    const ctx = cv.getContext('2d');
    ctx.scale(SCALE, SCALE);
    ctx.direction = 'rtl';
    ctx.textBaseline = 'alphabetic';

    const text = (str, x, y, size, color, weight, align) => {
      ctx.font = `${weight || 400} ${size}px ${FONT}`;
      ctx.fillStyle = color; ctx.textAlign = align || 'right';
      ctx.fillText(str, x, y);
    };

    // الخلفية والبطاقة
    ctx.fillStyle = BG; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#ffffff'; roundRect(ctx, 10, 10, W - 20, H - 20, 20); ctx.fill();
    ctx.strokeStyle = LINE; ctx.lineWidth = 1.5; ctx.stroke();

    // شريط علوي بلون الهوية
    ctx.save(); roundRect(ctx, 10, 10, W - 20, 12, 6); ctx.clip();
    ctx.fillStyle = PRIMARY; ctx.fillRect(10, 10, W - 20, 12); ctx.restore();

    // الترويسة: اسم الطالب والحلقة والفترة
    const R = W - PAD;
    text(data.student, R, 66, 30, INK, 700);
    if (data.circle) text(data.circle.startsWith('حلقة') ? data.circle : 'حلقة ' + data.circle, R, 96, 18, MUTED, 500);
    text('الحضور — آخر 4 أسابيع', R, 122, 15, PRIMARY, 700);
    if (data.start && data.end) text(`${data.start}  ←  ${data.end}`, PAD, 122, 14, MUTED, 400, 'left');

    ctx.strokeStyle = LINE; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(PAD, headerH - 6); ctx.lineTo(W - PAD, headerH - 6); ctx.stroke();

    // مفتاح الألوان (من اليمين لليسار)
    let lx = R, ly = headerH + 22;
    ctx.direction = 'rtl';
    ORDER.forEach(k => {
      ctx.fillStyle = COLORS[k]; roundRect(ctx, lx - 16, ly - 9, 16, 7, 3.5); ctx.fill();
      ctx.font = `400 13px ${FONT}`;
      const w = ctx.measureText(LABELS[k]).width;
      text(LABELS[k], lx - 22, ly, 13, MUTED, 400);
      lx -= 22 + w + 18;
    });

    // الشبكة: أول يوم عند أقصى اليمين (اتجاه عربي)
    const gy = headerH + legendH;
    data.cells.forEach((c, i) => {
      const col = i % COLS, row = Math.floor(i / COLS);
      const x = W - PAD - (col + 1) * cw - col * GAP;
      const y = gy + row * (ch + GAP);
      const empty = c.status === 'none';

      ctx.fillStyle = empty ? '#efede9' : BG;
      roundRect(ctx, x, y, cw, ch, 10); ctx.fill();
      ctx.strokeStyle = empty ? '#dedad3' : LINE; ctx.lineWidth = 1.2; ctx.stroke();
      if (c.today) { ctx.strokeStyle = PRIMARY; ctx.lineWidth = 3; roundRect(ctx, x - 1.5, y - 1.5, cw + 3, ch + 3, 11); ctx.stroke(); }

      // اسم الشهر عند أول خلية وعند بداية كل شهر
      if ((i === 0 || c.day === 1) && c.date) {
        const mi = parseInt(c.date.slice(5, 7), 10) - 1;
        if (MONTHS[mi]) text(MONTHS[mi], x + cw / 2, y + 17, 11.5, empty ? '#9a948a' : PRIMARY, 700, 'center');
      }
      text(String(c.day), x + cw / 2, y + 42, 24, empty ? '#9a948a' : INK, 700, 'center');

      if (!empty) {
        ctx.fillStyle = COLORS[c.status];
        roundRect(ctx, x + 12, y + ch - 14, cw - 24, 6, 3); ctx.fill();
      }
    });

    // مربعات الملخص
    const ty = gy + gridH + 22, tg = 8, tw = (W - PAD * 2 - tg * 4) / 5;
    ORDER.forEach((k, i) => {
      const x = W - PAD - (i + 1) * tw - i * tg;
      ctx.fillStyle = BG; roundRect(ctx, x, ty, tw, tilesH - 10, 12); ctx.fill();
      ctx.strokeStyle = LINE; ctx.lineWidth = 1; ctx.stroke();
      ctx.fillStyle = COLORS[k]; roundRect(ctx, x + tw / 2 - 14, ty + 8, 28, 5, 2.5); ctx.fill();
      text(String(data.counts[k]), x + tw / 2, ty + 38, 24, INK, 700, 'center');
      text(LABELS[k], x + tw / 2, ty + 56, 12.5, MUTED, 400, 'center');
    });

    // التذييل
    const fy = H - 24;
    text('مسجد طه — نظام إدارة حلقات القرآن', R, fy, 12.5, MUTED, 500);
    text(new Date().toISOString().slice(0, 10), PAD, fy, 12, '#a89a85', 400, 'left');
    return cv;
  }

  /* ── حفظ / مشاركة ── */
  const toBlob = cv => new Promise((res, rej) => cv.toBlob(b => (b ? res(b) : rej(new Error('تعذّر إنشاء الصورة'))), 'image/png'));

  function fileName(data) {
    const safe = (data.student || 'طالب').replace(/[\\/:*?"<>|]+/g, '').trim().replace(/\s+/g, '_');
    return `حضور_${safe}_${data.end || new Date().toISOString().slice(0, 10)}.png`;
  }

  function download(blob, name) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  async function run(btn, mode) {
    const card = btn.closest('[data-att-card]');
    if (!card || btn.dataset.busy) return;
    btn.dataset.busy = '1';
    const label = btn.textContent;
    btn.textContent = '… جاري الإنشاء';
    try {
      const data = readCard(card);
      const blob = await toBlob(await draw(data));
      const name = fileName(data);
      if (mode === 'share') {
        const file = new File([blob], name, {type: 'image/png'});
        if (navigator.canShare && navigator.canShare({files: [file]})) {
          try { await navigator.share({files: [file], title: `حضور ${data.student}`}); return; }
          catch (e) { if (e && e.name === 'AbortError') return; }      // أغلق المستخدم القائمة
        }
      }
      download(blob, name);
      toast('✅ تم حفظ الصورة', 'success');
    } catch (e) {
      toast('❌ تعذّر إنشاء الصورة', 'error');
    } finally {
      btn.textContent = label;
      delete btn.dataset.busy;
    }
  }

  /* ── إظهار زر المشاركة حيث يُدعم ── */
  function canShareFiles() {
    try {
      return !!(navigator.canShare && navigator.canShare({files: [new File([''], 'a.png', {type: 'image/png'})]}));
    } catch (e) { return false; }
  }
  function init(root) {
    if (!canShareFiles()) return;
    (root || document).querySelectorAll('[data-share-image]').forEach(b => { b.hidden = false; });
  }

  document.addEventListener('click', e => {
    const exp = e.target.closest('[data-export-image]');
    if (exp) { e.preventDefault(); run(exp, 'save'); return; }
    const sh = e.target.closest('[data-share-image]');
    if (sh) { e.preventDefault(); run(sh, 'share'); }
  });
  if (document.readyState !== 'loading') init(); else document.addEventListener('DOMContentLoaded', () => init());

  window.AttExport = {init, readCard, draw};
})();
