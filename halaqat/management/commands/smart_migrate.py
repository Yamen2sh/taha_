"""
python manage.py smart_migrate

ترحيل ذكي يتجاوز الحالة الواقعية التي تُفشل ``migrate`` العادي:

    relation "halaqat_assistantquery" already exists

أي أن الجدول موجود في القاعدة لكن الترحيل غير مسجَّل في ``django_migrations``
(حدث ذلك عند استيراد SQLite، أو بناء فاشل، أو جدول أُنشئ يدوياً).

السلوك:
  • يُنفِّذ الترحيلات بالترتيب.
  • إن كانت كل عمليات الترحيل إنشاءات وجميع عناصرها (جداول/أعمدة) موجودة →
    يُسجَّل كمطبَّق بلا تنفيذ.
  • إن فشل التنفيذ بخطأ «موجود بالفعل» → يُسجَّل ويُكمَل.
  • أي خطأ آخر يوقف العملية ويُظهره كما هو (لا إخفاء للأعطال الحقيقية).

بعد الانتهاء يعرض ملخصاً وحالة المخطط.
"""
from django.core.management.base import BaseCommand

from halaqat import schema_guard


class Command(BaseCommand):
    help = 'يطبّق الترحيلات المعلّقة ويتجاوز الترحيلات التي عناصرها موجودة فعلاً'

    def add_arguments(self, parser):
        parser.add_argument('--quiet', action='store_true', help='أقل تفصيلاً')

    def handle(self, *args, **options):
        before = schema_guard.pending_migrations()
        if not options['quiet']:
            self.stdout.write(self.style.WARNING(
                f'ترحيلات معلّقة قبل البدء: {len(before)}' + (f" → {', '.join(before)}" if before else '')
            ))

        applied = schema_guard.apply_migrations()
        after = schema_guard.pending_migrations()

        if applied:
            self.stdout.write(self.style.SUCCESS(f'✅ طُبِّقت: {", ".join(applied)}'))
        skipped = sorted(set(before) - set(applied) - set(after))
        if skipped:
            self.stdout.write(self.style.WARNING(
                f'↷ تُجوهز عن (عناصرها موجودة بالفعل): {", ".join(skipped)}'
            ))

        if after:
            self.stdout.write(self.style.ERROR(f'⚠️ ما زالت معلّقة: {", ".join(after)}'))
            self.stdout.write('   راجع الخطأ أعلاه، أو نفّذ: python manage.py migrate')
        else:
            self.stdout.write(self.style.SUCCESS('✅ المخطط محدَّث بالكامل — لا ترحيلات معلّقة.'))

        status = schema_guard.schema_status()
        if status['missing_tables']:
            self.stdout.write(self.style.ERROR(f"⛔ جداول مفقودة: {', '.join(status['missing_tables'])}"))
        else:
            self.stdout.write('الجداول الأساسية: ' + ' · '.join(f'✅ {n}' for n in status['tables']))
