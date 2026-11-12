"""面向网站管理员的只读业务数据查询。"""

from django.contrib.admin import AdminSite, ModelAdmin
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission

from apps.accounts.models import IdentityApplication
from apps.catalog.models import Item, ItemAvailabilityChange
from apps.loans.models import (
    BorrowAgreement,
    BorrowRestriction,
    Dispute,
    DisputeEvent,
    ExtensionRequest,
    Notification,
)
from apps.payments.models import PaymentOperation
from apps.transfers.models import Application, Revocation, Transfer, TransferLog


class DataQuerySite(AdminSite):
    site_header = "校园流转 · 数据查询"
    site_title = "校园流转数据查询"
    index_title = "全站资料"

    def get_app_list(self, request, app_label=None):
        apps = super().get_app_list(request, app_label)
        for app in apps:
            for entry in app["models"]:
                entry["name"] = self._registry[entry["model"]].query_label
        return apps


class QueryAdmin(ModelAdmin):
    query_label = ""
    actions = None
    list_per_page = 30

    def has_module_permission(self, request):
        return self.admin_site.has_permission(request)

    def has_view_permission(self, request, obj=None):
        return self.admin_site.has_permission(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(
            request, {"title": self.query_label, **(extra_context or {})}
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        return super().change_view(
            request,
            object_id,
            form_url,
            {"title": f"查看{self.query_label}", **(extra_context or {})},
        )


data_site = DataQuerySite(name="market_data")

data_site.register(
    get_user_model(),
    QueryAdmin,
    query_label="用户账号",
    exclude=("password",),
    list_display=("username", "email", "is_active", "is_staff", "is_superuser", "date_joined"),
    search_fields=("username", "email", "first_name", "last_name"),
)

for model, label, columns, search in (
    (Group, "用户组", ("name",), ("name",)),
    (Permission, "权限", ("name", "content_type"), ("name", "codename")),
    (
        LogEntry,
        "后台操作日志",
        ("id", "action_time", "user", "object_repr"),
        ("user__username", "object_repr"),
    ),
    (
        IdentityApplication,
        "身份申请",
        ("id", "user", "name", "status", "created_at"),
        ("user__username", "name", "staff_no", "department"),
    ),
    (
        Item,
        "物品资料",
        ("name", "owner", "flow_type", "display_status", "created_at"),
        ("name", "owner__username", "owner_nickname", "category"),
    ),
    (
        ItemAvailabilityChange,
        "物品上架与下架记录",
        ("id", "item", "available", "created_at"),
        ("item__name", "reason"),
    ),
    (
        Application,
        "流转申请",
        ("id", "item", "applicant", "kind", "status", "created_at"),
        ("item__name", "applicant__username"),
    ),
    (
        Transfer,
        "流转详情",
        ("id", "item", "owner", "recipient", "kind", "status", "reserved_at"),
        ("item__name", "owner__username", "recipient__username", "=id"),
    ),
    (
        Revocation,
        "撤销协商",
        ("id", "transfer", "initiator", "created_at"),
        ("transfer__item__name", "=transfer_id"),
    ),
    (
        TransferLog,
        "流转操作记录",
        ("id", "transfer", "action_label", "actor", "created_at"),
        ("transfer__item__name", "actor__username", "=transfer_id"),
    ),
    (
        PaymentOperation,
        "模拟资金流水",
        ("id", "transfer", "kind", "purpose", "amount", "status"),
        ("transfer__item__name", "business_id", "=id"),
    ),
    (
        BorrowAgreement,
        "借用与归还",
        ("id", "item_title", "owner", "borrower", "status", "due_at"),
        ("item_title", "owner__username", "borrower__username"),
    ),
    (
        ExtensionRequest,
        "延期申请",
        ("id", "agreement", "requested_by", "status", "requested_at"),
        ("agreement__item_title", "requested_by__username"),
    ),
    (
        Dispute,
        "争议资料",
        ("id", "agreement", "kind", "status", "assigned_admin", "created_at"),
        ("agreement__item_title", "opened_by__username", "description", "materials"),
    ),
    (
        DisputeEvent,
        "争议处理记录",
        ("id", "dispute", "action_label", "actor", "created_at"),
        ("dispute__agreement__item_title", "actor__username", "note"),
    ),
    (
        BorrowRestriction,
        "借用限制",
        ("id", "user", "active", "reason", "created_at"),
        ("user__username", "reason"),
    ),
    (
        Notification,
        "站内通知",
        ("id", "recipient", "business_kind", "title", "created_at", "read_at"),
        ("recipient__username", "title", "body"),
    ),
):
    data_site.register(
        model, QueryAdmin, query_label=label, list_display=columns, search_fields=search
    )
