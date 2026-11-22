import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('halaqat', '0006_normalize_sqlite_dates'),
    ]

    operations = [
        migrations.CreateModel(
            name='Recitation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(default=django.utils.timezone.localdate, verbose_name='تاريخ التسميع')),
                ('kind', models.CharField(choices=[('new', 'حفظ جديد'), ('review', 'مراجعة')], default='new', max_length=10, verbose_name='النوع')),
                ('from_surah', models.PositiveSmallIntegerField(verbose_name='من سورة')),
                ('from_ayah', models.PositiveSmallIntegerField(verbose_name='من آية')),
                ('to_surah', models.PositiveSmallIntegerField(verbose_name='إلى سورة')),
                ('to_ayah', models.PositiveSmallIntegerField(verbose_name='إلى آية')),
                ('grade', models.CharField(blank=True, choices=[('excellent', 'ممتاز'), ('very_good', 'جيد جداً'), ('good', 'جيد'), ('acceptable', 'مقبول'), ('repeat', 'يحتاج إعادة')], default='', max_length=12, verbose_name='التقدير')),
                ('notes', models.CharField(blank=True, default='', max_length=255, verbose_name='ملاحظات')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='وقت التسجيل')),
                ('circle', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='recitations', to='halaqat.circle', verbose_name='الحلقة')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='recitations', to='halaqat.student', verbose_name='الطالب')),
            ],
            options={
                'verbose_name': 'تسميع',
                'verbose_name_plural': 'التسميع',
                'ordering': ['-date', '-id'],
            },
        ),
    ]
