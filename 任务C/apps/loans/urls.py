from django.urls import path

from . import views

app_name = "loans"

urlpatterns = [
    path("", views.loan_list, name="list"),
    path("notifications/", views.notification_list, name="notifications"),
    path(
        "notifications/<int:pk>/read/",
        views.mark_notification_read,
        name="mark_notification_read",
    ),
    path("admin/disputes/", views.admin_dispute_list, name="admin_dispute_list"),
    path(
        "admin/disputes/<int:pk>/",
        views.admin_dispute_detail,
        name="admin_dispute_detail",
    ),
    path(
        "admin/disputes/<int:pk>/claim/",
        views.claim_dispute,
        name="claim_dispute",
    ),
    path(
        "admin/disputes/<int:pk>/close/",
        views.admin_close_dispute,
        name="admin_close_dispute",
    ),
    path("disputes/<int:pk>/", views.dispute_detail, name="dispute_detail"),
    path("disputes/<int:pk>/plan/", views.record_plan, name="record_plan"),
    path(
        "disputes/<int:pk>/performed/",
        views.confirm_performed,
        name="confirm_performed",
    ),
    path("disputes/<int:pk>/end/", views.agree_end, name="agree_end"),
    path("<int:pk>/", views.loan_detail, name="detail"),
    path("<int:pk>/due-date/", views.set_due_date, name="set_due_date"),
    path("<int:pk>/due-date/confirm/", views.confirm_due_date, name="confirm_due_date"),
    path("<int:pk>/return/", views.confirm_return, name="confirm_return"),
    path("<int:pk>/extensions/", views.request_extension, name="request_extension"),
    path(
        "<int:pk>/extensions/<int:extension_pk>/decide/",
        views.decide_extension,
        name="decide_extension",
    ),
    path("<int:pk>/disputes/", views.open_dispute, name="open_dispute"),
]
