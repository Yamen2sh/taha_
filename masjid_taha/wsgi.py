import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'masjid_taha.settings')
application = get_wsgi_application()

# تحميل الكاش مسبقاً عند تشغيل التطبيق (خيط خلفي لا يؤخّر الإقلاع) — انظر halaqat/cache_utils.py
from halaqat import cache_utils  # noqa: E402
cache_utils.warm_cache_async()
