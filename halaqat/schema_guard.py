"""
حماية من «جدول مفقود» بعد النشر:

Render يشغّل ``build.sh`` (وفيه ``migrate``) **قبل** تشغيل الخادم، لكن قد يحدث أن
كوداً أحدث يعمل على قاعدة بيانات لم تُطبَّق عليها الترحيلات (نشر فاشل، أو migrate
فشل بصمت، أو استيراد SQLite استبدل الجداول). النتيجة: خطأ 500 مثل
``relation "halaqat_aisettings" does not exist``.

هذا الملف يوفّر:
  • ``pending_migrations()``: قائمة الترحيلات غير المطبّقة (بلا كتابة على القاعدة).
  • ``ensure_schema()``: يطبّق الترحيلات تلقائياً عند الإقلاع — آمن ومتزامن،
    ويُعطَّل بـ ``AUTO_MIGRATE=false`` إذا فُضِّل الاعتماد على build.sh فقط.
  • ``schema_status()``: ملخص للعرض في صفحة المطور.
"""
import logging
import os
import threading

from django.db import connection

logger = logging.getLogger(__name__)


def _migration_plan():
    """يعيد قائمة الترحيلات غير المطبّقة لكل التطبيقات (تعتمد فقط على جدول الترحيلات)."""
    from django.db.migrations.executor import MigrationExecutor
    executor = MigrationExecutor(connection)
    return executor.migration_plan(executor.loader.graph.leaf_nodes())


def pending_migrations():
    """
    أسماء الترحيلات غير المطبّقة، مثل ['halaqat.0010_ai_settings'].
    إن لم يكن جدول ``django_migrations`` موجوداً أصلاً تُعاد قائمة بداية كاملة.
    """
    try:
        plan = _migration_plan()
    except Exception as exc:                       # noqa: BLE001 — قاعدة غير مهيّأة/جدول مفقود
        logger.warning('تعذّر قراءة حالة الترحيلات: %s', exc)
        return ['(تعذّر القراءة — جرّب تشغيل الترحيلات)']
    return [f'{m.app_label}.{m.name}' for m, backwards in plan if not backwards]


def apply_migrations():
    """
    يطبّق كل الترحيلات المعلّقة ويعيد قائمة ما طُبِّق فعلياً.
    على PostgreSQL يستخدم قفلاً استشارياً لمنع تشغيل نسختين في وقت واحد.
    """
    from django.core.management import call_command

    applied_before = set(pending_migrations())
    if not applied_before:
        return []

    with connection.cursor() as cur:
        locked = False
        if connection.vendor == 'postgresql':
            cur.execute('SELECT pg_try_advisory_lock(918273645)')
            locked = bool(cur.fetchone()[0])
        try:
            if connection.vendor == 'postgresql' and not locked:
                logger.info('ترحيل جارٍ في عملية أخرى — تخطّي الترحيل التلقائي')
                return []
            call_command('migrate', interactive=False, verbosity=0)
        finally:
            if locked:
                cur.execute('SELECT pg_advisory_unlock(918273645)')

    remaining = set(pending_migrations())
    done = sorted(applied_before - remaining)
    if done:
        logger.info('طُبِّقت الترحيلات: %s', ', '.join(done))
    return done


def _table_exists(table):
    """
    هل الجدول موجود؟ نستخدم استعلاماً مستقلاً عن الجداول الوصفية إن أمكن،
    وإلا استعلاماً محاطاً بـ savepoint حتى لا يُفسد معاملة فاشلة الاتصال.
    """
    try:
        with connection.cursor() as cur:
            if connection.vendor == 'postgresql':
                # استعلام وصفي لا يفشل أبداً ولا يُفسد المعاملة
                cur.execute('SELECT to_regclass(%s) IS NOT NULL', [connection.ops.quote_name(table)])
                return bool(cur.fetchone()[0])
            cur.execute('SELECT 1 FROM ' + connection.ops.quote_name(table) + ' LIMIT 1')
        return True
    except Exception:                              # noqa: BLE001
        return False
    finally:
        # على PostgreSQL قد يُترك الاتصال في حالة «معاملة فاشلة» → نُعيده ليعمل
        if connection.vendor == 'postgresql':
            try:
                connection.rollback()
            except Exception:                      # noqa: BLE001
                pass


def schema_status():
    """ملخص لحالة المخطط — للعرض في صفحة المطور."""
    pending = pending_migrations()
    from django.apps import apps
    tables = {}
    for label in ('halaqat.AISettings', 'halaqat.AssistantQuery', 'halaqat.Recitation', 'halaqat.Circle',
                  'halaqat.Student', 'halaqat.Attendance'):
        try:
            model = apps.get_model(label)
        except LookupError:
            continue
        tables[label.split('.')[1]] = _table_exists(model._meta.db_table)
    return {
        'pending': pending,
        'pending_count': len(pending),
        'up_to_date': not pending,
        'tables': tables,
        'missing_tables': [k for k, ok in tables.items() if not ok],
        'engine': connection.vendor,
    }


def ensure_schema_async():
    """
    يشغّل الترحيلات في خيط خلفي عند الإقلاع حتى لا يتأخّر تشغيل الخادم.
    يُعطَّل بـ AUTO_MIGRATE=false، ويُتجاهل في بيئة الاختبارات.
    """
    if os.environ.get('AUTO_MIGRATE', 'true').lower() in ('0', 'false', 'no', 'off'):
        return None
    if os.environ.get('DJANGO_TESTING'):          # لا ترحيل أثناء الاختبارات
        return None

    def work():
        try:
            apply_migrations()
        except Exception as exc:                  # noqa: BLE001 — لا نُسقِط التطبيق أبداً
            logger.error('فشل الترحيل التلقائي عند الإقلاع: %s', exc)

    thread = threading.Thread(target=work, name='auto-migrate', daemon=True)
    thread.start()
    return thread


class SchemaErrorMiddleware:
    """
    شبكة أمان أخيرة: إن حدث خطأ «جدول/عمود مفقود» في أي صفحة (بسبب ترحيل غير مطبَّق)
    يُعرض صفحة عربية مفهومة مع رابط مباشر لتطبيق الترحيلات — بدل صفحة 500 طويلة.
    """

    MISSING_HINTS = ('does not exist', 'no such table', 'no such column', 'undefined table')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        from django.db import DatabaseError
        from django.http import JsonResponse
        from django.shortcuts import render

        if not isinstance(exception, DatabaseError):
            return None
        text = str(exception).lower()
        if not any(h in text for h in self.MISSING_HINTS):
            return None

        pending = pending_migrations()
        logger.error('جدول/عمود مفقود (ترحيلات معلّقة: %s): %s', pending, exception)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'code': 'schema',
                                 'error': 'قاعدة البيانات تحتاج تحديثاً (ترحيلات غير مطبَّقة). '
                                          'افتح «المطور ← 🗂 الترحيلات» واضغط «تطبيق الترحيلات الآن».',
                                 'pending': pending}, status=503)
        try:
            return render(request, 'halaqat/schema_error.html',
                          {'pending': pending, 'active_nav': None}, status=503)
        except Exception:                        # noqa: BLE001 — حتى القالب قد يفشل
            return None
