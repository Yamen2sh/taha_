#!/usr/bin/env bash
# أمر البناء على Render:  ./build.sh
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --noinput

# ── الترحيلات ────────────────────────────────────────────────────────────────
# لا نستخدم errexit هنا عمداً: إن فشل migrate (شبكة/تنازع قفل) نُظهر الخطأ بوضوح
# ونكمل — ثم يعيد التطبيق المحاولة تلقائياً عند الإقلاع (halaqat/schema_guard.py).
echo "── تشغيل ترحيلات قاعدة البيانات ──"
if python manage.py migrate --noinput; then
  echo "✅ الترحيلات مطبَّقة"
else
  echo "⚠️ تحذير: فشل migrate في البناء — سيُعاد المحاولة تلقائياً عند إقلاع التطبيق."
  echo "   يمكنك أيضاً تطبيقه يدوياً من «المطور ← 🗂 الترحيلات»."
fi

# تحقّق سريع: هل بقيت ترحيلات معلّقة؟
python manage.py showmigrations halaqat | tail -5 || true

python manage.py createcachetable
echo "── انتهى البناء ──"
