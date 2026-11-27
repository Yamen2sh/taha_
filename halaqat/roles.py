"""
أنواع الحسابات:
  - الحساب الإداري (superuser/staff أو أي مستخدم ليس ضمن مجموعة المشاهدين): صلاحيات كاملة.
  - حساب «مشاهد»: يرى صفحة الإحصائيات وصفحة السبر فقط (قراءة فقط، بلا تسجيل/تعديل/حذف).
"""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import resolve, Resolver404

VIEWER_GROUP = 'مشاهد'

# أسماء المسارات المسموح بها لحساب المشاهد
VIEWER_ALLOWED_URLS = {
    'login', 'logout',
    'stats_page', 'export_stats_pdf',
    'sabr_page', 'sabr_student_info', 'sabr_add', 'sabr_update',   # المشاهد يضيف ويعدّل السبر (بدون حذف)
    'help_page',
    'students_index',                    # قائمة الأسماء للبحث المحلي
    'student_profile', 'student_quick_stats',   # الضغط على اسم الطالب من الإحصائيات/السبر
}


def is_viewer(user):
    if not user.is_authenticated or user.is_superuser:
        return False
    cache = getattr(user, '_is_viewer_cache', None)
    if cache is None:
        cache = user.groups.filter(name=VIEWER_GROUP).exists()
        user._is_viewer_cache = cache
    return cache


def superuser_required(view_func):
    """
    يقصر الصفحة على المدير العام (superuser): صفحة المطور، النسخ الاحتياطي، الاستيراد والترحيل.
    غير المسجَّل ⇒ صفحة الدخول. مسجَّل لكنه ليس مديراً عاماً ⇒ رفض:
    JSON 403 للطلبات غير GET أو AJAX، وإلا عودة للرئيسية برسالة.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        text = 'هذه الصفحة للمدير العام فقط'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.method != 'GET':
            return JsonResponse({'ok': False, 'msg': text, 'error': text}, status=403)
        messages.error(request, text + '.')
        return redirect('home')
    return login_required(_wrapped)


class ViewerAccessMiddleware:
    """يحصر حساب المشاهد في الصفحات المسموح بها فقط."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and is_viewer(user):
            try:
                name = resolve(request.path_info).url_name
            except Resolver404:
                name = None
            if name not in VIEWER_ALLOWED_URLS:
                is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                if is_ajax or request.method != 'GET':
                    return JsonResponse({'ok': False, 'error': 'هذا الحساب للعرض فقط'}, status=403)
                return redirect('stats_page')
        return self.get_response(request)


# عناصر التنقّل: (اسم المسار، المفتاح active_nav، الأيقونة، النص)
_NAV_MAIN = [
    ('home', 'home', '🏠', 'الرئيسية'),
    ('courses_list', 'courses', '🎓', 'الدورات'),
    ('absentees_list', 'absentees', '🚫', 'الغائبون'),
    ('sabr_page', 'sabr', '📝', 'السبر'),
    ('recitation_page', 'recitation', '🎙', 'الدورات القرآنية'),
]
_NAV_MORE = [
    ('teachers_list', 'teachers', '👨‍🏫', 'الأساتذة'),
    ('stats_page', 'stats', '📊', 'الإحصائيات'),
    ('admin_panel', 'admin', '⚙️', 'لوحة التحكم'),
    ('developer_page', 'developer', '🛠', 'المطور'),
    ('help_page', 'help', '❓', 'كيفية الاستخدام'),
]
_NAV_VIEWER_MAIN = [
    ('stats_page', 'stats', '📊', 'الإحصائيات'),
    ('sabr_page', 'sabr', '📝', 'السبر'),
]
_NAV_VIEWER_MORE = [
    ('help_page', 'help', '❓', 'كيفية الاستخدام'),
]


def _nav(items):
    from django.urls import reverse
    return [{'url': reverse(n), 'key': k, 'icon': i, 'label': l} for n, k, i, l in items]


def schema_context(request):
    """
    تنبيه عام لأي مستخدم إداري: إن كانت هناك ترحيلات غير مطبَّقة (أو جدول مفقود)
    يظهر شريط تحذير في أعلى كل صفحة مع رابط مباشر لصفحة المطور.
    النتيجة مُخزَّنة في الكاش 60 ثانية حتى لا يُسأل محرّك الترحيلات في كل طلب.
    """
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated):
        return {}
    from django.core.cache import caches
    cache = caches['memory']      # ذاكرة العملية: بلا استعلام قاعدة بيانات في كل صفحة (الافتراضي DatabaseCache)
    data = cache.get('schema_alert')
    if data is None:
        try:
            from . import schema_guard
            status = schema_guard.schema_status()
            data = {'count': status['pending_count'], 'missing': status['missing_tables']}
        except Exception:                      # noqa: BLE001 — لا نُعطّل أي صفحة بسبب التنبيه
            data = {'count': 0, 'missing': []}
        cache.set('schema_alert', data, 60)
    return {'schema_alert': data}


def roles_context(request):
    user = getattr(request, 'user', None)
    viewer = bool(user and is_viewer(user))
    if not (user and user.is_authenticated):
        return {'is_viewer': False}
    is_super = bool(user.is_superuser)
    # صفحة المطور للمدير العام فقط: لا يظهر رابطها لغيره
    more = _NAV_VIEWER_MORE if viewer else [i for i in _NAV_MORE if is_super or i[0] != 'developer_page']
    return {
        'is_viewer': viewer,
        'is_superuser': is_super,
        'nav_main': _nav(_NAV_VIEWER_MAIN if viewer else _NAV_MAIN),
        'nav_more': _nav(more),
    }
