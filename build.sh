#!/usr/bin/env bash
# أمر البناء على Render:  ./build.sh
# (يمكنك أيضاً استخدام أمرك الخاص، فالأمر migrate نفسه صار يتجاوز
#  الجداول الموجودة فعلاً تلقائياً — لا حاجة لتعديل إعدادات Render)
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --noinput

# ── الترحيلات ────────────────────────────────────────────────────────────────
# أمر migrate هنا نسخة ذكية: تتجاوز الترحيلات التي عناصرها موجودة بالفعل
# (relation "…" already exists) وتُسجّلها بدل أن يُفشل البناء.
echo "── تشغيل ترحيلات قاعدة البيانات ──"
if python manage.py migrate --noinput; then
  echo "✅ المخطط محدَّث"
else
  echo "⚠️ تحذير: فشل migrate — سيُعاد المحاولة تلقائياً عند إقلاع التطبيق."
  echo "   ويمكنك تطبيقه يدوياً من «المطور ← 🗂 الترحيلات»."
fi

python manage.py createcachetable
echo "── انتهى البناء ──"
