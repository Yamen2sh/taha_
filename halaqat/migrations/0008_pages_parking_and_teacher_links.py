"""
ترحيل 0008:
  • التسميع بالصفحات: mode / from_page / to_page / surah (+ يعبّئ الصفحات للسجلات القديمة).
  • الحاوية الفارغة في لوحة الفرز: Student.parked_at.
  • الربط المؤقت: Circle.substitute_teacher / substitute_date.
"""
from django.db import migrations, models
import django.db.models.deletion


def fill_pages(apps, schema_editor):
    """يملأ from_page/to_page للسجلات القديمة من نطاق الآيات المحفوظ ويصنّفها «بالصفحات»."""
    from halaqat import quran
    Recitation = apps.get_model('halaqat', 'Recitation')
    batch = []
    for r in Recitation.objects.all().only('id', 'from_surah', 'from_ayah', 'to_surah', 'to_ayah', 'mode'):
        try:
            r.from_page = quran.page_of(r.from_surah, r.from_ayah)
            r.to_page = quran.page_of(r.to_surah, r.to_ayah)
            r.mode = 'pages'
        except Exception:
            continue
        batch.append(r)
        if len(batch) >= 500:
            Recitation.objects.bulk_update(batch, ['from_page', 'to_page', 'mode'])
            batch = []
    if batch:
        Recitation.objects.bulk_update(batch, ['from_page', 'to_page', 'mode'])


class Migration(migrations.Migration):

    dependencies = [
        ('halaqat', '0007_recitation'),
    ]

    operations = [
        migrations.AddField(
            model_name='student',
            name='parked_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='موضوع في الحاوية المؤقتة'),
        ),
        migrations.AddField(
            model_name='circle',
            name='substitute_teacher',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='substitute_circles', to='halaqat.teacher',
                                    verbose_name='أستاذ بديل (يوم الربط فقط)'),
        ),
        migrations.AddField(
            model_name='circle',
            name='substitute_date',
            field=models.DateField(blank=True, null=True, verbose_name='يوم الربط المؤقت'),
        ),
        migrations.AddField(
            model_name='recitation',
            name='mode',
            field=models.CharField(choices=[('pages', 'بالصفحات'), ('surah', 'بأسماء السور')],
                                   default='pages', max_length=6, verbose_name='طريقة التسميع'),
        ),
        migrations.AddField(
            model_name='recitation',
            name='from_page',
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='من صفحة'),
        ),
        migrations.AddField(
            model_name='recitation',
            name='to_page',
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='إلى صفحة'),
        ),
        migrations.AddField(
            model_name='recitation',
            name='surah',
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='السورة (وضع السور)'),
        ),
        migrations.AlterField(
            model_name='recitation',
            name='from_surah',
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='من سورة'),
        ),
        migrations.AlterField(
            model_name='recitation',
            name='from_ayah',
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='من آية'),
        ),
        migrations.AlterField(
            model_name='recitation',
            name='to_surah',
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='إلى سورة'),
        ),
        migrations.AlterField(
            model_name='recitation',
            name='to_ayah',
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='إلى آية'),
        ),
        migrations.RunPython(fill_pages, migrations.RunPython.noop),
    ]
