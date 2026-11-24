// حفظ تلقائي لحالة الحضور فور الضغط على الخيار - بدون زر حفظ
// يعمل بشكل عام على أي صف يحمل data-save-url / data-kind / data-entity-id / data-date
// (صفحة الحلقة، صفحة «الدورات القرآنية» المدموجة، وصفحة الغائبين تستخدم نفس الآلية)
// الحفظ يمرّ عبر TahaSync.post: إن انقطع الاتصال يُحفظ محلياً ويُرسل تلقائياً عند رجوعه.
document.addEventListener('DOMContentLoaded', function () {
  const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
  const toast = document.getElementById('save-toast');
  if (!csrfInput) return;
  const csrfToken = csrfInput.value;

  let toastTimer = null;
  function showToast(ok, msg) {
    if (!toast) return;
    toast.textContent = msg || (ok ? 'تم الحفظ ✓' : 'تعذّر الحفظ، حاول مجدداً');
    toast.classList.toggle('error', !ok);
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 1600);
  }

  function updateCounts(counts) {
    const p = document.getElementById('cnt-present');
    const l = document.getElementById('cnt-late');
    const a = document.getElementById('cnt-absent');
    const e = document.getElementById('cnt-excused');
    if (p) p.textContent = counts.present;
    if (l && counts.late !== undefined) l.textContent = counts.late;
    if (a) a.textContent = counts.absent;
    if (e) e.textContent = counts.excused;
  }

  /* التقاط التغيير في أي مكان (الصفحة أو النافذة المنبثقة) */
  document.addEventListener('change', function (e) {
    const input = e.target;
    if (input.type !== 'radio' || !input.name.startsWith('status_')) return;

    const row = input.closest('[data-save-url]');
    if (!row) return;

    const { saveUrl, kind, entityId, date } = row.dataset;
    const status = input.value;

    row.classList.add('saving');

    const formData = new URLSearchParams();
    formData.append('kind', kind || 'student');
    formData.append('entity_id', entityId);
    formData.append('status', status);
    formData.append('date', date);

    // مفتاح يجعل آخر حالة لنفس الطالب هي التي تُرسل (لا نُغرق السيرفر بتغييرات متتالية)
    const opts = {key: `att:${kind || 'student'}:${entityId}:${date}`};

    const send = window.TahaSync
      ? window.TahaSync.post(saveUrl, formData, opts)
      : fetch(saveUrl, {
          method: 'POST',
          headers: {'X-CSRFToken': csrfToken, 'Content-Type': 'application/x-www-form-urlencoded'},
          body: formData.toString(),
        }).then(r => r.json());

    send.then((data) => {
      row.classList.remove('saving');
      if (data.counts) updateCounts(data.counts);
      if (data.queued) {
        showToast(true, '📴 حُفظ على الجهاز — سيُرسل عند رجوع الاتصال');
      } else {
        showToast(true);
      }
      row.classList.remove('unrecorded-row');

      // في صفحة الغائبين: إن تغيّرت حالة طالب من "غائب/إذن" لحالة أخرى، أخفِ صفه تلقائياً
      if (row.classList.contains('resolvable-row')) {
        const originalStatus = row.dataset.originalStatus;
        if (status !== originalStatus) {
          row.classList.add('resolved');
          setTimeout(() => row.remove(), 450);
        }
      }
    }).catch((err) => {
      row.classList.remove('saving');
      showToast(false, (err && err.message) || 'تعذّر الحفظ');
      const label = row.querySelector(`label[for="${input.id}"]`);
      if (label) label.classList.add('shake');
      setTimeout(() => label && label.classList.remove('shake'), 600);
    });
  });
});
