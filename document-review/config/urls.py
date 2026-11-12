from django.contrib.auth import views as auth_views
from django.urls import path

from classroom import views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.class_list, name="class-list"),
    path("classes/new/", views.create_class, name="class-create"),
    path("classes/join/", views.join_class, name="class-join"),
    path("classes/<int:class_id>/", views.class_detail, name="class-detail"),
    path("classes/<int:class_id>/groups/new/", views.create_group, name="group-create"),
    path(
        "classes/<int:class_id>/students/<int:enrollment_id>/group/",
        views.assign_group,
        name="group-assign",
    ),
    path("works/<int:work_id>/", views.work_detail, name="work-detail"),
]
