"""
اختبارات الإصلاحات الأخيرة (شغّلها بـ: python manage.py test halaqat):
  • صفحات المطور والنسخ الاحتياطي والترحيل للمدير العام فقط، والإرسال إلى تلغرام بطلب POST.
  • المساعد الإحصائي لا يسقط مع أرقام ضخمة، وإعادة محاولة Gemini لا تُرسل حقل model.
  • نموذج «واتساب الغائبين» يحسب تاريخه الافتراضي عند كل عرض لا عند إقلاع الخادم.
  • كلمة مرور حساب المشاهد تمرّ على AUTH_PASSWORD_VALIDATORS.
  • استيراد Excel يقتطع الحقول الطويلة بما يوافق حدود PostgreSQL.
  • اختيار مفتاح الذكاء الاصطناعي لا يُرسل مفتاح مزوّد إلى مزوّد آخر.
  • مُدخلات الطلبات المشوّهة (معرّفات/حلقة/أعمار) ترجع 400 أو تُتجاهل بدل خطأ 500.
  • رسائل واتساب للغائبين: التحقق من النص، الهاتف «-» ناقص لا فاشل، قفل ضد التكرار، الخيط لا يموت بصمت.
  • بطاقات الحلقات تحسب الأستاذ البديل يوم الربط المؤقت، وتصدير CSV يتجاهل الموضوعين في الحاوية.
  • Gemini: النماذج القديمة تُستبدل تلقائياً عند 404، إعادة المحاولة للأعطال العابرة، ومستوى التفكير.
  • استيراد SQLite: يفهم صيغ التواريخ المختلفة، يحفظ أختام الوقت الأصلية، ويرفض القيم الإلزامية الفارغة برسالة واضحة.
"""
import datetime
import json
import os
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from halaqat import ai_query, cache_utils, sqlite_transfer, views
from halaqat.forms import ViewerAccountForm, WhatsAppAbsentForm
from halaqat.models import Attendance, Circle, Course, Student, Teacher, TeacherAttendance


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
    def __init__(self, *responses, models=()):
        self.responses = list(responses)
        self.calls = []
        self.models = list(models)

    def post(self, url, timeout=None, headers=None, json=None):
        self.calls.append({'url': url, 'json': json})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, headers=None, timeout=None):
        return _FakeResponse(200, {'models': [
            {'name': 'models/' + name, 'supportedGenerationMethods': ['generateContent']} for name in self.models]})


class GeminiRetryTests(SimpleTestCase):
    def setUp(self):
        ai_query._MODEL_OVERRIDE.clear()
        self.addCleanup(ai_query._MODEL_OVERRIDE.clear)

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


class MalformedInputTests(_NoWarmup, TestCase):
    """طلبات يدوية بمعرّفات غير رقمية: كانت تنتهي بخطأ 500."""

    def setUp(self):
        User = get_user_model()
        self.client.force_login(User.objects.create_superuser('boss', password='Str0ng-pass-12345'))
        self.today = timezone.localdate().isoformat()
        self.teacher = Teacher.objects.create(name='الشيخ أحمد')
        self.circle = Circle.objects.create(name='حلقة', teacher=self.teacher)
        self.student = Student.objects.create(name='طالب نشط', circle=self.circle)

    def test_non_numeric_ids_get_400_not_500(self):
        resp = self.client.post(reverse('save_attendance', args=[self.circle.id]),
                                {'kind': 'student', 'entity_id': 'abc', 'status': 'present', 'date': self.today})
        self.assertEqual(resp.status_code, 400)
        course = Course.objects.create(name='دورة')
        for kind in ('student', 'teacher'):
            resp = self.client.post(reverse('save_course_attendance', args=[course.id]),
                                    {'kind': kind, 'entity_id': 'abc', 'status': 'present', 'date': self.today})
            self.assertEqual(resp.status_code, 400, kind)
        resp = self.client.post(reverse('save_teacher_attendance_general'),
                                {'entity_id': 'abc', 'status': 'present', 'date': self.today})
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(reverse('teacher_link_set'), {'circle_id': 'abc'})
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(reverse('teacher_link_set'), {'circle_id': self.circle.id, 'teacher_id': 'abc'})
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(reverse('sort_students_add'), {'kind': 'student', 'name': 'x', 'circle_id': 'abc'})
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(reverse('sort_students_add'), {'kind': 'link', 'name': 'x', 'circle_id': 'abc'})
        self.assertEqual(resp.status_code, 404)

    def test_bad_circle_or_course_param_does_not_crash(self):
        for name in ('absentees_list', 'export_attendance_csv'):
            self.assertEqual(self.client.get(reverse(name) + '?circle=abc').status_code, 200, name)
        self.assertEqual(self.client.get(reverse('export_course_attendance_csv') + '?course=abc').status_code, 200)

    def test_huge_age_filter_does_not_crash_stats(self):
        resp = self.client.get(reverse('stats_page') + '?age_min=5000&age_max=9999')
        self.assertEqual(resp.status_code, 200)

    def test_new_teacher_with_a_duplicated_name_does_not_crash(self):
        Teacher.objects.create(name='الشيخ أحمد')                  # الاسم مكرر بحكم التصميم
        resp = self.client.post(reverse('teacher_link_set'),
                                {'circle_id': self.circle.id, 'new_teacher_name': 'الشيخ أحمد'})
        self.assertEqual(resp.status_code, 200)

    def test_csv_export_skips_parked_students(self):
        Student.objects.create(name='طالب موضوع', circle=self.circle, parked_at=timezone.now())
        body = self.client.get(reverse('export_attendance_csv')).content.decode('utf-8')
        self.assertIn('طالب نشط', body)
        self.assertNotIn('طالب موضوع', body)

    def test_move_returns_the_target_circle_count(self):
        other = Circle.objects.create(name='حلقة ثانية')
        Student.objects.create(name='مقيم', circle=other)
        resp = self.client.post(reverse('sort_students_move'),
                                {'student_id': self.student.id, 'circle_id': other.id})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual((data['from']['count'], data['to']['count']), (0, 2))


class TeacherByNameTests(TestCase):
    def test_duplicate_names_do_not_break_get_or_create(self):
        first = Teacher.objects.create(name='الشيخ أحمد')
        Teacher.objects.create(name='الشيخ أحمد')
        self.assertEqual(Teacher.get_or_create_by_name(' الشيخ أحمد ').id, first.id)
        self.assertEqual(Teacher.objects.filter(name='الشيخ أحمد').count(), 2)      # لم يُنشأ ثالث
        self.assertEqual(Teacher.get_or_create_by_name('أستاذ جديد').name, 'أستاذ جديد')


class CirclesOverviewSubstituteTests(_NoWarmup, TestCase):
    def test_substitute_teacher_counts_on_the_substitute_day(self):
        today = timezone.localdate()
        main = Teacher.objects.create(name='الأساسي')
        sub = Teacher.objects.create(name='البديل')
        circle = Circle.objects.create(name='حلقة', teacher=main, substitute_teacher=sub, substitute_date=today)
        student = Student.objects.create(name='طالب', circle=circle)
        Attendance.objects.create(student=student, circle=circle, date=today, status='present')
        # الأستاذ الأساسي لم يُسجَّل له شيء، والبديل سُجِّل: الحلقة مكتملة
        TeacherAttendance.objects.create(teacher=sub, circle=circle, date=today, status='present')
        cache_utils.invalidate_all()
        card = views._circles_overview()['circle_cards'][0]
        self.assertEqual(card['card_status'], 'complete')
        self.assertEqual((card['progress_recorded'], card['progress_total']), (2, 2))


class WhatsAppTemplateTests(SimpleTestCase):
    def _form(self, message):
        return WhatsAppAbsentForm({'date': '2026-11-25', 'circle': '', 'message': message})

    def test_valid_templates_pass(self):
        self.assertTrue(self._form('غاب {student_name} يوم {date}').is_valid())
        self.assertTrue(self._form('{{حرفي}} {week_absences:02d}').is_valid())

    def test_broken_templates_are_rejected_with_a_message(self):
        for bad in ('غاب {student}', 'قوس مفتوح {', '{0}'):
            form = self._form(bad)
            self.assertFalse(form.is_valid(), bad)
            self.assertIn('message', form.errors, bad)


class WhatsAppAbsentSendTests(_NoWarmup, TestCase):
    def setUp(self):
        User = get_user_model()
        self.client.force_login(User.objects.create_superuser('boss', password='Str0ng-pass-12345'))
        self.day = timezone.localdate()
        self.circle = Circle.objects.create(name='حلقة')
        self.no_phone = Student.objects.create(name='بلا رقم', circle=self.circle, phone='-')
        self.with_phone = Student.objects.create(name='برقم', circle=self.circle, phone='0501234567')
        for student in (self.no_phone, self.with_phone):
            Attendance.objects.create(student=student, circle=self.circle, date=self.day, status='absent')

    @mock.patch('halaqat.views.time.sleep')
    @mock.patch('halaqat.views.send_telegram_message')
    @mock.patch('halaqat.views.send_whatsapp_text', return_value=True)
    @mock.patch('halaqat.views.normalize_chat_id', side_effect=lambda phone: '966' + phone.lstrip('0') + '@c.us')
    def test_dash_phone_is_skipped_not_reported_as_failed(self, _norm, send_wa, send_tg, _sleep):
        views._send_whatsapp_absent_messages(self.day, None, 'غاب {student_name}')
        send_wa.assert_called_once()
        summary = send_tg.call_args[0][0]
        self.assertIn('\u274c فشل/غير مُرسل: لا يوجد', summary)
        self.assertIn('\u23ed أرقام ناقصة/غير صالحة: بلا رقم', summary)

    @mock.patch('halaqat.views.connections')
    @mock.patch('halaqat.views.send_telegram_message')
    def test_worker_entry_survives_errors_and_releases_the_lock(self, send_tg, conns):
        views._WHATSAPP_SEND_LOCK.acquire()
        try:
            with mock.patch.object(views, '_send_whatsapp_absent_messages', side_effect=RuntimeError('boom')):
                views._queue_whatsapp_absent_messages(self.day, None, 'x')       # لا يرفع الاستثناء
            self.assertTrue(views._WHATSAPP_SEND_LOCK.acquire(blocking=False))     # القفل حُرِّر
        finally:
            views._WHATSAPP_SEND_LOCK.release()
        self.assertIn('تعذّر', send_tg.call_args[0][0])
        conns.close_all.assert_called_once()

    def _post(self):
        return self.client.post(reverse('admin_panel'), {
            'submit_whatsapp_absent': '1', 'date': self.day.isoformat(), 'circle': '',
            'message': 'غاب {student_name}'})

    def test_submit_starts_exactly_one_worker(self):
        with mock.patch('halaqat.views.threading.Thread') as thread_cls:
            resp = self._post()
        try:
            self.assertRedirects(resp, reverse('admin_panel'), fetch_redirect_response=False)
            thread_cls.return_value.start.assert_called_once()
            self.assertFalse(views._WHATSAPP_SEND_LOCK.acquire(blocking=False))   # محجوز حتى ينتهي الخيط
        finally:
            views._WHATSAPP_SEND_LOCK.release()                                   # الخيط الحقيقي هو من يحرّره

    def test_second_submit_while_sending_is_refused(self):
        views._WHATSAPP_SEND_LOCK.acquire()
        try:
            with mock.patch('halaqat.views.threading.Thread') as thread_cls:
                resp = self._post()
            self.assertRedirects(resp, reverse('admin_panel'), fetch_redirect_response=False)
            thread_cls.assert_not_called()
        finally:
            views._WHATSAPP_SEND_LOCK.release()


def _ok_response(args=None):
    args = args or {'subject': 'students'}
    return _FakeResponse(200, {'candidates': [{'content': {'parts': [
        {'functionCall': {'name': ai_query.TOOL_NAME, 'args': args}}]}}]})


class GeminiResilienceTests(SimpleTestCase):
    """أوقفت Google النماذج 1.5 و2.0 وحصرت 2.5 بالمشاريع القديمة: الكود يجب أن يجد نموذجاً صالحاً بنفسه."""
    TODAY = datetime.date(2026, 11, 26)
    GOOGLE = 'https://generativelanguage.googleapis.com/v1beta'

    def setUp(self):
        ai_query._MODEL_OVERRIDE.clear()
        ai_query._NO_THINKING.clear()
        self.addCleanup(ai_query._MODEL_OVERRIDE.clear)
        self.addCleanup(ai_query._NO_THINKING.clear)
        patcher = mock.patch('halaqat.ai_query.time.sleep')            # لا انتظار حقيقي بين المحاولات
        patcher.start()
        self.addCleanup(patcher.stop)

    def ask(self, http, model='gemini-2.5-flash'):
        return ai_query.ask_llm('q', self.TODAY, ['حلقة'], 'KEY', model, http=http, base_url=self.GOOGLE)

    @staticmethod
    def model_of(call):
        return call['url'].split('/models/')[1].split(':')[0]

    def test_request_config_follows_the_model_generation(self):
        def config(model, **kw):
            return ai_query.build_request_body('q', self.TODAY, ['ح'], model, kind='gemini', **kw)['generationConfig']
        self.assertEqual(config('gemini-3.8-flash'), {'maxOutputTokens': 4096, 'thinkingConfig': {'thinkingLevel': 'low'}})
        self.assertEqual(config('gemini-flash-latest', thinking=False), {'maxOutputTokens': 4096})
        self.assertEqual(config('gemini-2.5-flash'), {'temperature': 0, 'maxOutputTokens': 1024})

    def test_unavailable_model_falls_back_through_current_models_and_is_remembered(self):
        http = _FakeHttp(_FakeResponse(404), _FakeResponse(404), _ok_response())
        self.assertEqual(self.ask(http), {'subject': 'students'})
        self.assertEqual([self.model_of(c) for c in http.calls],
                         ['gemini-2.5-flash', 'gemini-flash-latest', 'gemini-3.8-flash'])
        http2 = _FakeHttp(_ok_response())                                  # السؤال التالي لا يجرّب الميّت
        self.ask(http2)
        self.assertEqual([self.model_of(c) for c in http2.calls], ['gemini-3.8-flash'])
        self.assertEqual(ai_query.resolved_model(self.GOOGLE, 'gemini-2.5-flash'), 'gemini-3.8-flash')

    def test_models_listing_is_the_last_resort(self):
        static_404s = 1 + len([m for m in ai_query.GEMINI_FALLBACK_MODELS if m != 'gemini-2.5-flash'])
        http = _FakeHttp(*([_FakeResponse(404)] * static_404s), _ok_response(),
                         models=['gemini-3.9-flash', 'gemini-3.9-flash-image-preview'])
        self.ask(http)
        self.assertEqual(self.model_of(http.calls[-1]), 'gemini-3.9-flash')

    def test_everything_unavailable_gives_a_clear_error(self):
        with self.assertRaises(ai_query.AssistantError) as ctx:
            self.ask(_FakeHttp(*([_FakeResponse(404)] * 30)))
        self.assertEqual(ctx.exception.code, 'not_found')
        self.assertIn('gemini-flash-latest', ctx.exception.message)

    def test_transient_failures_are_retried_once(self):
        class ReadTimeout(Exception):
            pass
        self.assertEqual(self.ask(_FakeHttp(ReadTimeout('slow'), _ok_response()), 'gemini-3.8-flash'),
                         {'subject': 'students'})
        self.assertEqual(self.ask(_FakeHttp(_FakeResponse(503), _ok_response()), 'gemini-3.8-flash'),
                         {'subject': 'students'})

    def test_persistent_failures_report_the_right_reason(self):
        class ReadTimeout(Exception):
            pass
        cases = (((ReadTimeout('a'), ReadTimeout('b')), 'timeout'),
                 ((ConnectionError('a'), ConnectionError('b')), 'network'),
                 ((_FakeResponse(503), _FakeResponse(503)), 'api'))
        for responses, code in cases:
            with self.assertRaises(ai_query.AssistantError) as ctx:
                self.ask(_FakeHttp(*responses), 'gemini-3.8-flash')
            self.assertEqual(ctx.exception.code, code)

    def test_model_that_rejects_thinking_is_retried_without_it(self):
        rejected = _FakeResponse(400, {'error': {'message': 'Thinking level low is not supported for this model'}})
        http = _FakeHttp(rejected, _ok_response())
        self.assertEqual(self.ask(http, 'gemini-3.8-flash'), {'subject': 'students'})
        self.assertIn('thinkingConfig', http.calls[0]['json']['generationConfig'])
        self.assertNotIn('thinkingConfig', http.calls[1]['json']['generationConfig'])


@override_settings(TIME_ZONE='Asia/Riyadh')
class SqliteImportTests(TestCase):
    """ملف SQLite بتواريخ بصيغ مختلفة كان يُنتج date=NULL فيفشل الاستيراد بخطأ NOT NULL غامض."""

    def _make_file(self, attendance_rows):
        import sqlite3
        import tempfile
        fd, path = tempfile.mkstemp(suffix='.sqlite3')
        os.close(fd)
        self.addCleanup(os.remove, path)
        con = sqlite3.connect(path)
        con.executescript("""
            CREATE TABLE halaqat_teacher (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE halaqat_circle (id INTEGER PRIMARY KEY, name TEXT, teacher_id INTEGER);
            CREATE TABLE halaqat_student (id INTEGER PRIMARY KEY, name TEXT, circle_id INTEGER, joined_at TEXT);
            CREATE TABLE halaqat_attendance (id INTEGER PRIMARY KEY, student_id INTEGER, circle_id INTEGER,
                                             date, status TEXT, recorded_at TEXT);
        """)
        con.execute("INSERT INTO halaqat_teacher VALUES (1, 'الشيخ أحمد')")
        con.execute("INSERT INTO halaqat_circle VALUES (7, 'حلقة', 1)")
        con.execute("INSERT INTO halaqat_student VALUES (1, 'محمد', 7, '2026-01-05T10:30:00+00:00')")
        con.executemany("INSERT INTO halaqat_attendance VALUES (?, 1, 7, ?, 'present', ?)", attendance_rows)
        con.commit()
        con.close()
        return path

    def test_mixed_date_formats_import_correctly_and_original_timestamps_survive(self):
        utc = datetime.timezone.utc
        riyadh_midnight_ms = int(datetime.datetime(2026, 7, 25, 21, 0, tzinfo=utc).timestamp() * 1000)
        path = self._make_file([
            (1, riyadh_midnight_ms, '2026-07-26 08:00:00'),      # epoch بالميلي ثانية (تصدير بعض الأدوات)
            (2, '27/07/2026', '2026-07-27 08:00:00'),            # يوم/شهر/سنة
            (3, '2026-07-28 00:00:00', '2026-07-28 08:00:00'),   # تاريخ بوقت
            (4, 20260729, '2026-07-29 08:00:00'),                # YYYYMMDD
            (5, '٣٠/٠٧/٢٠٢٦', '2026-07-30 08:00:00'),            # أرقام عربية
        ])
        counts = sqlite_transfer.import_from_file(path, force=True)
        self.assertEqual(counts['halaqat_attendance'], 5)
        self.assertEqual(list(Attendance.objects.order_by('id').values_list('date', flat=True)),
                         [datetime.date(2026, 7, day) for day in (26, 27, 28, 29, 30)])
        # أختام الوقت الأصلية لا تُستبدل بوقت الاستيراد (auto_now_add / auto_now)
        self.assertEqual(Student.objects.get().joined_at, datetime.datetime(2026, 1, 5, 10, 30, tzinfo=utc))
        self.assertEqual(Attendance.objects.get(pk=1).recorded_at, datetime.datetime(2026, 7, 26, 8, 0, tzinfo=utc))

    def test_unparseable_or_missing_required_date_aborts_clearly_and_rolls_back(self):
        Teacher.objects.create(name='قديم')                       # يجب أن يبقى: المعاملة تتراجع كلها
        for bad in ('ليس تاريخاً', None):
            path = self._make_file([(1, bad, '2026-07-26 08:00:00')])
            with self.assertRaises(ValueError) as ctx:
                sqlite_transfer.import_from_file(path, force=True)
            message = str(ctx.exception)
            self.assertIn('halaqat_attendance.date', message)
            self.assertIn(repr(bad), message)
            self.assertEqual(list(Teacher.objects.values_list('name', flat=True)), ['قديم'])
            self.assertEqual(Attendance.objects.count(), 0)
