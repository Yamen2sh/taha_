from django.apps import AppConfig


class HalaqatConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'halaqat'
    verbose_name = 'إدارة الحلقات'

    def ready(self):
        from . import checks  # noqa: F401  — فحص صلاحية القوالب عند check/النشر
        from . import signals  # noqa: F401  — يربط إبطال الكاش بتعديلات البيانات
