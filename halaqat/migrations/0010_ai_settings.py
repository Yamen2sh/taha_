# إعدادات المساعد الإحصائي: **البرومت فقط** (المفتاح/العنوان/النموذج من متغيّرات البيئة)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('halaqat', '0009_assistantquery'),
    ]

    operations = [
        migrations.CreateModel(
            name='AISettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(default='default', max_length=20, unique=True, verbose_name='الاسم')),
                ('prompt', models.TextField(blank=True, default='', verbose_name='البرومت (system prompt)')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='آخر تعديل')),
            ],
            options={
                'verbose_name': 'إعدادات الذكاء الاصطناعي',
                'verbose_name_plural': 'إعدادات الذكاء الاصطناعي',
            },
        ),
    ]
