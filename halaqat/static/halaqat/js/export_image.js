/*
 * تصدير أيام الحضور (آخر 4 أسابيع) للطالب كصورة PNG.
 *
 * يعرض **أيام الحضور الفعلية فقط** — لا شبكة أيام فارغة:
 *   • فوق كل يوم: اسم اليوم (السبت/الأحد…) والتاريخ (12/4).
 *   • داخل اليوم: مربّع الحالة (حاضر/تأخر/غياب/إذن) + عدد الصفحات المسمّعة + عدد الأسابير.
 *   • بطاقة تدرّج الطالب (أصفر ← أحمر) أو شارة «جديد».
 *
 * رسم مباشر على Canvas (بلا مكتبات وبلا طلبات للسيرفر) من بيانات البطاقة الظاهرة.
 */
(function () {
  'use strict';

  const COLORS = {present: '#5A9367', late: '#D9A441', absent: '#B5544B', excused: '#6B8CAE'};
  const LABELS = {present: 'حاضر', late: 'تأخر', absent: 'غياب', excused: 'إذن'};
  const ORDER = ['present', 'late', 'absent', 'excused'];
  const GRADE_COLORS = {yellow: '#E0B33A', orange: '#E08C33', deep: '#D2603A', red: '#C0392B', new: '#7A5AA8'};
  const INK = '#4A3420', MUTED = '#7a6a55', LINE = '#E8D5B7', BG = '#FAF7F2', PRIMARY = '#B17F4A';
  const FONT = "Dubai, 'Segoe UI', Tahoma, 'Noto Naskh Arabic', Arial, sans-serif";
  const SCALE = 2;

  const toast = (msg, type) => { if (typeof window.showToast === 'function') window.showToast(msg, type || 'info', 3500); };

  /* ── قراءة أيام الحضور من البطاقة ── */
  function readCard(card) {
    const days = [...card.querySelectorAll('.att-days .att-day')].map(el => ({
      date: el.dataset.date || '',
      status: el.dataset.status || 'present',
      weekday: el.dataset.weekday || '',
      pages: parseInt(el.dataset.pages, 10) || 0,
      sabr: parseInt(el.dataset.sabr, 10) || 0,
    }));
    const counts = {present: 0, late: 0, absent: 0, excused: 0};
    days.forEach(d => { counts[d.status] = (counts[d.status] || 0) + 1; });
    return {
      student: card.dataset.student || '',
      circle: card.dataset.circle || '',
      start: card.dataset.start || '', end: card.dataset.end || '',
      grade: card.dataset.grade || '',
      rate: card.dataset.rate || '',
      gradeLabel: card.dataset.gradeLabel || '',
      days, counts,
      totalPages: days.reduce((s, d) => s + d.pages, 0),
      totalSabr: days.reduce((s, d) => s + d.sabr, 0),
    };
  }

  function roundRect(ctx, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath(); ctx.moveTo(x + r, y);
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

  const shortDate = iso => {
    if (!iso || iso.length < 10) return '';
    const [, m, d] = iso.split('-');
    return `${parseInt(d, 10)}/${parseInt(m, 10)}`;
  };

  /* ── رسم الصورة ── */
  async function draw(data) {
    await ensureFonts();
    const W = 760, PAD = 28, GAP = 9, COLS = 5;
    const cw = (W - PAD * 2 - GAP * (COLS - 1)) / COLS, ch = 84;
    const rows = Math.max(1, Math.ceil(data.days.length / COLS));
    const gridH = rows * ch + (rows - 1) * GAP;

    const headerH = 140, legendH = 42, tilesH = 84, footerH = 46;
    const H = headerH + legendH + gridH + 24 + tilesH + footerH;

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

    const R = W - PAD;
    text(data.student, R, 66, 30, INK, 700);
    if (data.circle) text(data.circle.startsWith('حلقة') ? data.circle : 'حلقة ' + data.circle, R, 96, 18, MUTED, 500);
    text('أيام الحضور — آخر 4 أسابيع', R, 122, 15, PRIMARY, 700);
    if (data.start && data.end) text(`${data.start}  ←  ${data.end}`, PAD, 122, 14, MUTED, 400, 'left');

    // بطاقة التدرّج (أعلى اليسار)
    if (data.grade) {
      const gc = GRADE_COLORS[data.grade] || PRIMARY;
      const label = data.grade === 'new' ? 'جديد' : `${data.gradeLabel}${data.rate ? ' ' + data.rate + '%' : ''}`;
      ctx.font = `700 14px ${FONT}`;
      const tw = ctx.measureText(label).width + 30;
      ctx.fillStyle = gc; roundRect(ctx, PAD, 40, tw, 32, 16); ctx.fill();
      text(label, PAD + tw - 15, 61, 14, '#ffffff', 700);
    }

    ctx.strokeStyle = LINE; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(PAD, headerH - 6); ctx.lineTo(W - PAD, headerH - 6); ctx.stroke();

    // مفتاح الألوان
    let lx = R; const ly = headerH + 24;
    ctx.direction = 'rtl';
    ORDER.forEach(k => {
      ctx.fillStyle = COLORS[k]; roundRect(ctx, lx - 16, ly - 9, 16, 7, 3.5); ctx.fill();
      ctx.font = `400 13px ${FONT}`;
      const w = ctx.measureText(LABELS[k]).width;
      text(LABELS[k], lx - 22, ly, 13, MUTED, 400);
      lx -= 22 + w + 18;
    });

    // أيام الحضور فقط — أول يوم عند أقصى اليمين
    const gy = headerH + legendH;
    if (!data.days.length) {
      text('لا توجد أيام حضور مسجَّلة في هذه الفترة', W / 2, gy + 44, 18, MUTED, 500, 'center');
    }
    data.days.forEach((c, i) => {
      const col = i % COLS, row = Math.floor(i / COLS);
      const x = W - PAD - (col + 1) * cw - col * GAP;
      const y = gy + row * (ch + GAP);
      const color = COLORS[c.status] || MUTED;

      ctx.fillStyle = BG; roundRect(ctx, x, y, cw, ch, 12); ctx.fill();
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();

      // اسم اليوم + التاريخ فوق اليوم
      text(c.weekday, x + cw / 2, y + 24, 14.5, INK, 700, 'center');
      text(shortDate(c.date), x + cw / 2, y + 42, 13, MUTED, 400, 'center');

      // الحالة
      ctx.fillStyle = color; roundRect(ctx, x + cw / 2 - 24, y + 50, 48, 6, 3); ctx.fill();
      text(LABELS[c.status] || '', x + cw / 2, y + 72, 12.5, color, 700, 'center');

      // الصفحات والأسابير
      if (c.pages || c.sabr) {
        const bits = [];
        if (c.pages) bits.push(`📖 ${c.pages}`);
        if (c.sabr) bits.push(`📝 ${c.sabr}`);
        text(bits.join('  '), x + cw / 2, y + ch - 4, 11, MUTED, 500, 'center');
      }
    });

    // مربعات الملخص: الحالات + الصفحات + الأسابير
    const ty = gy + gridH + 24, tg = 8;
    const tiles = ORDER.map(k => ({n: data.counts[k] || 0, l: LABELS[k], c: COLORS[k]}));
    tiles.push({n: data.totalPages, l: 'صفحات', c: PRIMARY});
    tiles.push({n: data.totalSabr, l: 'أسابير', c: '#7A5AA8'});
    const tw = (W - PAD * 2 - tg * (tiles.length - 1)) / tiles.length;
    tiles.forEach((t, i) => {
      const x = W - PAD - (i + 1) * tw - i * tg;
      ctx.fillStyle = BG; roundRect(ctx, x, ty, tw, tilesH - 10, 12); ctx.fill();
      ctx.strokeStyle = LINE; ctx.lineWidth = 1; ctx.stroke();
      ctx.fillStyle = t.c; roundRect(ctx, x + tw / 2 - 14, ty + 8, 28, 5, 2.5); ctx.fill();
      text(String(t.n), x + tw / 2, ty + 40, 23, INK, 700, 'center');
      text(t.l, x + tw / 2, ty + 58, 12.5, MUTED, 400, 'center');
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
          catch (e) { if (e && e.name === 'AbortError') return; }
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
