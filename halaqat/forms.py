from django import forms
from django.utils import timezone
from .models import Teacher, Circle, Student, Course


class TeacherForm(forms.ModelForm):
    class Meta:
        model = Teacher
        fields = ['name', 'phone']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'اسم الأستاذ الجديد'}),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف (اختياري)'}),
        }


class CircleForm(forms.ModelForm):
    # حقل اختياري لإضافة أستاذ جديد مباشرة من نفس النموذج
    new_teacher_name = forms.CharField(
        label='أو أضف أستاذاً جديداً',
        max_length=150, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'اسم الأستاذ الجديد (اختياري)'})
    )

    class Meta:
        model = Circle
        fields = ['name', 'teacher', 'description', 'display_order']
        labels = {
            'name': 'اسم الحلقة',
            'teacher': 'الأستاذ المسؤول',
            'description': 'وصف مختصر',
            'display_order': 'ترتيب العرض',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'مثال: حلقة الأنعام'}),
            'description': forms.TextInput(attrs={'placeholder': 'وصف مختصر (اختياري)'}),
            'display_order': forms.NumberInput(attrs={'min': '0', 'step': '1', 'placeholder': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['teacher'].required = False
        self.fields['teacher'].empty_label = 'اختر أستاذاً موجوداً'

    def save(self, commit=True):
        new_name = self.cleaned_data.get('new_teacher_name')
        if new_name:
            teacher = Teacher.get_or_create_by_name(new_name)     # الاسم غير فريد: لا نستعمل get_or_create
            self.instance.teacher = teacher
        return super().save(commit=commit)


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = ['name', 'circle', 'birth_date', 'phone', 'notes']
        labels = {
            'name': 'اسم الطالب',
            'circle': 'الحلقة',
            'birth_date': 'تاريخ الميلاد',
            'phone': 'رقم الهاتف',
            'notes': 'ملاحظات',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'الاسم الكامل'}),
            'birth_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف (اختياري)'}),
            'notes': forms.TextInput(attrs={'placeholder': 'رقم ولي الأمر، ملاحظات... (اختياري)'}),
        }


class WhatsAppAbsentForm(forms.Form):
    date = forms.DateField(
        label='تاريخ الغياب',
        initial=timezone.localdate,          # دالة: تُحسب عند كل عرض (لا عند إقلاع الخادم)
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    circle = forms.ModelChoiceField(
        queryset=Circle.objects.none(),
        required=False,
        label='الحلقة (اختياري)',
        empty_label='كل الحلقات'
    )
    message = forms.CharField(
        label='نص الرسالة',
        widget=forms.Textarea(attrs={
            'rows': 6,
            'placeholder': 'مثال: السلام عليكم ورحمة الله وبركاته\nحياكم الله\n🔴 لأخذ العلم قد تغيب ابنكم {student_name} عن المسجد اليوم {date}.\n👈🏻 يرجى منكم تبرير الغياب في المرات القادمة قبل الغياب\n    ولكم جزيل الشكر🌷\n\nإدارة المسجد',
        }),
        initial='🍀 السلام عليكم ورحمة الله وبركاته\n      حياكم الله\n🔴 لأخذ العلم قد تغيب ابنكم {student_name} عن المسجد اليوم {date}.\n👈🏻 يرجى منكم تبرير الغياب في المرات\n      القادمة قبل الغياب\n      ولكم جزيل الشكر🌷\n\nإدارة المسجد',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['circle'].queryset = Circle.objects.all()

    # المتغيّرات التي تمرّرها لوحة التحكم إلى str.format عند الإرسال
    PLACEHOLDERS = ('student_name', 'circle_name', 'date', 'week_absences', 'month_absences')

    def clean_message(self):
        """يتحقق من نص الرسالة قبل الإرسال: خطأ في الأقواس كان يُسقط خيط الإرسال بصمت بعد رسالة «بدأ الإرسال»."""
        text = self.cleaned_data['message']
        try:
            text.format(student_name='x', circle_name='x', date='2000-01-01', week_absences=0, month_absences=0)
        except (KeyError, IndexError, ValueError, AttributeError):
            raise forms.ValidationError(
                'نص الرسالة يحوي أقواساً { } غير صحيحة. المتغيّرات المسموحة فقط: '
                + ' '.join('{%s}' % name for name in self.PLACEHOLDERS)
                + ' — ولكتابة قوس حرفي استعمل {{ أو }}.')
        return text


class StudentMultipleChoiceField(forms.ModelMultipleChoiceField):
    """يعرض اسم الطالب مع اسم حلقته لتسهيل الاختيار من قائمة طويلة"""
    def label_from_instance(self, obj):
        return f'{obj.name} — {obj.circle.name}'


class CourseForm(forms.ModelForm):
    # حقل اختياري لإضافة أستاذ/محاضر جديد مباشرة من نفس النموذج
    new_teacher_name = forms.CharField(
        label='أو أضف أستاذاً/محاضراً جديداً',
        max_length=150, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'اسم الأستاذ الجديد (اختياري)'})
    )
    teachers = forms.ModelMultipleChoiceField(
        queryset=Teacher.objects.order_by('name'),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label='الأساتذة / المحاضرون المسؤولون',
    )
    students = StudentMultipleChoiceField(
        queryset=Student.objects.select_related('circle').order_by('circle__name', 'name'),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label='الطلاب المشاركون',
    )

    class Meta:
        model = Course
        fields = ['name', 'teachers', 'description', 'students']
        labels = {
            'name': 'اسم الدورة / الدرس',
            'teachers': 'الأساتذة / المحاضرون المسؤولون',
            'description': 'وصف مختصر',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'مثال: دورة تحسين التلاوة'}),
            'description': forms.TextInput(attrs={'placeholder': 'وصف مختصر (اختياري)'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['teachers'].required = False

    def save(self, commit=True):
        new_name = self.cleaned_data.get('new_teacher_name')
        course = super().save(commit=commit)
        if new_name:
            teacher = Teacher.get_or_create_by_name(new_name)
            course.teachers.add(teacher)
        return course


class ViewerAccountForm(forms.Form):
    """إنشاء حساب «مشاهد» يرى الإحصائيات والسبر فقط."""
    username = forms.CharField(label='اسم المستخدم', max_length=150,
                               widget=forms.TextInput(attrs={'placeholder': 'مثال: mushrif1', 'autocomplete': 'off'}))
    password = forms.CharField(label='كلمة المرور', min_length=8,
                               widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    def clean_username(self):
        from django.contrib.auth import get_user_model
        name = self.cleaned_data['username'].strip()
        if get_user_model().objects.filter(username=name).exists():
            raise forms.ValidationError('اسم المستخدم مستخدم مسبقاً.')
        return name

    def clean(self):
        """يطبّق AUTH_PASSWORD_VALIDATORS (الطول، الشائعة، الأرقام فقط، التشابه مع الاسم)."""
        cleaned = super().clean()
        password = cleaned.get('password')
        if password:
            from django.contrib.auth import get_user_model, password_validation
            user = get_user_model()(username=cleaned.get('username') or '')
            try:
                password_validation.validate_password(password, user=user)
            except forms.ValidationError as exc:
                self.add_error('password', exc)
        return cleaned
