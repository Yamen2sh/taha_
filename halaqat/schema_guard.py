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

from django.apps import apps
from django.db import connection

logger = logging.getLogger(__name__)


def _run_original_migrate(*args, **options):
    """
    ينفّذ أمر ``migrate`` الأصلي في Django متجاوزاً نسختنا الذكية
    (halaqat/management/commands/migrate.py) لتجنّب الاستدعاء الذاتي.
    """
    from django.core.management import call_command
    from django.core.management.commands import migrate as django_migrate

    options.setdefault('interactive', False)
    options.setdefault('verbosity', 0)
    return call_command(django_migrate.Command(), *args, **options)


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


def _table_columns(table):
    """
    أسماء أعمدة جدول (بلا أي استعلام على الجدول نفسه، فلا يُفسد أي معاملة).
    يعيد set() إن لم يوجد الجدول.
    """
    try:
        with connection.cursor() as cur:
            if connection.vendor == 'postgresql':
                cur.execute('SELECT to_regclass(%s) IS NOT NULL', [connection.ops.quote_name(table)])
                if not cur.fetchone()[0]:
                    return set()
                cur.execute("SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = %s", [table])
                return {r[0] for r in cur.fetchall()}
            cur.execute(f'PRAGMA table_info("{table}")')
            return {r[1] for r in cur.fetchall()}
    except Exception:                              # noqa: BLE001
        return set()


def _column_exists(table, column):
    """هل العمود موجود فعلاً في الجدول؟"""
    return column in _table_columns(table)


def _op_target(op, app_label, state=None):
    """
    يعيد (نوع الهدف، اسم الجدول، اسم العمود|None) للعمليات القابلة للتحقق،
    أو None للعمليات التي لا يمكن الحكم عليها (تعديل/حذف/تشغيل كود).

    ملاحظة مهمة: نأخذ اسم الجدول والعمود من **حالة الترحيل نفسها** (state)
    لا من النموذج الحالي — وإلا فحصنا عموداً لم يُنشأ بعد.
    """
    from django.db.migrations import operations as ops

    if isinstance(op, ops.CreateModel):
        model_state = state.models.get((app_label, op.name.lower())) if state else None
        table = (op.options or {}).get('db_table')
        if not table and model_state is not None:
            table = model_state.options.get('db_table')
        if not table:
            try:
                table = apps.get_model(app_label, op.name)._meta.db_table
            except LookupError:
                table = f'{app_label}_{op.name.lower()}'
        return ('table', table, None)

    if isinstance(op, ops.AddField):
        key = (app_label, op.model_name.lower())
        table = column = None
        if state is not None:
            model_state = state.models.get(key)
            if model_state is not None:
                table = model_state.options.get('db_table') or f'{app_label}_{op.model_name.lower()}'
        if not table:
            try:
                table = apps.get_model(app_label, op.model_name)._meta.db_table
            except LookupError:
                table = f'{app_label}_{op.model_name.lower()}'
        field = op.field
        try:
            field.set_attributes_from_name(op.name)
        except Exception:                          # noqa: BLE001
            pass
        column = getattr(field, 'column', None) or op.name
        return ('column', table, column)

    return None


def _pre_state(migration):
    """
    حالة المخطط **قبل** هذا الترحيل، مبنية من **كل** ترحيلات المصدر (القرص)
    بالترتيب — لا تعتمد على ما هو مطبَّق، فتعمل حتى على قاعدة فارغة.
    تُبنى مرة واحدة وتُخزَّن في الذاكرة.
    """
    from django.db.migrations.loader import MigrationLoader
    from django.db.migrations.state import ProjectState

    global _PRE_STATE_CACHE
    try:
        cached = _PRE_STATE_CACHE
    except NameError:
        cached = None
    if cached is None:
        cached = {}
        try:
            loader = MigrationLoader(None, ignore_no_migrations=True)
            state = ProjectState()
            order = []
            for key in _topological_migrations(loader):
                order.append(loader.disk_migrations[key])
            for mig in order:
                try:
                    state = state.clone()
                    for op in mig.operations:
                        op.state_forwards(mig.app_label, state)
                except Exception:                  # noqa: BLE001
                    pass
                cached[(mig.app_label, mig.name)] = state.clone()
        except Exception:                          # noqa: BLE001
            cached = {}
        _PRE_STATE_CACHE = cached

    key = (migration.app_label, migration.name)
    if key in cached:
        return cached[key]
    return ProjectState()


def _topological_migrations(loader):
    """
    ترتيب الترحيلات من الأقدم إلى الأحدث حسب تبعيات الرسم.
    (مفاتيح node_map كائنات Node، لذلك نستخرج .key منها بعناية.)
    """
    ordered, seen = [], set()

    def key_of(node):
        return getattr(node, 'key', node)

    def visit(node, stack=()):
        key = key_of(node)
        if key in seen or key in stack:
            return
        for parent in getattr(node, 'parents', ()):
            visit(parent, stack + (key,))
        seen.add(key)
        ordered.append(key)

    for key in sorted(loader.disk_migrations):
        node = loader.graph.node_map.get(key)
        if node is not None:
            visit(node)
        elif key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


def _migration_already_satisfied(migration):
    """
    صحيح **فقط** إن كانت كل عمليات الترحيل إنشاءات (جدول/عمود) وجميع أهدافها
    موجودة بالفعل — أي أن الترحيل نُفِّذ فعلاً لكن لم يُسجَّل في django_migrations.

    نتتبّع حالة المخطط خطوة بخطوة لمعرفة أسماء الأعمدة الحقيقية.
    أي عملية لا يمكن التحقق منها (تعديل/حذف/بيانات) → False (أأمن: نُنفّذ ولا نتجاوز).
    """
    from django.db.migrations import operations as ops

    state = _pre_state(migration)
    targets = []
    for op in migration.operations:
        target = _op_target(op, migration.app_label, state)
        if target is None:
            if isinstance(op, (ops.AlterModelOptions, ops.AlterModelTable)):
                pass                               # لا تُنشئ شيئاً — لا تمنع التجاوز
            else:
                return False                       # عملية لا يمكن التحقق منها
        else:
            targets.append(target)
        try:
            state = state.clone()
            op.state_forwards(migration.app_label, state)
        except Exception:                          # noqa: BLE001
            return False

    if not targets:
        return False
    for kind, table, column in targets:
        if kind == 'table' and not _table_exists(table):
            return False
        if kind == 'column' and not _column_exists(table, column):
            return False
    return True


def _mark_applied(migration):
    """يسجّل الترحيل كمطبَّق في django_migrations دون تنفيذه."""
    from django.db.migrations.recorder import MigrationRecorder
    recorder = MigrationRecorder(connection)
    recorder.record_applied(migration.app_label, migration.name)
    logger.info('تم تجاوز الترحيل %s.%s (العناصر موجودة فعلاً)', migration.app_label, migration.name)


_DUPLICATE_HINTS = ('already exists', 'duplicate table', 'duplicate column', 'duplicate_object',
                    'already in use')


def record_satisfied_migrations():
    """
    يُسجّل — بلا تنفيذ — كل ترحيل معلّق عناصره موجودة فعلاً في القاعدة.
    مفيد كخطوة إصلاح مستقلة عند خطأ «already exists».
    يعيد قائمة ما سُجِّل.
    """
    from django.db.migrations.executor import MigrationExecutor
    recorded = []
    executor = MigrationExecutor(connection)
    pending = [m for m, backwards in executor.migration_plan(executor.loader.graph.leaf_nodes())
               if not backwards]
    for migration in pending:
        if _migration_already_satisfied(migration):
            _mark_applied(migration)
            recorded.append(f'{migration.app_label}.{migration.name}')
    return recorded


def apply_migrations():
    """
    يطبّق كل الترحيلات المعلّقة ويعيد قائمة ما طُبِّق فعلياً (أو تُجوهز عنه).

    يتعامل مع الحالة الواقعية: جدول موجود في القاعدة لكن ترحيله غير مسجَّل
    (مثل ``relation "halaqat_assistantquery" already exists``) عبر:
      • تحقّق مسبق: إن كانت كل عمليات الترحيل إنشاءات وأهدافها موجودة → يُسجَّل كمطبَّق.
      • وإن فشل التنفيذ بخطأ «موجود بالفعل» يُسجَّل الترحيل ويُكمَل إلى ما بعده.
    على PostgreSQL يستخدم قفلاً استشارياً لمنع تشغيل نسختين في وقت واحد.
    """
    from django.db.migrations.executor import MigrationExecutor

    applied, skipped = [], []
    with connection.cursor() as cur:
        locked = False
        if connection.vendor == 'postgresql':
            cur.execute('SELECT pg_try_advisory_lock(918273645)')
            locked = bool(cur.fetchone()[0])
        try:
            if connection.vendor == 'postgresql' and not locked:
                logger.info('ترحيل جارٍ في عملية أخرى — تخطّي الترحيل التلقائي')
                return []
            # حلقة: نُطبّق ترحيلاً واحداً في كل دورة حتى نتحكّم في حالة «موجود بالفعل»
            for _ in range(200):
                executor = MigrationExecutor(connection)
                pending = [m for m, backwards in executor.migration_plan(executor.loader.graph.leaf_nodes())
                           if not backwards]
                if not pending:
                    break
                migration = pending[0]                     # الترحيل التالي في الترتيب
                if _migration_already_satisfied(migration):
                    _mark_applied(migration)
                    skipped.append(f'{migration.app_label}.{migration.name}')
                    continue
                try:
                    _run_original_migrate(migration.app_label, migration.name)
                    applied.append(f'{migration.app_label}.{migration.name}')
                except Exception as exc:                   # noqa: BLE001
                    message = str(exc).lower()
                    try:
                        connection.rollback()
                    except Exception:                  # noqa: BLE001
                        pass
                    if any(h in message for h in _DUPLICATE_HINTS):
                        # خطأ «موجود بالفعل» — لكن لا نثق به عمياناً:
                        # نتحقق أن كل عناصر الترحيل موجودة فعلاً قبل تسجيله كمطبَّق.
                        if _migration_already_satisfied(migration):
                            logger.warning('تجاوز %s.%s (عناصره موجودة فعلاً): %s',
                                           migration.app_label, migration.name, exc)
                            _mark_applied(migration)
                            skipped.append(f'{migration.app_label}.{migration.name}')
                            continue
                        logger.error('خطأ «موجود بالفعل» لكن عناصر %s.%s غير مكتملة — يُترك للتنفيذ',
                                     migration.app_label, migration.name)
                    raise
        finally:
            if locked:
                cur.execute('SELECT pg_advisory_unlock(918273645)')

    if applied:
        logger.info('طُبِّقت الترحيلات: %s', ', '.join(applied))
    if skipped:
        logger.info('تُجوهز عن ترحيلات (عناصرها موجودة): %s', ', '.join(skipped))
    return applied


def _table_exists(table):
    """هل الجدول موجود؟ استعلام وصفي فقط — لا نقرأ من الجدول (قد يكون تالفاً/بلا أعمدة)."""
    try:
        return bool(_table_columns(table))
    except Exception:                              # noqa: BLE001
        return False


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


def _recorded_migrations():
    """أسماء الترحيلات المسجَّلة فعلاً في django_migrations."""
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT app, name FROM django_migrations')
            return {(app, name) for app, name in cur.fetchall()}
    except Exception:                              # noqa: BLE001 — الجدول غير موجود
        return set()


def repair_history():
    """
    يُصلح «تاريخاً غير متّسق» في django_migrations: ترحيل غير مسجَّل لكن ترحيلاً
    لاحقاً يعتمد عليه مسجَّل (يسبّب ``InconsistentMigrationHistory`` فيتعطّل **كل**
    أمر ``migrate``). إن كانت عناصره موجودة فعلاً في القاعدة → يُسجَّل كمطبَّق.

    يُعيد قائمة الترحيلات التي سُجِّلت بهذه الطريقة.
    """
    from django.db.migrations.loader import MigrationLoader

    recorded = _recorded_migrations()
    if not recorded:
        return []
    try:
        loader = MigrationLoader(None, ignore_no_migrations=True)
    except Exception:                              # noqa: BLE001
        return []

    fixed = []
    for key in _topological_migrations(loader):
        if key in recorded:
            continue
        node = loader.graph.node_map.get(key)
        if node is None:
            continue
        # هل يعتمد عليه ترحيل مسجَّل؟ (أي أنه في المنتصف → تاريخ متّسق مستحيل)
        has_recorded_child = any(key_of(child) in recorded
                                 for child in getattr(node, 'children', ())
                                 for key_of in (lambda n: getattr(n, 'key', n),))
        if not has_recorded_child:
            continue
        migration = loader.disk_migrations.get(key)
        if migration is None or not _migration_already_satisfied(migration):
            continue
        try:
            _mark_applied(migration)
            recorded.add(key)
            fixed.append(f'{migration.app_label}.{migration.name}')
            logger.warning('إصلاح تاريخ الترحيلات: سُجِّل %s.%s كمطبَّق (عناصره موجودة)',
                           migration.app_label, migration.name)
        except Exception as exc:                   # noqa: BLE001
            logger.error('تعذّر إصلاح تاريخ الترحيلات لـ %s.%s: %s', key[0], key[1], exc)
    return fixed


def ensure_cache_table():
    """
    يتأكد من وجود جدول الكاش ``django_cache``.
    كاش قاعدة البيانات (DatabaseCache) يحتاج ``createcachetable``؛ وإن غاب الجدول
    تفشل **كل** صفحة تستخدم الكاش بـ 503 رغم سلامة المخطط والترحيلات.
    """
    from django.core.cache import cache, caches

    try:
        if caches['default'].__class__.__name__ != 'DatabaseCache':
            return False
    except Exception:                              # noqa: BLE001
        return False

    table = connection.ops.quote_name(caches['default']._table)
    if _table_exists(caches['default']._table):
        try:                                       # الجدول موجود — تأكد أنه سليم
            cache.get('__schema_probe__')
            return False
        except Exception:                          # noqa: BLE001 — جدول تالف
            logger.warning('جدول الكاش تالف — يُعاد إنشاؤه')
    try:
        with connection.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS {table}')
    except Exception:                              # noqa: BLE001
        pass
    from django.core.management import call_command
    call_command('createcachetable', verbosity=0)
    logger.info('أُنشئ جدول الكاش %s', table)
    return True


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
            ensure_cache_table()
        except Exception as exc:                  # noqa: BLE001
            logger.error('تعذّر إنشاء جدول الكاش: %s', exc)
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
