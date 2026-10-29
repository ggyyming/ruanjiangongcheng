"""账号与认证路由（A 包，路径 /accounts/）。"""
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="accounts/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.home, name="home"),
    path("identity/", views.identity_apply, name="identity_apply"),
    path("identity/<int:application_id>/", views.identity_detail, name="identity_detail"),
    path("review/", views.review_list, name="review_list"),
    path("review/<int:application_id>/", views.review, name="review"),
    path("revoke/<int:user_id>/", views.revoke, name="revoke"),
]
