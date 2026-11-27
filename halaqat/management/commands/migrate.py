"""
نسخة مُصلَّحة من أمر ``migrate`` تتعامل تلقائياً مع الحالة الواقعية على Render:

    psycopg.errors.DuplicateTable: relation "halaqat_assistantquery" already exists

أي أن الجدول موجود في القاعدة لكن ترحيله غير مسجَّل في ``django_migrations``
(يحدث بعد استيراد SQLite، أو بناء فاشل، أو إنشاء الجداول يدوياً).

لماذا نُعيد تعريف الأمر بدل تعديل أمر البناء؟
  لأن أمر البناء عند المستخدم قد يكون:
      pip install ... && collectstatic && python manage.py migrate && createsuperuser
  فجعل ``migrate`` نفسه ذكياً يعني أن البناء ينجح **بلا أي تغيير في إعدادات Render**.

السلوك:
  • إن لم تكن هناك ترحيلات معلّقة → يُنفَّذ أمر Django الأصلي كما هو تماماً (نفس المخرجات والسلوك).
  • إن وُجدت ترحيلات وعناصرها موجودة فعلاً (جداول/أعمدة) → تُسجَّل كمطبَّقة بلا تنفيذ.
  • إن فشل ترحيل بخطأ «already exists/duplicate» → يُسجَّل ويُكمَل.
  • أي خطأ آخر يظهر كما هو (لا إخفاء للأعطال الحقيقية).
  • يُعطَّل هذا السلوك بمتغيّر البيئة ``SMART_MIGRATE=false``.
"""
from django.core.management.commands import migrate as django_migrate


class Command(django_migrate.Command):
    help = 'يطبّق الترحيلات، ويتجاوز تلقائياً ما هو موجود فعلاً في القاعدة (already exists)'

    def handle(self, *args, **options):
        import os

        from halaqat import schema_guard

        if os.environ.get('SMART_MIGRATE', 'true').lower() in ('0', 'false', 'no', 'off'):
            return super().handle(*args, **options)

        # جدول الكاش ليس ترحيلاً: إن غاب تفشل كل صفحة بـ 503 رغم سلامة المخطط.
        try:
            schema_guard.ensure_cache_table()
        except Exception:                              # noqa: BLE001
            pass

        # إصلاح تاريخ الترحيلات إن كان غير متّسق (يرفض Django التشغيل بدونه)
        try:
            fixed = schema_guard.repair_history()
        except Exception:                              # noqa: BLE001
            fixed = []
        if fixed:
            self.stdout.write(self.style.WARNING(
                f'🩹 أُصلح تاريخ الترحيلات (سُجِّل كمطبَّق): {", ".join(fixed)}'))

        pending = schema_guard.pending_migrations()
        if not pending:
            return super().handle(*args, **options)

        self.stdout.write(self.style.WARNING(
            f'ℹ️ ترحيلات معلّقة: {len(pending)} — سيتم تجاوز ما هو موجود فعلاً في القاعدة تلقائياً.'
        ))
        applied = schema_guard.apply_migrations()
        remaining = schema_guard.pending_migrations()

        if applied:
            self.stdout.write(self.style.SUCCESS(f'✅ طُبِّقت: {", ".join(applied)}'))
        skipped = sorted(set(pending) - set(applied) - set(remaining))
        if skipped:
            self.stdout.write(self.style.WARNING(
                f'↷ تُجوهز عن (عناصرها موجودة بالفعل): {", ".join(skipped)}'
            ))
        if remaining:
            self.stdout.write(self.style.ERROR(f'⚠️ ما زالت معلّقة: {", ".join(remaining)}'))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS('✅ المخطط محدَّث بالكامل.'))
        return None
