from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from classroom.models import User


class Command(BaseCommand):
    help = "创建本机演示所需的虚构教师和学生账号"

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("演示账号只在本机开发配置中创建。")
        accounts = {
            "demo-teacher-1": User.Role.TEACHER,
            "demo-teacher-2": User.Role.TEACHER,
            "demo-student-1": User.Role.STUDENT,
            "demo-student-2": User.Role.STUDENT,
        }
        for username, role in accounts.items():
            user, created = User.objects.get_or_create(username=username, defaults={"role": role})
            if created:
                user.set_password("Local-review-demo-01")
                user.save(update_fields=["password"])
                self.stdout.write(f"已创建 {username}")
            else:
                self.stdout.write(f"已存在 {username}")
