"""流转路由，挂载于 /transfers/。"""

from django.urls import path

from . import views

app_name = "transfers"

urlpatterns = [
    path("", views.my_transfers, name="my_transfers"),
    path("records/", views.admin_transfer_list, name="admin_transfer_list"),
    path("records/<int:transfer_id>/", views.admin_transfer_detail, name="admin_transfer_detail"),
    path("applications/", views.my_applications, name="my_applications"),
    path(
        "applications/item/<int:item_id>/",
        views.applications_for_item,
        name="applications_for_item",
    ),
    path("apply/<int:item_id>/", views.apply, name="apply"),
    path("applications/<int:application_id>/reserve/", views.reserve, name="reserve"),
    path("<int:transfer_id>/", views.transfer_detail, name="transfer_detail"),
    path("<int:transfer_id>/confirm/", views.confirm_delivery, name="confirm_delivery"),
    path("<int:transfer_id>/cancel/", views.cancel, name="cancel"),
    path("<int:transfer_id>/revoke/start/", views.start_revoke, name="start_revoke"),
    path(
        "<int:transfer_id>/revoke/direction/",
        views.declare_direction,
        name="declare_direction",
    ),
    path("<int:transfer_id>/revoke/agree/", views.agree_revoke, name="agree_revoke"),
    path("<int:transfer_id>/revoke/withdraw/", views.withdraw_revoke, name="withdraw_revoke"),
    path("conflicts/", views.admin_revocation_conflicts, name="admin_revocation_conflicts"),
    path(
        "conflicts/<int:conflict_id>/claim/",
        views.claim_revocation_conflict,
        name="claim_revocation_conflict",
    ),
    path(
        "conflicts/<int:conflict_id>/",
        views.revocation_conflict_detail,
        name="revocation_conflict_detail",
    ),
    path(
        "conflicts/<int:conflict_id>/rounds/start/",
        views.start_revocation_round,
        name="start_revocation_round",
    ),
    path(
        "conflicts/<int:conflict_id>/rounds/<int:round_id>/declare/",
        views.declare_revocation_round,
        name="declare_revocation_round",
    ),
]
