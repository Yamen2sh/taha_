from django.db import models
from django.utils import timezone


def age_from_birth_date(birth_date, on=None):
    on = on or timezone.localdate()
    return on.year - birth_date.year - ((on.month, on.day) < (birth_date.month, birth_date.day))


class Teacher(models.Model):
    """المعلم المسؤول عن حلقة أو أكثر"""
    name = models.CharField('اسم الأستاذ', max_length=150)
    phone = models.CharField('رقم الهاتف', max_length=20, blank=True)

    class Meta:
        verbose_name = 'أستاذ'
        verbose_name_plural = 'الأساتذة'
        ordering = ['name']

    def __str__(self):
        return self.name


class Circle(models.Model):
    """حلقة قرآنية"""
    name = models.CharField('اسم الحلقة', max_length=150)
    teacher = models.ForeignKey(
        Teacher, verbose_name='الأستاذ المسؤول',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='circles',
    )
    description = models.CharField('وصف مختصر', max_length=255, blank=True)
    display_order = models.PositiveIntegerField('ترتيب العرض', default=0, help_text='كلما كان الرقم أصغر ظهرت الحلقة أولاً في قائمة الحلقات.')
    # ربط مؤقت: أستاذ آخر يتولى الحلقة في يوم محدد فقط، ثم ترجع الحلقة لأستاذها الأساسي تلقائياً.
    substitute_teacher = models.ForeignKey(
        Teacher, verbose_name='أستاذ بديل (يوم الربط فقط)',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='substitute_circles',
    )
    substitute_date = models.DateField('يوم الربط المؤقت', null=True, blank=True)
    created_at = models.DateTimeField('تاريخ الإنشاء', auto_now_add=True)

    class Meta:
        verbose_name = 'حلقة'
        verbose_name_plural = 'الحلقات'
        ordering = ['display_order', 'name', 'id']

    def __str__(self):
        return self.name

    @property
    def student_count(self):
        return self.students.filter(parked_at__isnull=True).count()

    def teacher_on(self, date):
        """
        الأستاذ المسؤول في يوم محدد: البديل إن كان يوم الربط المؤقت مطابقاً،
        وإلا الأستاذ الأساسي. (الربط المؤقت انتهى بمجرد اختلاف اليوم.)
        """
        if self.substitute_teacher_id and self.substitute_date and date and self.substitute_date == date:
            return self.substitute_teacher
        return self.teacher

    def is_substituted_on(self, date):
        return bool(self.substitute_teacher_id and self.substitute_date and date and self.substitute_date == date)

    def attendance_rate(self, days=30):
        """نسبة الحضور خلال آخر عدد أيام محدد (احتساب: (حاضر+تأخر) / (حاضر+تأخر+غائب))"""
        since = timezone.now().date() - timezone.timedelta(days=days)
        qs = Attendance.objects.filter(circle=self, date__gte=since)
        total = qs.exclude(status='excused').count()
        if total == 0:
            return None
        present = qs.filter(status__in=['present', 'late']).count()
        return round((present / total) * 100)

    def attendance_progress(self, date):
        """هل تم تسجيل حضور الجميع (كل الطلاب + الأستاذ) في هذا التاريخ؟ يُستخدم لتلوين كرت الحلقة."""
        total = self.student_count
        recorded = Attendance.objects.filter(circle=self, date=date).count()
        if self.teacher:
            total += 1
            if TeacherAttendance.objects.filter(teacher=self.teacher, circle=self, date=date).exists():
                recorded += 1
        return {'total': total, 'recorded': recorded, 'complete': total > 0 and recorded >= total}


class Student(models.Model):
    """طالب داخل حلقة"""
    name = models.CharField('اسم الطالب', max_length=150)
    phone = models.CharField('رقم الهاتف', max_length=20, blank=True)
    circle = models.ForeignKey(
        Circle, verbose_name='الحلقة',
        on_delete=models.CASCADE, related_name='students',
    )
    notes = models.CharField('ملاحظات', max_length=255, blank=True)
    birth_date = models.DateField('تاريخ الميلاد', null=True, blank=True,
                                  help_text='يُستخدم لحساب العمر وفرز الطلاب في الإحصائيات.')
    # الحاوية المؤقتة في لوحة الفرز: الطالب يبقى في حلقته في قاعدة البيانات لكنه يُخفى
    # من صفحات الحضور/التسميع حتى يُسحب إلى حلقة أخرى (parked_at = وقت الوضع).
    parked_at = models.DateTimeField('موضوع في الحاوية المؤقتة', null=True, blank=True)
    joined_at = models.DateTimeField('تاريخ الانضمام', auto_now_add=True)
    updated_at = models.DateTimeField('آخر تعديل', auto_now=True, null=True)

    class Meta:
        verbose_name = 'طالب'
        verbose_name_plural = 'الطلاب'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def age(self):
        """العمر بالسنوات الكاملة (None إن لم يُحدَّد تاريخ الميلاد)."""
        if not self.birth_date:
            return None
        return age_from_birth_date(self.birth_date)

    @property
    def is_parked(self):
        """هل الطالب موضوع مؤقتاً في الحاوية الفارغة بلوحة الفرز؟"""
        return self.parked_at is not None

    @property
    def birth_year(self):
        return self.birth_date.year if self.birth_date else None

    def last_recitation(self):
        return self.recitations.order_by('-date', '-id').first()

    @property
    def last_recited_page(self):
        """رقم آخر صفحة سمّعها الطالب (None إن لم يسمّع بعد) — يظهر كوسم جانب اسمه."""
        last = self.last_recitation()
        if not last:
            return None
        from .quran import page_of
        try:
            return last.to_page or page_of(last.to_surah, last.to_ayah)
        except Exception:
            return None

    @property
    def last_recited_on(self):
        last = self.last_recitation()
        return last.date if last else None

    def attendance_rate(self, days=90):
        since = timezone.now().date() - timezone.timedelta(days=days)
        qs = Attendance.objects.filter(student=self, date__gte=since)
        total = qs.exclude(status='excused').count()
        if total == 0:
            return None
        present = qs.filter(status__in=['present', 'late']).count()
        return round((present / total) * 100)

    def absence_count(self, days, before_date=None):
        """عدد أيام الغياب خلال آخر (days) يوماً، محسوبة قبل تاريخ محدد (افتراضياً اليوم)."""
        before_date = before_date or timezone.now().date()
        since = before_date - timezone.timedelta(days=days - 1)
        return Attendance.objects.filter(
            student=self, status='absent', date__gte=since, date__lte=before_date,
        ).count()


class Attendance(models.Model):
    """سجل حضور يومي لطالب في حلقة - سجل تاريخي بالتاريخ"""

    STATUS_CHOICES = [
        ('present', 'حاضر'),
        ('late', 'تأخر'),
        ('excused', 'إذن'),
        ('absent', 'غائب'),
    ]

    student = models.ForeignKey(
        Student, verbose_name='الطالب',
        on_delete=models.CASCADE, related_name='attendance_records',
    )
    circle = models.ForeignKey(
        Circle, verbose_name='الحلقة',
        on_delete=models.CASCADE, related_name='attendance_records',
    )
    date = models.DateField('التاريخ', default=timezone.now)
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='present')
    recorded_at = models.DateTimeField('وقت التسجيل', auto_now=True)

    class Meta:
        verbose_name = 'سجل حضور'
        verbose_name_plural = 'سجلات الحضور'
        # طالب واحد لا يمكن أن يملك أكثر من سجل حضور في نفس اليوم
        unique_together = [('student', 'date')]
        ordering = ['-date']

    def __str__(self):
        return f'{self.student.name} - {self.date} - {self.get_status_display()}'


class TeacherAttendance(models.Model):
    """سجل حضور يومي للأستاذ المسؤول عن حلقة - بنفس منطق حضور الطلاب"""

    STATUS_CHOICES = Attendance.STATUS_CHOICES

    teacher = models.ForeignKey(
        Teacher, verbose_name='الأستاذ',
        on_delete=models.CASCADE, related_name='attendance_records',
    )
    circle = models.ForeignKey(
        Circle, verbose_name='الحلقة',
        on_delete=models.CASCADE, related_name='teacher_attendance_records',
    )
    date = models.DateField('التاريخ', default=timezone.now)
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='present')
    recorded_at = models.DateTimeField('وقت التسجيل', auto_now=True)

    class Meta:
        verbose_name = 'حضور أستاذ'
        verbose_name_plural = 'حضور الأساتذة'
        # الأستاذ لا يمكن أن يملك أكثر من سجل حضور لنفس الحلقة في نفس اليوم
        unique_together = [('teacher', 'circle', 'date')]
        ordering = ['-date']

    def __str__(self):
        return f'{self.teacher.name} - {self.circle.name} - {self.date} - {self.get_status_display()}'


class Course(models.Model):
    """دورة أو درس إضافي لفئة محددة من الطلاب (مستقل عن الحلقات الأساسية). يمكن أن يكون للدورة أكثر من أستاذ."""
    name = models.CharField('اسم الدورة / الدرس', max_length=150)
    teachers = models.ManyToManyField(
        Teacher, verbose_name='الأساتذة / المحاضرون المسؤولون',
        related_name='courses', blank=True,
    )
    description = models.CharField('وصف مختصر', max_length=255, blank=True)
    students = models.ManyToManyField(
        Student, verbose_name='الطلاب المشاركون',
        related_name='courses', blank=True,
    )
    created_at = models.DateTimeField('تاريخ الإنشاء', auto_now_add=True)

    class Meta:
        verbose_name = 'دورة / درس إضافي'
        verbose_name_plural = 'الدورات والدروس الإضافية'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def student_count(self):
        return self.students.count()

    def attendance_rate(self, days=30):
        since = timezone.now().date() - timezone.timedelta(days=days)
        qs = CourseAttendance.objects.filter(course=self, date__gte=since)
        total = qs.exclude(status='excused').count()
        if total == 0:
            return None
        present = qs.filter(status__in=['present', 'late']).count()
        return round((present / total) * 100)

    def attendance_progress(self, date):
        """هل تم تسجيل حضور جميع المشاركين (+الأساتذة إن وُجدوا) في هذا التاريخ؟"""
        total = self.student_count
        recorded = CourseAttendance.objects.filter(course=self, date=date).count()
        teacher_count = self.teachers.count()
        total += teacher_count
        if teacher_count:
            recorded += CourseTeacherAttendance.objects.filter(
                course=self, date=date, teacher__in=self.teachers.all()
            ).count()
        return {'total': total, 'recorded': recorded, 'complete': total > 0 and recorded >= total}


class CourseAttendance(models.Model):
    """سجل حضور يومي لطالب مشارك في دورة/درس إضافي - مستقل عن حضور الحلقة الأساسية"""

    STATUS_CHOICES = Attendance.STATUS_CHOICES

    student = models.ForeignKey(
        Student, verbose_name='الطالب',
        on_delete=models.CASCADE, related_name='course_attendance_records',
    )
    course = models.ForeignKey(
        Course, verbose_name='الدورة / الدرس',
        on_delete=models.CASCADE, related_name='attendance_records',
    )
    date = models.DateField('التاريخ', default=timezone.now)
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='present')
    recorded_at = models.DateTimeField('وقت التسجيل', auto_now=True)

    class Meta:
        verbose_name = 'حضور دورة'
        verbose_name_plural = 'سجلات حضور الدورات'
        unique_together = [('student', 'course', 'date')]
        ordering = ['-date']

    def __str__(self):
        return f'{self.student.name} - {self.course.name} - {self.date} - {self.get_status_display()}'


class CourseTeacherAttendance(models.Model):
    """سجل حضور يومي لأستاذ/محاضر دورة أو درس إضافي"""

    STATUS_CHOICES = Attendance.STATUS_CHOICES

    teacher = models.ForeignKey(
        Teacher, verbose_name='الأستاذ',
        on_delete=models.CASCADE, related_name='course_attendance_records',
    )
    course = models.ForeignKey(
        Course, verbose_name='الدورة / الدرس',
        on_delete=models.CASCADE, related_name='teacher_attendance_records',
    )
    date = models.DateField('التاريخ', default=timezone.now)
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='present')
    recorded_at = models.DateTimeField('وقت التسجيل', auto_now=True)

    class Meta:
        verbose_name = 'حضور أستاذ دورة'
        verbose_name_plural = 'حضور أساتذة الدورات'
        unique_together = [('teacher', 'course', 'date')]
        ordering = ['-date']

    def __str__(self):
        return f'{self.teacher.name} - {self.course.name} - {self.date} - {self.get_status_display()}'

class TeacherDailyAttendance(models.Model):
    """
    تفقّد عام يومي للأستاذ، مستقل عن أي حلقة أو دورة محددة.
    يُستخدم في صفحة "الأساتذة" لتسجيل حضور من لم يُؤخذ له تفقد ضمن حلقة/دورة اليوم
    (خصوصاً الأساتذة غير المرتبطين بأي حلقة).
    """

    STATUS_CHOICES = Attendance.STATUS_CHOICES

    teacher = models.ForeignKey(
        Teacher, verbose_name='الأستاذ',
        on_delete=models.CASCADE, related_name='general_attendance_records',
    )
    date = models.DateField('التاريخ', default=timezone.now)
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='present')
    recorded_at = models.DateTimeField('وقت التسجيل', auto_now=True)

    class Meta:
        verbose_name = 'تفقد عام لأستاذ'
        verbose_name_plural = 'التفقد العام للأساتذة'
        unique_together = [('teacher', 'date')]
        ordering = ['-date']

    def __str__(self):
        return f'{self.teacher.name} - {self.date} - {self.get_status_display()}'


class Sabr(models.Model):
    """سبر (اختبار) يجريه الطالب — يُسجَّل بتاريخ اليوم افتراضياً ويمكن تغيير التاريخ."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='sabrs', verbose_name='الطالب')
    date = models.DateField('تاريخ السبر', default=timezone.localdate)
    notes = models.TextField('تفاصيل السبر والملاحظات', blank=True, default='')
    created_at = models.DateTimeField('وقت التسجيل', auto_now_add=True)

    class Meta:
        verbose_name = 'سبر'
        verbose_name_plural = 'السبر'
        ordering = ['-date', '-id']

    def __str__(self):
        return f'{self.student.name} — {self.date}'


class Recitation(models.Model):
    """
    تسميع: ما سمّعه الطالب من القرآن الكريم بتاريخ محدد.

    طريقتان:
      • pages — «بالصفحات»: من صفحة … إلى صفحة (افتراضياً صفحة واحدة)، ويُشتق منها نطاق الآيات.
      • surah — «بأسماء السور» (آخر جزأين: الملك ← الناس): يُختار اسم السورة ثم صفحة/صفحات منها.
    تُحفظ الحلقة وقت التسميع، فلا يتغيّر سجل التسميع القديم إن انتقل الطالب لحلقة أخرى.
    """

    KIND_CHOICES = [
        ('new', 'حفظ جديد'),
        ('review', 'مراجعة'),
    ]
    GRADE_CHOICES = [
        ('excellent', 'ممتاز'),
        ('very_good', 'جيد جداً'),
        ('good', 'جيد'),
        ('acceptable', 'مقبول'),
        ('repeat', 'يحتاج إعادة'),
    ]
    MODE_CHOICES = [
        ('pages', 'بالصفحات'),
        ('surah', 'بأسماء السور'),
    ]

    student = models.ForeignKey(
        Student, verbose_name='الطالب',
        on_delete=models.CASCADE, related_name='recitations',
    )
    circle = models.ForeignKey(
        Circle, verbose_name='الحلقة',
        on_delete=models.CASCADE, related_name='recitations',
    )
    date = models.DateField('تاريخ التسميع', default=timezone.localdate)
    kind = models.CharField('النوع', max_length=10, choices=KIND_CHOICES, default='new')
    mode = models.CharField('طريقة التسميع', max_length=6, choices=MODE_CHOICES, default='pages')
    from_page = models.PositiveSmallIntegerField('من صفحة', null=True, blank=True)
    to_page = models.PositiveSmallIntegerField('إلى صفحة', null=True, blank=True)
    surah = models.PositiveSmallIntegerField('السورة (وضع السور)', null=True, blank=True)
    # نطاق الآيات — يُشتق تلقائياً من الصفحات، ويبقى محفوظاً للسجلات القديمة والتصدير
    from_surah = models.PositiveSmallIntegerField('من سورة', null=True, blank=True)
    from_ayah = models.PositiveSmallIntegerField('من آية', null=True, blank=True)
    to_surah = models.PositiveSmallIntegerField('إلى سورة', null=True, blank=True)
    to_ayah = models.PositiveSmallIntegerField('إلى آية', null=True, blank=True)
    grade = models.CharField('التقدير', max_length=12, choices=GRADE_CHOICES, blank=True, default='')
    notes = models.CharField('ملاحظات', max_length=255, blank=True, default='')
    created_at = models.DateTimeField('وقت التسجيل', auto_now_add=True)

    class Meta:
        verbose_name = 'تسميع'
        verbose_name_plural = 'التسميع'
        ordering = ['-date', '-id']

    def __str__(self):
        return f'{self.student.name} — {self.range_display} — {self.date}'

    # ── اشتقاق نطاق الآيات من الصفحات ──────────────────────────
    def apply_pages(self):
        """يحوّل صفحة البداية/النهاية إلى (سورة، آية) حتى تبقى سجلات الآيات متوافقة."""
        from .quran import page_start, page_end, validate_range
        if not (self.from_page and self.to_page):
            return
        fs, fa = page_start(self.from_page)
        ts, ta = page_end(self.to_page)
        if validate_range(fs, fa, ts, ta):
            return
        self.from_surah, self.from_ayah, self.to_surah, self.to_ayah = fs, fa, ts, ta

    def save(self, *args, **kwargs):
        if self.from_page and not self.to_page:
            self.to_page = self.from_page
        if self.from_page and self.to_page:
            if self.to_page < self.from_page:
                self.from_page, self.to_page = self.to_page, self.from_page
            self.apply_pages()
        super().save(*args, **kwargs)

    # ── العرض ──────────────────────────────────────────────────
    @property
    def page_span(self):
        if self.from_page and self.to_page:
            return self.to_page - self.from_page + 1
        return 0

    @property
    def surah_name(self):
        from .quran import SURAH_NAME
        n = self.surah or self.from_surah
        return SURAH_NAME.get(n, '')

    @property
    def notes_display(self):
        """الملاحظات للعرض بعد إخفاء بصمة منع التكرار [uid:…]."""
        import re
        return re.sub(r'^\[uid:[^\]]*\]\s*', '', self.notes or '')

    @property
    def range_display(self):
        """نص مقروء للمقطع: «صفحة 5» / «صفحة 5–7» / «الملك: الأولى والثانية»."""
        from .quran import page_range_display, surah_pages_display
        if self.mode == 'surah' and self.surah and self.from_page:
            return surah_pages_display(self.surah, self.from_page, self.to_page or self.from_page)
        if self.from_page and self.to_page:
            return page_range_display(self.from_page, self.to_page)
        from .quran import format_range
        return format_range(self.from_surah, self.from_ayah, self.to_surah, self.to_ayah)

    @property
    def ayah_count(self):
        from .quran import safe_ayah_span
        return safe_ayah_span(self.from_surah, self.from_ayah, self.to_surah, self.to_ayah)

    @property
    def last_page(self):
        """رقم آخر صفحة في هذا التسميع (يُستخدم لوسم «آخر صفحة مسمّعة»)."""
        if self.to_page:
            return self.to_page
        from .quran import page_of
        try:
            return page_of(self.to_surah, self.to_ayah)
        except Exception:
            return None
