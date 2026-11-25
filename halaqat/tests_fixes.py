"""
اختبارات الإصلاحات الأخيرة (شغّلها بـ: python manage.py test halaqat):
  • صفحات المطور والنسخ الاحتياطي والترحيل للمدير العام فقط، والإرسال إلى تلغرام بطلب POST.
  • المساعد الإحصائي لا يسقط مع أرقام ضخمة، وإعادة محاولة Gemini لا تُرسل حقل model.
  • نموذج «واتساب الغائبين» يحسب تاريخه الافتراضي عند كل عرض لا عند إقلاع الخادم.
  • كلمة مرور حساب المشاهد تمرّ على AUTH_PASSWORD_VALIDATORS.
  • استيراد Excel يقتطع الحقول الطويلة بما يوافق حدود PostgreSQL.
  • اختيار مفتاح الذكاء الاصطناعي لا يُرسل مفتاح مزوّد إلى مزوّد آخر.
"""
import datetime
import json
import os
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from halaqat import ai_query, cache_utils
from halaqat.forms import ViewerAccountForm, WhatsAppAbsentForm


class _NoWarmup:
    """يمنع خيط التحميل المسبق للكاش أثناء الاختبارات (كما في tests_security)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._orig_warm = cache_utils.warm_cache_async
        cache_utils.warm_cache_async = lambda *a, **k: False

    @classmethod
    def tearDownClass(cls):
        cache_utils.warm_cache_async = cls._orig_warm
        super().tearDownClass()


class SuperuserOnlyTests(_NoWarmup, TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser('boss', password='Str0ng-pass-12345')
        # حساب عادي: ليس «مشاهداً» وليس مديراً عاماً
        self.staff = User.objects.create_user('supervisor', password='Str0ng-pass-12345')

    def test_non_superuser_is_bounced_from_developer_page(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('developer_page'))
        self.assertRedirects(resp, reverse('home'), fetch_redirect_response=False)

    def test_non_superuser_gets_403_json_on_dangerous_posts(self):
        self.client.force_login(self.staff)
        for name in ('developer_run_migrations', 'developer_sqlite_import', 'developer_fill_defaults',
                     'developer_cache_refresh', 'send_all_data_telegram', 'migrate_sqlite_to_postgres'):
            resp = self.client.post(reverse(name))
            self.assertEqual(resp.status_code, 403, name)
            self.assertFalse(resp.json()['ok'], name)

    def test_non_superuser_cannot_download_the_backup(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('send_all_data_telegram') + '?download=1')
        self.assertRedirects(resp, reverse('home'), fetch_redirect_response=False)

    def test_telegram_send_requires_post_even_for_superuser(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('send_all_data_telegram'))
        self.assertEqual(resp.status_code, 405)
        self.assertFalse(resp.json()['ok'])

    def test_developer_link_is_shown_only_to_superuser(self):
        dev_url = reverse('developer_page')
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('help_page'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, dev_url)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('help_page')), dev_url)


class AssistantSpecRobustnessTests(SimpleTestCase):
    TODAY = datetime.date(2026, 11, 25)

    def test_huge_numbers_do_not_crash_validation(self):
        spec, _w = ai_query.validate_spec({'age_min': '1e999'}, [], self.TODAY)
        self.assertIsNone(spec['age_min'])
        spec, _w = ai_query.validate_spec({'age_max': 10 ** 400}, [], self.TODAY)
        self.assertIsNone(spec['age_max'])
        spec, _w = ai_query.validate_spec({'limit': float('inf')}, [], self.TODAY)
        self.assertEqual(spec['limit'], ai_query.DEFAULT_LIMIT)
        spec, _w = ai_query.validate_spec(
            {'conditions': [{'metric': 'absent', 'op': '>', 'value': 10 ** 400}]}, [], self.TODAY)
        self.assertEqual(spec['conditions'], [])


class _FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class _FakeHttp:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, timeout=None, headers=None, json=None):
        self.calls.append({'url': url, 'json': json})
        return self.responses.pop(0)


class GeminiRetryTests(SimpleTestCase):
    def test_retry_after_404_sends_no_model_field(self):
        args = {'subject': 'students', 'group_by': 'person'}
        ok = _FakeResponse(200, {'candidates': [{'content': {'parts': [
            {'functionCall': {'name': ai_query.TOOL_NAME, 'args': args}}]}}]})
        http = _FakeHttp(_FakeResponse(404), ok)
        spec = ai_query.ask_llm('كم غاب الطلاب؟', datetime.date(2026, 11, 25), ['حلقة'], 'KEY', 'gemini-bogus',
                                http=http, base_url='https://generativelanguage.googleapis.com/v1beta')
        self.assertEqual(spec, args)
        self.assertEqual(len(http.calls), 2)
        self.assertNotIn('model', http.calls[1]['json'])          # جسم Gemini لا يحوي model (المسار فقط)
        self.assertIn(ai_query.GEMINI_DEFAULT_MODEL, http.calls[1]['url'])


class WhatsAppFormDateTests(SimpleTestCase):
    def test_default_date_is_computed_per_render(self):
        self.assertTrue(callable(WhatsAppAbsentForm.base_fields['date'].initial))
        self.assertEqual(WhatsAppAbsentForm()['date'].initial, timezone.localdate())


class ViewerPasswordTests(TestCase):
    def _form(self, password, username='viewer1'):
        return ViewerAccountForm({'username': username, 'password': password})

    def test_weak_passwords_are_rejected(self):
        for weak in ('12345678', 'password', 'viewer12'):         # أرقام فقط / شائعة / تشبه اسم المستخدم
            form = self._form(weak)
            self.assertFalse(form.is_valid(), weak)
            self.assertIn('password', form.errors, weak)

    def test_strong_password_is_accepted(self):
        self.assertTrue(self._form('Str0ng-pass-12345').is_valid())


class ExcelImportLimitsTests(_NoWarmup, TestCase):
    def test_long_cells_are_truncated_to_model_limits(self):
        import openpyxl
        from halaqat import excel_import
        from halaqat.models import Circle, Student, Teacher

        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        def add(title, header, row):
            ws = wb.create_sheet(title)
            ws.append(header)
            ws.append(row)

        add('الأساتذة', ['م', 'اسم الأستاذ', 'رقم الهاتف', 'المعرّف'],
            [1, 'أ' * 200, '9' * 30, None])
        add('الحلقات', ['م', 'اسم الحلقة', 'الأستاذ', 'عدد الطلاب', 'الوصف', 'ترتيب العرض', 'المعرّف', 'معرّف الأستاذ'],
            [1, 'ح' * 200, 'أ' * 200, 0, 'و' * 300, 0, None, None])
        add('الطلاب', ['م', 'اسم الطالب', 'الحلقة', 'الهاتف', 'ملاحظات', 'تاريخ الانضمام', 'تاريخ الميلاد',
                       'المعرّف', 'معرّف الحلقة'],
            [1, 'ط' * 200, 'ح' * 200, '1' * 30, 'ن' * 300, None, None, None, None])

        excel_import.import_workbook(wb)

        teacher = Teacher.objects.get()                            # أستاذ واحد: المطابقة بالاسم المقتطع تعمل
        self.assertEqual((len(teacher.name), len(teacher.phone)), (150, 20))
        circle = Circle.objects.get()
        self.assertEqual((len(circle.name), len(circle.description)), (150, 255))
        self.assertEqual(circle.teacher, teacher)
        student = Student.objects.get()
        self.assertEqual((len(student.name), len(student.phone), len(student.notes)), (150, 20, 255))
        self.assertEqual(student.circle, circle)


class AIKeySelectionTests(SimpleTestCase):
    GOOGLE = 'https://generativelanguage.googleapis.com/v1beta'

    def pick(self, base_url, **env):
        from masjid_taha import settings as project_settings
        with mock.patch.dict(os.environ, env, clear=True):
            return project_settings._pick_ai_key(base_url)

    def test_foreign_keys_are_never_sent_to_google(self):
        self.assertEqual(self.pick(self.GOOGLE, OPENAI_API_KEY='sk-x', ANTHROPIC_API_KEY='sk-ant'), ('', ''))

    def test_gemini_key_is_used_for_google(self):
        self.assertEqual(self.pick(self.GOOGLE, GEMINI_API_KEY='g-1'), ('g-1', 'GEMINI_API_KEY'))

    def test_provider_keys_match_their_own_provider(self):
        env = {'ANTHROPIC_API_KEY': 'a-1', 'OPENAI_API_KEY': 'o-1'}
        self.assertEqual(self.pick('https://api.anthropic.com', **env), ('a-1', 'ANTHROPIC_API_KEY'))
        self.assertEqual(self.pick('https://api.openai.com/v1', **env), ('o-1', 'OPENAI_API_KEY'))
