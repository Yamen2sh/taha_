"""
نقل كامل للبيانات من وإلى ملف SQLite واحد — من «المطور ← 🗄 SQLite».

الفكرة: أي قاعدة بيانات يدعمها المشروع (SQLite محلياً أو PostgreSQL على Render)
تُنسخ كل جداول تطبيق ``halaqat`` + الحضور/الدورات/التسميع/الإعدادات إلى ملف SQLite،
ثم يمكن استيراد الملف في أي نسخة أخرى **باستبدال كامل**.

المعمارية تبقى متوافقة:
  • تُستخدم نماذج Django نفسها (introspection) فلا يوجد تعريف جداول مكرَّر.
  • تُحفظ المفاتيح الأساسية كما هي، ثم تُضبط تسلسلات PostgreSQL (`setval`) لتجنّب التعارض.
  • كل الاستيراد داخل معاملة واحدة (atomic) — ينجح كاملاً أو يتراجع كاملاً.
  • الإعدادات (AISettings) لا تُستبدل عند الاستيراد حتى لا يضيع مفتاح الـ API المضبوط.
"""
import os
import sqlite3
import tempfile

from django.apps import apps
from django.db import connection, connections, transaction
from django.db.models import ForeignKey, ManyToManyField

EXPORTED_MODELS = ('halaqat.Teacher', 'halaqat.Circle', 'halaqat.Student', 'halaqat.Attendance',
                   'halaqat.TeacherAttendance', 'halaqat.Course', 'halaqat.CourseAttendance',
                   'halaqat.CourseTeacherAttendance', 'halaqat.TeacherDailyAttendance',
                   'halaqat.Sabr', 'halaqat.Recitation', 'halaqat.AssistantQuery')
# عند الاستيراد: تُستبدل هذه الجداول، وتبقى AISettings (مفتاح الـ API) كما هي
REPLACED_MODELS = EXPORTED_MODELS
KEPT_MODELS = ('halaqat.AISettings',)


def _models():
    return [apps.get_model(name) for name in EXPORTED_MODELS]


def _ordered_models():
    """
    ترتيب النماذج بحيث تُدخَل الجداول الأب قبل الابن (احترام المفاتيح الأجنبية).
    الفرز الطوبولوجي بسيط: يُقدَّم أي نموذج يعتمد على غيره.
    """
    models = _models()
    by_label = {m._meta.label: m for m in models}
    ordered, visiting = [], set()

    def visit(m):
        if m._meta.label in ordered_labels:
            return
        if m._meta.label in visiting:            # دورة (لا توجد عملياً) → تجاهل
            return
        visiting.add(m._meta.label)
        for f in m._meta.concrete_fields:
            if isinstance(f, ForeignKey) and getattr(f.remote_field, 'model', None) is not None:
                dep = f.remote_field.model
                if dep in by_label.values() and dep is not m:
                    visit(dep)
        visiting.discard(m._meta.label)
        ordered_labels.add(m._meta.label)
        ordered.append(m)

    ordered_labels = set()
    for m in models:
        visit(m)
    return ordered


def _concrete_fields(model):
    """
    كل الحقول الفعلية بما فيها المفتاح الأساسي التلقائي (id) — نستثني فقط
    «مؤشرات الوراثة» (parent link) التي لا جدول لها.
    """
    return [f for f in model._meta.concrete_fields if not (f.auto_created and f.is_relation)]


def export_to_file(path):
    """
    يصدّر **كل** بيانات التطبيق إلى ملف SQLite جديد (يُنشأ/يُستبدل).
    يعيد {اسم الجدول: عدد الصفوف}.
    """
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    counts = {}
    try:
        cur = conn.cursor()
        # 1) الجداول
        for model in _ordered_models():
            cols = []
            for f in _concrete_fields(model):
                cols.append(f'{f.column} {"INTEGER" if f.get_internal_type() in ("AutoField", "BigAutoField", "IntegerField", "PositiveIntegerField", "PositiveSmallIntegerField", "SmallIntegerField", "ForeignKey", "BooleanField") else "TEXT"}')
            cur.execute(f'CREATE TABLE "{model._meta.db_table}" ({", ".join(cols)})')
        cur.execute('CREATE TABLE "_meta" (key TEXT PRIMARY KEY, value TEXT)')
        # 2) البيانات (بمفاتيحها الأصلية)
        for model in _ordered_models():
            table = model._meta.db_table
            cols = [f.column for f in _concrete_fields(model)]
            placeholders = ', '.join('?' * len(cols))
            col_sql = ', '.join(f'"{c}"' for c in cols)
            batch = []
            total = 0
            for row in model.objects.order_by().iterator(chunk_size=1000):
                vals = []
                for f in _concrete_fields(model):
                    if isinstance(f, ForeignKey):
                        vals.append(getattr(row, f.attname))
                    else:
                        v = getattr(row, f.attname)
                        if hasattr(v, 'isoformat'):
                            vals.append(v.isoformat())
                        elif isinstance(v, bool):
                            vals.append(int(v))
                        else:
                            vals.append(v)
                batch.append(vals)
                total += 1
                if len(batch) >= 500:
                    cur.executemany(f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})', batch)
                    batch = []
            if batch:
                cur.executemany(f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})', batch)
            counts[table] = total
        # 3) علاقات many-to-many (طلاب الدورات وأساتذتها)
        for model in _ordered_models():
            for f in model._meta.many_to_many:
                through = f.remote_field.through
                ttable = through._meta.db_table
                tcols = [x.column for x in through._meta.concrete_fields]
                cur.execute(f'CREATE TABLE "{ttable}" ({", ".join(c + " INTEGER" for c in tcols)})')
                rows = through.objects.order_by().values_list(*[x.attname for x in through._meta.concrete_fields])
                batch = [list(r) for r in rows]
                if batch:
                    ph = ', '.join('?' * len(tcols))
                    cur.executemany(f'INSERT INTO "{ttable}" ({", ".join(chr(34)+c+chr(34) for c in tcols)}) VALUES ({ph})', batch)
                counts[ttable] = len(batch)
        # 4) بيانات وصفية
        meta = {
            'format': 'taha-sqlite-backup', 'version': '2',
            'source': connection.vendor,
            'exported_at': __import__('django.utils.timezone', fromlist=['timezone']).localtime().isoformat(),
        }
        cur.executemany('INSERT INTO "_meta" (key, value) VALUES (?, ?)', list(meta.items()))
        conn.commit()
    finally:
        conn.close()
    return counts


def read_meta(path):
    """
    يقرأ جدول ``_meta`` إن وُجد (ملف صادر عن النظام) وقائمة الجداول.
    **أي ملف SQLite صالح مقبول** — وجود ``_meta`` اختياري.
    """
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        try:
            rows = dict(cur.execute('SELECT key, value FROM "_meta"').fetchall())
        except sqlite3.Error:
            rows = {}
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        return rows, tables
    finally:
        conn.close()


_ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def _epoch_to_datetime(num):
    """ثوانٍ أو ميلي ثوانٍ منذ 1970 ← datetime بتوقيت المشروع (الرياض)، أو None إن لم يبدُ طابعاً زمنياً."""
    from datetime import datetime, timezone as dtz
    from django.utils import timezone as tz
    if 1e12 <= abs(num) < 1e14:                # ميلي ثانية (13 رقماً)
        num = num / 1000.0
    if not 1e8 <= num < 1e11:                  # ثوانٍ (9–10 أرقام)
        return None
    try:
        return tz.localtime(datetime.fromtimestamp(num, dtz.utc))
    except (OverflowError, OSError, ValueError):
        return None


def _number_to_date(num):
    """تواريخ مخزَّنة كأرقام في أدوات أخرى: YYYYMMDD أو رقم Excel أو Julian أو epoch (ثوانٍ/ميلي)."""
    import math
    from datetime import date, timedelta
    if num != num or num in (float('inf'), float('-inf')):
        return None
    try:
        if 19000101 <= num <= 21001231 and float(num).is_integer():
            text = str(int(num))
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        if 25569 <= num <= 73050:              # رقم Excel التسلسلي (1970–2099)
            return date(1899, 12, 30) + timedelta(days=int(num))
        if 2415021 <= num <= 2488070:          # يوم Julian (1900–2100)
            return date(1970, 1, 1) + timedelta(days=math.floor(num - 2440587.5))
    except (ValueError, OverflowError):
        return None
    moment = _epoch_to_datetime(num)
    return moment.date() if moment else None


def _to_date(value):
    """
    يفهم تواريخ ملفات SQLite القادمة من أدوات مختلفة: نص ISO أو 26/07/2026 أو 2026/7/26 (بأرقام عربية أيضاً)،
    وأرقام (epoch/Excel/Julian/YYYYMMDD). يعيد date أو None إن لم يفهم القيمة.
    """
    import re
    from datetime import date, datetime
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode('utf-8', 'ignore')
    if isinstance(value, (int, float)):
        return _number_to_date(value)
    text = str(value).strip().translate(_ARABIC_DIGITS)
    if not text:
        return None
    if re.fullmatch(r'-?\d+(\.\d+)?', text):
        return _number_to_date(float(text))
    if re.search(r'[T ]\d{1,2}:\d{2}.*(Z|[+-]\d{2}:?\d{2})$', text):       # طابع زمني بمنطقة زمنية: التاريخ المحلي
        moment = _to_datetime(text)
        if moment is not None:
            from django.utils import timezone as tz
            return tz.localtime(moment).date()
    try:
        found = re.match(r'^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)', text)      # 2026-07-26 | 2026/7/26 (+ وقت)
        if found:
            return date(int(found[1]), int(found[2]), int(found[3]))
        found = re.match(r'^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?!\d)', text)      # 26/07/2026 (اليوم أولاً)
        if found:
            first, second, year = int(found[1]), int(found[2]), int(found[3])
            day, month = (first, second) if second <= 12 else (second, first)     # إن كان الثاني > 12 فهو اليوم
            return date(year, month, day)
    except ValueError:
        return None
    return None


def _to_datetime(value):
    """طابع زمني من أي صيغة شائعة (ISO، أرقام epoch، أو تاريخ فقط). غير المصرَّح بمنطقته يُعدّ UTC (كما يخزّنه Django في SQLite)."""
    import re
    from datetime import datetime, time, timezone as dtz
    from django.utils import timezone as tz
    from django.utils.dateparse import parse_datetime
    if value is None or isinstance(value, bool):
        return None
    moment = None
    if isinstance(value, datetime):
        moment = value
    else:
        if isinstance(value, (bytes, bytearray, memoryview)):
            value = bytes(value).decode('utf-8', 'ignore')
        if isinstance(value, (int, float)) or re.fullmatch(r'-?\d+(\.\d+)?', str(value).strip().translate(_ARABIC_DIGITS)):
            num = float(value) if isinstance(value, (int, float)) else float(str(value).strip().translate(_ARABIC_DIGITS))
            moment = _epoch_to_datetime(num)
            if moment is None:
                day = _number_to_date(num)
                moment = datetime.combine(day, time.min) if day else None
        else:
            text = str(value).strip().translate(_ARABIC_DIGITS)
            for parser in (parse_datetime, datetime.fromisoformat):
                try:
                    moment = parser(text)
                except ValueError:
                    moment = None
                if moment is not None:
                    break
            if moment is None:
                day = _to_date(text)
                moment = datetime.combine(day, time.min) if day else None
    if moment is None:
        return None
    if tz.is_naive(moment):
        moment = moment.replace(tzinfo=dtz.utc)
    return moment


def _coerce(value, field):
    """يحوّل قيمة من SQLite إلى نوع الحقل المطلوب في قاعدة البيانات الحالية."""
    if value is None:
        return None
    kind = field.get_internal_type()
    if kind == 'DateField':
        return _to_date(value)
    if kind == 'DateTimeField':
        return _to_datetime(value)
    if kind == 'BooleanField':
        if isinstance(value, str):
            return value.strip().lower() in ('1', 'true', 't', 'yes', 'y', 'نعم')
        return bool(value)
    return value


def _fill_required(field, raw):
    """
    قيمة بديلة آمنة لحقل إلزامي جاء فارغاً: (القيمة، نجح؟).
    نص/رقم/منطقي ← قيمته الافتراضية، وأختام الوقت التلقائية ← الآن.
    التواريخ والمفاتيح الأجنبية والحقول ذات الخيارات (كحالة الحضور) لا تُخترع أبداً:
    تُعدّ مشكلة ويتوقف الاستيراد برسالة واضحة بدل إدخال بيانات خاطئة.
    """
    kind = field.get_internal_type()
    if isinstance(field, ForeignKey) or field.choices or kind == 'DateField':
        return None, False
    if kind == 'DateTimeField':
        if getattr(field, 'auto_now', False) or getattr(field, 'auto_now_add', False):
            from django.utils import timezone
            return timezone.now(), True
        return None, False
    if field.has_default():
        default = field.get_default()
        return default, default is not None
    if kind in ('CharField', 'TextField', 'EmailField', 'SlugField'):
        return '', True
    if kind.endswith('IntegerField'):
        return 0, True
    if kind == 'BooleanField':
        return False, True
    return None, False


def _problems_message(problems):
    """رسالة عربية واضحة بالأعمدة الإلزامية الفارغة/غير المفهومة مع أمثلة من الملف (القيمة الأصلية تُظهر الصيغة)."""
    grouped = {}
    for table, pk, column, raw in problems:
        grouped.setdefault((table, column), []).append((pk, raw))
    parts = []
    for (table, column), items in list(grouped.items())[:6]:
        sample = '، '.join(f'id={pk} ← {raw!r}' for pk, raw in items[:3])
        parts.append(f'«{table}.{column}»: {len(items)} صفاً (مثال: {sample})')
    return ('لم يُستورد شيء: الملف يحوي قيماً فارغة أو بصيغة غير مفهومة في أعمدة إلزامية — ' + ' | '.join(parts)
            + '. صحّح هذه القيم في الملف (التواريخ بصيغة YYYY-MM-DD مثل 2026-07-26) ثم أعد الاستيراد.')


def _file_tables(path):
    """أسماء الجداول الموجودة فعلاً في ملف SQLite (مع أعمدتها)."""
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        names = [r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        cols = {}
        for name in names:
            cols[name] = {r[1] for r in cur.execute(f'PRAGMA table_info("{name}")').fetchall()}
        return {n: cols[n] for n in names}
    finally:
        conn.close()


def cascade_impact(to_import, limit=2000):
    """
    يحسب بأمان ما سينحذف **بالتبعية** (CASCADE) من جداول **ليست في الملف**
    عند استبدال الجداول الموجودة في الملف.

    (Django لا يحذف بالتبعية على مستوى SQL هنا، بل يجمع التابعين في Python —
     لذلك نستعمل Collector على عيّنة من كائنات الجداول المستبدلة.)
    يعيد {اسم الجدول: عدد الصفوف} للجداول المتأثرة غير الموجودة في الملف.
    """
    from django.db.models.deletion import Collector

    models = [m for m in _ordered_models() if m._meta.db_table in to_import]
    affected = {}
    for model in models:
        qs = model.objects.all()[:limit]
        objs = list(qs)
        if not objs:
            continue
        collector = Collector(using='default')
        try:
            collector.collect(objs)
        except Exception:                          # noqa: BLE001
            continue
        for obj, related in collector.data.items():
            rel_table = obj._meta.db_table
            if rel_table in to_import:
                continue                           # سيُستبدل أصلاً
            n = len(related)
            if n:
                affected[rel_table] = max(affected.get(rel_table, 0), n)
    return affected


def import_from_file(path, keep_ai_settings=True, force=False):
    """
    يستورد ملف SQLite **باستبدال** لكل جدول موجود فيه (ذرّياً في معاملة واحدة).

    قواعد مهمة (بناءً على طلب المستخدم):
      • **أي ملف SQLite صالح مقبول** — لا يشترط وجود جدول ``_meta`` ولا كامل الجداول.
      • الجداول **الغير موجودة في الملف تُترك كما هي** في القاعدة — لا تُحذف ولا تُفرَّغ.
      • الجداول الموجودة في الملف تُستبدل تماماً بمحتواها (حتى لو كانت فارغة).
      • الأعمدة الناقصة في الملف تُترك بقيمها الافتراضية.
      • إعدادات الذكاء الاصطناعي (البرومت) لا تُمسّ عند الاستيراد.
    يعيد {اسم الجدول: عدد الصفوف المستوردة}.
    """
    file_tables = _file_tables(path)
    if not file_tables:
        raise ValueError('الملف لا يحوي أي جدول — تأكّد أنه ملف SQLite صالح.')

    models = _ordered_models()
    if keep_ai_settings:
        models = [m for m in models if m._meta.label not in KEPT_MODELS]
    target_tables = {m._meta.db_table for m in models}

    # أي جدول في الملف يعرف النظام جدوله؟ (نقبل أيضاً جداول m2m)
    m2m_tables = set()
    for m in models:
        for f in m._meta.many_to_many:
            m2m_tables.add(f.remote_field.through._meta.db_table)
    known = target_tables | m2m_tables
    to_import = [t for t in file_tables if t in known]
    if not to_import:
        raise ValueError('لا يوجد في ملفك أي جدول معروف للنظام '
                         f'(الجداول في الملف: {", ".join(sorted(file_tables)[:8])}…) — '
                         f'الجداول المتوقّعة مثل: {", ".join(sorted(target_tables)[:6])}.')

    # حماية من الحذف بالتبعية للجداول غير الموجودة في الملف
    collateral = cascade_impact(set(to_import))
    if collateral and not force:
        detail = '، '.join(f'{t} ({n} صفاً)' for t, n in sorted(collateral.items()))
        raise ValueError(
            f'تحذير: استبدال الجداول الموجودة في ملفك سيحذف بالتبعية بيانات في جداول '
            f'غير موجودة في الملف: {detail}. '
            f'لتجنّب ذلك أضِف هذه الجداول إلى الملف، أو أعد المحاولة مع خيار «الاستمرار رغم ذلك».'
        )

    sql = sqlite3.connect(path)
    sql.row_factory = sqlite3.Row
    counts = {}
    try:
        cur = sql.cursor()
        with connection.constraint_checks_disabled(), transaction.atomic():
            # 1) إفراغ **الجداول التي سنستوردها فقط** (عكسي احتراماً للمفاتيح الأجنبية)
            for model in reversed(models):
                table = model._meta.db_table
                for f in model._meta.many_to_many:
                    through = f.remote_field.through
                    if through._meta.db_table in to_import:
                        through.objects.all().delete()
                if table in to_import:
                    model.objects.all().delete()

            # 2) إدخال الصفوف بمفاتيحها الأصلية (ترتيب أب ← ابن)
            for model in models:
                table = model._meta.db_table
                if table not in to_import:
                    continue                          # الجدول غير موجود بالملف → يُترك كما هو
                fields = _concrete_fields(model)
                file_cols = file_tables[table]
                usable = [f for f in fields if f.column in file_cols]
                if not usable:
                    counts[table] = 0
                    continue
                cols = [f.column for f in usable]
                rows = cur.execute(
                    f'SELECT {", ".join(chr(34)+c+chr(34) for c in cols)} FROM "{table}"'
                ).fetchall()
                objs = []
                pk_field = next((f for f in usable if f.primary_key), None)
                # حقول auto_now / auto_now_add تُغلب القيمة المُمرَّرة عند bulk_create (فتضيع تواريخ الانضمام والتسجيل الأصلية)
                auto_fields = [f for f in usable if getattr(f, 'auto_now', False) or getattr(f, 'auto_now_add', False)]
                originals = []                       # (الكائن، {حقل: قيمته في الملف}) لاستعادتها بعد الإدراج
                problems = []                        # (جدول، id، عمود، القيمة الأصلية)
                for row in rows:
                    kwargs = {}
                    for f in usable:
                        if f.primary_key:
                            continue
                        raw = row[f.column]
                        value = raw if isinstance(f, ForeignKey) else _coerce(raw, f)
                        if value is None and not f.null:
                            value, filled = _fill_required(f, raw)
                            if not filled:
                                problems.append((table, row[pk_field.column] if pk_field is not None else None,
                                                 f.column, raw))
                        kwargs[f.attname] = value
                    obj = model(**kwargs)
                    if pk_field is not None:
                        obj.pk = row[pk_field.column]
                    objs.append(obj)
                    if auto_fields:
                        keep = {f.attname: kwargs[f.attname] for f in auto_fields
                                if row[f.column] is not None and kwargs.get(f.attname) is not None}
                        if keep:
                            originals.append((obj, keep))
                if problems:                         # داخل المعاملة: الاستثناء يُرجع كل شيء (لا يُستورد نصف الملف)
                    raise ValueError(_problems_message(problems))
                if objs:
                    model.objects.bulk_create(objs, batch_size=500)
                    if originals:
                        for obj, keep in originals:
                            for attname, value in keep.items():
                                setattr(obj, attname, value)
                        model.objects.bulk_update([obj for obj, _keep in originals],
                                                  [f.name for f in auto_fields], batch_size=500)
                counts[table] = len(objs)

            # 3) العلاقات many-to-many (للجداول الموجودة فقط)
            for model in models:
                for f in model._meta.many_to_many:
                    through = f.remote_field.through
                    ttable = through._meta.db_table
                    if ttable not in to_import:
                        continue
                    file_cols = file_tables[ttable]
                    usable = [x for x in through._meta.concrete_fields if x.column in file_cols]
                    if not usable:
                        counts[ttable] = 0
                        continue
                    rows = cur.execute(
                        f'SELECT {", ".join(chr(34)+c+chr(34) for c in (x.column for x in usable))} '
                        f'FROM "{ttable}"'
                    ).fetchall()
                    links = [through(**{x.attname: row[x.column] for x in usable}) for row in rows]
                    if links:
                        through.objects.bulk_create(links, batch_size=1000)
                    counts[ttable] = len(links)

            # 4) ضبط تسلسلات PostgreSQL (وإلا تتعارض المفاتيح الجديدة)
            _reset_sequences()
    finally:
        sql.close()
    return counts


def _reset_sequences():
    """يضبط تسلسل المفاتيح لكل جدول بعد الاستيراد (PostgreSQL فقط؛ SQLite يستنتج تلقائياً)."""
    if connection.vendor != 'postgresql':
        return
    with connection.cursor() as cur:
        for model in _ordered_models():
            table = model._meta.db_table
            pk = model._meta.pk.column
            seq = f'{table}_{pk}_seq'
            try:
                # نقطة حفظ: فشل جدول واحد لا يُفسد معاملة الاستيراد (وإلا يتحوّل COMMIT إلى ROLLBACK بصمت)
                with transaction.atomic():
                    cur.execute(f"SELECT setval(%s, COALESCE((SELECT MAX({pk}) FROM \"{table}\"), 1), "
                                f"(SELECT COUNT(*) > 0 FROM \"{table}\"))", [seq])
            except Exception:
                import logging
                logging.getLogger(__name__).warning('تعذّر ضبط تسلسل %s', seq, exc_info=True)


def temp_backup_path(suffix='sqlite'):
    """مسار مؤقت لملف النسخة (يُحذف بعد الإرسال/التنزيل)."""
    fd, path = tempfile.mkstemp(prefix='taha_', suffix='.' + suffix)
    os.close(fd)
    os.remove(path)
    return path
