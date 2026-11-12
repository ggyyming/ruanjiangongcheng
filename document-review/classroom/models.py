import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


def invitation_code():
    return secrets.token_hex(16)


class User(AbstractUser):
    class Role(models.TextChoices):
        TEACHER = "teacher", "教师"
        STUDENT = "student", "学生"

    role = models.CharField(max_length=7, choices=Role, blank=True)


class TeachingClass(models.Model):
    course = models.CharField("课程", max_length=100)
    term = models.CharField("学期", max_length=40)
    name = models.CharField("班级标识", max_length=60)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    invite_code = models.CharField(
        max_length=32, default=invitation_code, unique=True, editable=False
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["course", "term", "name"],
                name="unique_teaching_class",
                violation_error_message="此课程、学期和班级标识已存在。",
            )
        ]

    def __str__(self):
        return f"{self.course} · {self.term} · {self.name}"


class StudyGroup(models.Model):
    teaching_class = models.ForeignKey(TeachingClass, on_delete=models.CASCADE)
    name = models.CharField("组名", max_length=60)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["teaching_class", "name"], name="unique_group_in_teaching_class"
            )
        ]

    def __str__(self):
        return self.name


class Enrollment(models.Model):
    teaching_class = models.ForeignKey(TeachingClass, on_delete=models.CASCADE)
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    group = models.ForeignKey(StudyGroup, on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["teaching_class", "student"], name="unique_student_in_teaching_class"
            )
        ]


class Work(models.Model):
    group = models.OneToOneField(StudyGroup, on_delete=models.PROTECT)
    title = models.CharField("作品标题", max_length=160)
