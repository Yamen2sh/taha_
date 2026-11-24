"""
إبطال الكاش تلقائياً عند أي إضافة/تعديل/حذف (انظر cache_utils.py).

  • بيانات مرجعية (أساتذة، حلقات، طلاب، دورات) ⇒ تُبطَل المرجعية والإحصائيات معاً.
  • سجلات الحضور والسبر ⇒ تُبطَل الإحصائيات فقط (عملية في الذاكرة بلا أي استعلام، فلا تُبطئ الحفظ).
العمليات الجماعية التي لا ترسل signals (bulk_create / update) تستدعي cache_utils.invalidate_all() صراحةً.
"""
from django.db.models.signals import m2m_changed, post_delete, post_save

from . import cache_utils
from .models import (
    Teacher, Circle, Student, Attendance, TeacherAttendance,
    Course, CourseAttendance, CourseTeacherAttendance, TeacherDailyAttendance, Sabr, Recitation,
)

_REFERENCE_MODELS = (Teacher, Circle, Student, Course)
_ATTENDANCE_MODELS = (Attendance, TeacherAttendance, CourseAttendance,
                      CourseTeacherAttendance, TeacherDailyAttendance, Sabr)


def _on_reference_change(sender, **kwargs):
    cache_utils.invalidate_reference()
    cache_utils.invalidate_stats()


def _on_attendance_change(sender, **kwargs):
    cache_utils.invalidate_stats()


for _m in _REFERENCE_MODELS:
    post_save.connect(_on_reference_change, sender=_m, dispatch_uid=f'taha-ref-save-{_m.__name__}')
    post_delete.connect(_on_reference_change, sender=_m, dispatch_uid=f'taha-ref-del-{_m.__name__}')

for _m in _ATTENDANCE_MODELS:
    post_save.connect(_on_attendance_change, sender=_m, dispatch_uid=f'taha-att-save-{_m.__name__}')
    post_delete.connect(_on_attendance_change, sender=_m, dispatch_uid=f'taha-att-del-{_m.__name__}')

# التسميع: يؤثر على «آخر صفحة مسمّعة» في البحث المحلي ولوحة الفرز، وعلى الإحصائيات
def _on_recitation_change(sender, **kwargs):
    cache_utils.invalidate_reference()
    cache_utils.invalidate_stats()

post_save.connect(_on_recitation_change, sender=Recitation, dispatch_uid='taha-rec-save')
post_delete.connect(_on_recitation_change, sender=Recitation, dispatch_uid='taha-rec-del')

for _through in (Course.students.through, Course.teachers.through):
    m2m_changed.connect(_on_reference_change, sender=_through, dispatch_uid=f'taha-m2m-{_through.__name__}')
