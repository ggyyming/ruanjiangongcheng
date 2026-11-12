from django.test import Client, TestCase
from django.urls import reverse

from .models import Enrollment, StudyGroup, TeachingClass, User, Work


class ClassroomTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user("teacher", role=User.Role.TEACHER)
        cls.other_teacher = User.objects.create_user("other-teacher", role=User.Role.TEACHER)
        cls.student = User.objects.create_user("student", role=User.Role.STUDENT)
        cls.waiting_student = User.objects.create_user("waiting", role=User.Role.STUDENT)
        cls.teaching_class = TeachingClass.objects.create(
            course="软件工程", term="2026 秋", name="一班", teacher=cls.teacher
        )
        cls.other_class = TeachingClass.objects.create(
            course="软件工程", term="2026 秋", name="二班", teacher=cls.other_teacher
        )
        cls.group = StudyGroup.objects.create(teaching_class=cls.teaching_class, name="一组")
        cls.open_group = StudyGroup.objects.create(teaching_class=cls.teaching_class, name="二组")
        cls.foreign_group = StudyGroup.objects.create(teaching_class=cls.other_class, name="别班组")
        cls.member = Enrollment.objects.create(
            teaching_class=cls.teaching_class, student=cls.student, group=cls.group
        )
        cls.waiting = Enrollment.objects.create(
            teaching_class=cls.teaching_class, student=cls.waiting_student
        )

    def assign_url(self, enrollment):
        return reverse("group-assign", args=[self.teaching_class.pk, enrollment.pk])

    def test_teacher_creates_class_and_group(self):
        self.client.force_login(self.teacher)
        create = reverse("class-create")
        data = {"course": "软件工程", "term": "2026 秋", "name": "三班"}
        response = self.client.post(create, data)
        new_class = TeachingClass.objects.get(name="三班")
        detail = reverse("class-detail", args=[new_class.pk])
        self.assertRedirects(response, detail)
        self.assertEqual(new_class.teacher, self.teacher)
        self.assertRegex(new_class.invite_code, r"^[0-9a-f]{32}$")
        self.assertNotEqual(new_class.invite_code, self.teaching_class.invite_code)
        self.assertContains(self.client.get(detail), new_class.invite_code)
        self.assertContains(self.client.post(create, data), "已存在")
        group_create = reverse("group-create", args=[new_class.pk])
        self.assertRedirects(self.client.post(group_create, {"name": "演示组"}), detail)
        self.assertContains(self.client.post(group_create, {"name": "演示组"}), "已有同名小组")
        self.assertContains(self.client.get(detail), "未提交")

    def test_student_join_is_idempotent_and_class_code_is_private(self):
        self.client.force_login(self.student)
        join = reverse("class-join")
        self.assertContains(self.client.post(join, {"code": "invalid"}), "邀请码无效")
        self.assertFalse(Enrollment.objects.filter(teaching_class=self.other_class).exists())
        detail = reverse("class-detail", args=[self.other_class.pk])
        for _ in range(2):
            response = self.client.post(join, {"code": self.other_class.invite_code.upper()})
            self.assertRedirects(response, detail)
        self.assertEqual(
            Enrollment.objects.filter(
                teaching_class=self.other_class, student=self.student
            ).count(),
            1,
        )
        response = self.client.get(detail)
        self.assertContains(response, "等待教师分组")
        self.assertNotContains(response, self.other_class.invite_code)
        self.assertEqual(self.client.post(reverse("class-create"), {}).status_code, 403)

    def test_assignment_rejects_cross_class_ids_and_allows_same_class(self):
        self.client.force_login(self.other_teacher)
        class_detail = reverse("class-detail", args=[self.teaching_class.pk])
        self.assertEqual(self.client.get(class_detail).status_code, 404)
        self.assertEqual(
            self.client.post(self.assign_url(self.waiting), {"group": self.group.pk}).status_code,
            404,
        )
        self.client.force_login(self.teacher)
        foreign_member = Enrollment.objects.create(
            teaching_class=self.other_class, student=self.waiting_student
        )
        self.assertEqual(
            self.client.post(self.assign_url(foreign_member), {"group": self.group.pk}).status_code,
            404,
        )
        invalid = self.client.post(self.assign_url(self.waiting), {"group": self.foreign_group.pk})
        self.assertTrue(invalid.context["form"].errors["group"])
        self.waiting.refresh_from_db()
        self.assertIsNone(self.waiting.group_id)
        for group in (self.group, self.open_group):
            response = self.client.post(self.assign_url(self.waiting), {"group": group.pk})
            self.assertRedirects(response, class_detail)
            self.waiting.refresh_from_db()
            self.assertEqual(self.waiting.group_id, group.pk)

    def test_submitted_group_rejects_departures_and_new_members(self):
        Work.objects.create(group=self.group, title="需求规格")
        self.client.force_login(self.teacher)
        response = self.client.post(self.assign_url(self.member), {"group": self.open_group.pk})
        self.assertContains(response, "成员名单已锁定")
        response = self.client.post(self.assign_url(self.waiting), {"group": self.group.pk})
        self.assertContains(response, "成员名单已锁定")
        self.member.refresh_from_db()
        self.waiting.refresh_from_db()
        self.assertEqual(self.member.group_id, self.group.pk)
        self.assertIsNone(self.waiting.group_id)

    def test_work_visible_only_to_group_or_responsible_teacher(self):
        work = Work.objects.create(group=self.group, title="一组需求规格")
        url = reverse("work-detail", args=[work.pk])
        self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")
        for user in (self.teacher, self.student):
            self.client.force_login(user)
            self.assertContains(self.client.get(url), work.title)
        self.waiting.group = self.open_group
        self.waiting.save(update_fields=["group"])
        for user in (self.waiting_student, self.other_teacher):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_csrf_and_login_protect_class_creation(self):
        self.teacher.set_password("test-only-teacher-password")
        self.teacher.save(update_fields=["password"])
        client = Client(enforce_csrf_checks=True)
        login = reverse("login")
        client.get(login)
        response = client.post(
            login,
            {
                "username": self.teacher.username,
                "password": "test-only-teacher-password",
                "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
            },
        )
        self.assertRedirects(response, reverse("class-list"))
        self.assertEqual(client.post(reverse("class-create"), {}).status_code, 403)
