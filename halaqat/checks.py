"""
فحص نظام: يتأكد أن كل القوالب تُحمَّل فعلاً قبل النشر.

`manage.py check` لا يفحص صلاحية القوالب، فخطأ `{% if %}` غير مغلق (أو وسم
مقطوع عبر سطرين بسبب تنسيق تلقائي) لا يظهر إلا عند فتح الصفحة في الإنتاج.
"""
import glob
import os

from django.apps import apps as django_apps
from django.conf import settings
from django.core.checks import Error, register


@register()
def templates_load_check(app_configs=None, **kwargs):
    """يتأكد من أن كل ملفات القوالب تُحلَّل بلا أخطاء."""
    errors = []
    loader = None
    try:
        from django.template.loader import get_template
        loader = get_template
    except Exception:                                  # noqa: BLE001
        return errors
    for app in django_apps.get_app_configs():
        root = os.path.join(app.path, 'templates')
        if not os.path.isdir(root):
            continue
        for path in glob.glob(os.path.join(root, '**', '*.html'), recursive=True):
            name = os.path.relpath(path, root).replace(os.sep, '/')
            try:
                loader(name)
            except Exception as exc:                   # noqa: BLE001
                errors.append(Error(
                    f'القالب «{name}» لا يُحلَّل: {exc}',
                    hint='افحص توازن {% if %}/{% endif %} وتأكد أن الوسوم غير مقطوعة عبر أسطر.',
                    obj=app.name, id='halaqat.E001',
                ))
    return errors
