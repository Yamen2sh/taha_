import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'masjid_taha.settings')
application = get_asgi_application()

# تحميل الكاش مسبقاً عند تشغيل التطبيق (خيط خلفي لا يؤخّر الإقلاع) — انظر halaqat/cache_utils.py
from halaqat import cache_utils  # noqa: E402
cache_utils.warm_cache_async()

# تطبيق الترحيلات المعلّقة تلقائياً عند الإقلاع (يمنع «جدول مفقود» بعد النشر)
from halaqat import schema_guard  # noqa: E402
schema_guard.ensure_schema_async()
