from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_safe

from .forms import AssignmentForm, ClassForm, GroupForm, JoinForm
from .models import Enrollment, StudyGroup, TeachingClass, User, Work


@login_required
@require_safe
def class_list(request):
    if request.user.role == User.Role.TEACHER:
        classes = TeachingClass.objects.filter(teacher=request.user)
    elif request.user.role == User.Role.STUDENT:
        classes = TeachingClass.objects.filter(enrollment__student=request.user)
    else:
        raise PermissionDenied
    return render(request, "classroom/list.html", {"classes": classes.order_by("course", "name")})


@login_required
@require_http_methods(["GET", "POST"])
def create_class(request):
    if request.user.role != User.Role.TEACHER:
        raise PermissionDenied
    form = ClassForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                teaching_class = form.save(commit=False)
                teaching_class.teacher = request.user
                teaching_class.save()
        except IntegrityError:
            if not TeachingClass.objects.filter(**form.cleaned_data).exists():
                raise
            form.add_error(None, "此课程、学期和班级标识已存在。")
        else:
            return redirect("class-detail", class_id=teaching_class.pk)
    return render(request, "classroom/form.html", {"title": "创建教学班", "form": form})


@login_required
@require_http_methods(["GET", "POST"])
def join_class(request):
    if request.user.role != User.Role.STUDENT:
        raise PermissionDenied
    form = JoinForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        teaching_class = TeachingClass.objects.filter(
            invite_code=form.cleaned_data["code"].lower()
        ).first()
        if teaching_class is None:
            form.add_error("code", "邀请码无效。")
        else:
            Enrollment.objects.get_or_create(teaching_class=teaching_class, student=request.user)
            return redirect("class-detail", class_id=teaching_class.pk)
    return render(request, "classroom/form.html", {"title": "加入教学班", "form": form})


def teacher_class(user, class_id):
    if user.role != User.Role.TEACHER:
        raise PermissionDenied
    return get_object_or_404(TeachingClass, pk=class_id, teacher=user)


@login_required
@require_safe
def class_detail(request, class_id):
    if request.user.role == User.Role.TEACHER:
        teaching_class = teacher_class(request.user, class_id)
        groups = teaching_class.studygroup_set.select_related("work").order_by("name")
        enrollments = teaching_class.enrollment_set.select_related("student", "group")
        context = {
            "teaching_class": teaching_class,
            "groups": groups,
            "enrollments": enrollments.order_by("student__username"),
        }
        return render(request, "classroom/teacher.html", context)

    if request.user.role != User.Role.STUDENT:
        raise PermissionDenied
    enrollment = get_object_or_404(
        Enrollment.objects.select_related("teaching_class", "group__work"),
        teaching_class_id=class_id,
        student=request.user,
    )
    if enrollment.group and enrollment.group.teaching_class_id != class_id:
        raise PermissionDenied
    return render(request, "classroom/student.html", {"enrollment": enrollment})


@login_required
@require_http_methods(["GET", "POST"])
def create_group(request, class_id):
    teaching_class = teacher_class(request.user, class_id)
    form = GroupForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        _, created = StudyGroup.objects.get_or_create(
            teaching_class=teaching_class, name=form.cleaned_data["name"]
        )
        if created:
            return redirect("class-detail", class_id=class_id)
        form.add_error("name", "本班已有同名小组。")
    return render(request, "classroom/form.html", {"title": "创建小组", "form": form})


@login_required
@require_http_methods(["GET", "POST"])
def assign_group(request, class_id, enrollment_id):
    teaching_class = teacher_class(request.user, class_id)
    groups = teaching_class.studygroup_set.order_by("name")
    # SQLite takes the write lock before reading the membership and work records.
    # S2 creates the first work and its version in the same transaction.
    with transaction.atomic():
        enrollment = get_object_or_404(
            teaching_class.enrollment_set.select_related("student", "group"), pk=enrollment_id
        )
        if enrollment.group and enrollment.group.teaching_class_id != class_id:
            raise PermissionDenied
        form = AssignmentForm(
            request.POST if request.method == "POST" else None,
            groups=groups,
            initial={"group": enrollment.group_id},
        )
        if request.method == "POST" and form.is_valid():
            group = form.cleaned_data["group"]
            if group.pk == enrollment.group_id:
                return redirect("class-detail", class_id=class_id)
            if Work.objects.filter(group_id__in=[enrollment.group_id, group.pk]).exists():
                form.add_error("group", "已提交作品的小组成员名单已锁定。")
            else:
                enrollment.group = group
                enrollment.save(update_fields=["group"])
                return redirect("class-detail", class_id=class_id)
    return render(
        request, "classroom/form.html", {"title": f"为 {enrollment.student} 分组", "form": form}
    )


@login_required
@require_safe
def work_detail(request, work_id):
    works = Work.objects.select_related("group__teaching_class")
    if request.user.role == User.Role.TEACHER:
        works = works.filter(group__teaching_class__teacher=request.user)
    elif request.user.role == User.Role.STUDENT:
        works = works.filter(
            group__enrollment__student=request.user,
            group__enrollment__teaching_class=F("group__teaching_class"),
        )
    else:
        raise PermissionDenied
    work = get_object_or_404(works, pk=work_id)
    return render(request, "classroom/work.html", {"work": work})
