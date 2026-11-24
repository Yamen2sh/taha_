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
            'format': 'taha-sqlite-backup', 'version': '1',
            'source': connection.vendor,
            'exported_at': __import__('django.utils.timezone', fromlist=['timezone']).localtime().isoformat(),
        }
        cur.executemany('INSERT INTO "_meta" (key, value) VALUES (?, ?)', list(meta.items()))
        conn.commit()
    finally:
        conn.close()
    return counts


def read_meta(path):
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


def _coerce(value, field):
    """يحوّل قيمة من SQLite إلى نوع الحقل المطلوب في قاعدة البيانات الحالية."""
    if value is None:
        return None
    kind = field.get_internal_type()
    from datetime import date, datetime
    if kind in ('DateField',):
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    if kind in ('DateTimeField',):
        from django.utils.dateparse import parse_datetime
        from django.utils import timezone as tz
        if isinstance(value, datetime):
            return value
        dt = parse_datetime(str(value))
        if dt is None:
            try:
                dt = datetime.fromisoformat(str(value))
            except ValueError:
                return None
        if dt.tzinfo is None:
            dt = tz.make_aware(dt)
        return dt
    if kind == 'BooleanField':
        return bool(value)
    if isinstance(value, str) and kind not in ('CharField', 'TextField', 'EmailField', 'SlugField'):
        return value
    return value


def import_from_file(path, keep_ai_settings=True):
    """
    يستورد ملف SQLite **باستبدال كامل** لكل البيانات (ذرّياً في معاملة واحدة).
    يعيد {اسم الجدول: عدد الصفوف المستوردة}. يرفع ValueError برسالة عربية عند فشل التحقق.
    """
    meta, tables = read_meta(path)
    if meta.get('format') != 'taha-sqlite-backup':
        raise ValueError('هذا الملف ليس نسخة SQLite صادرة عن النظام (جدول _meta مفقود أو غير مطابق).')

    sql = sqlite3.connect(path)
    sql.row_factory = sqlite3.Row
    counts = {}
    try:
        cur = sql.cursor()
        # نُعطّل فحص القيود أثناء الاستيراد (خارج المعاملة في SQLite)، ثم يُفحص الجميع عند التسجيل
        with connection.constraint_checks_disabled(), transaction.atomic():
            # 1) إفراغ الجداول (ترتيب عكسي احتراماً للمفاتيح الأجنبية)
            for model in reversed(_ordered_models()):
                for f in model._meta.many_to_many:
                    f.remote_field.through.objects.all().delete()
                model.objects.all().delete()

            # 2) إدخال الصفوف بمفاتيحها الأصلية ثم ضبط التسلسل (ترتيب أب ← ابن)
            for model in _ordered_models():
                table = model._meta.db_table
                fields = _concrete_fields(model)
                cols = [f.column for f in fields]
                try:
                    rows = cur.execute(f'SELECT {", ".join(chr(34)+c+chr(34) for c in cols)} FROM "{table}"').fetchall()
                except sqlite3.Error:
                    continue                          # الجدول غير موجود في الملف (نموذج أحدث/أقدم)
                objs, pks = [], []
                for row in rows:
                    kwargs = {}
                    for f in fields:
                        if f.primary_key:
                            pks.append(row[f.column])
                            continue
                        if isinstance(f, ForeignKey):
                            kwargs[f.attname] = row[f.column]
                        else:
                            kwargs[f.attname] = _coerce(row[f.column], f)
                    obj = model(**kwargs)
                    if pks and len(pks) == len(objs) + 1:
                        obj.pk = pks[-1]
                    objs.append(obj)
                if objs:
                    model.objects.bulk_create(objs, batch_size=500, ignore_conflicts=False)
                counts[table] = len(objs)

            # 3) العلاقات many-to-many
            for model in _ordered_models():
                for f in model._meta.many_to_many:
                    through = f.remote_field.through
                    tcols = [x.column for x in through._meta.concrete_fields]
                    try:
                        rows = cur.execute(f'SELECT {", ".join(chr(34)+c+chr(34) for c in tcols)} FROM "{through._meta.db_table}"').fetchall()
                    except sqlite3.Error:
                        continue
                    links = [through(**{x.attname: row[x.column] for x in through._meta.concrete_fields}) for row in rows]
                    if links:
                        through.objects.bulk_create(links, batch_size=1000)
                    counts[through._meta.db_table] = len(links)

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
                cur.execute(f"SELECT setval(%s, COALESCE((SELECT MAX({pk}) FROM \"{table}\"), 1), "
                            f"(SELECT COUNT(*) > 0 FROM \"{table}\"))", [seq])
            except Exception:
                pass


def temp_backup_path(suffix='sqlite'):
    """مسار مؤقت لملف النسخة (يُحذف بعد الإرسال/التنزيل)."""
    fd, path = tempfile.mkstemp(prefix='taha_', suffix='.' + suffix)
    os.close(fd)
    os.remove(path)
    return path
