"""校园流转数据管理控制台。"""

from django import forms
from django.contrib import messages
from django.contrib.admin import AdminSite, ModelAdmin, display
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.views.decorators.http import require_http_methods

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
from apps.payments.services import (
    RECEIPT_FAILURE,
    RECEIPT_SUCCESS,
    RECEIPT_UNKNOWN,
    apply_simulated_receipt,
    close_manual_operation,
)
from apps.transfers.models import Application, Revocation, Transfer, TransferLog


class DataQuerySite(AdminSite):
    site_header = "校园流转 · 数据控制台"
    site_title = "校园流转数据控制台"
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


class ManagedRecordsAdmin(QueryAdmin):
    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def change_view(self, request, object_id, form_url="", extra_context=None):
        if request.user.is_superuser:
            return ModelAdmin.change_view(self, request, object_id, form_url, extra_context)
        return super().change_view(request, object_id, form_url, extra_context)


class AccountAdmin(ManagedRecordsAdmin):
    query_label = "用户账号"
    fields = ("username", "email", "first_name", "last_name", "is_active")
    list_display = ("username", "email", "is_active", "is_staff", "is_superuser", "date_joined")
    search_fields = ("username", "email", "first_name", "last_name")

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("username", "email", "password1", "password2")
        return super().get_fields(request, obj)

    def get_form(self, request, obj=None, change=False, **kwargs):
        if obj is None:
            kwargs["form"] = UserCreationForm
        return super().get_form(request, obj, change, **kwargs)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or not obj.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or not obj.is_superuser)


class DeliveryRecordAdmin(ManagedRecordsAdmin):
    query_label = "交付与流转操作记录"
    list_display = ("id", "transfer", "action_label", "actor", "created_at")
    search_fields = ("transfer__item__name", "actor__username", "=transfer_id")


class ReceiptForm(forms.Form):
    result = forms.ChoiceField(
        label="模拟结果",
        choices=(
            ("", "请选择"),
            (RECEIPT_SUCCESS, "成功"),
            (RECEIPT_FAILURE, "失败"),
            (RECEIPT_UNKNOWN, "未知"),
        ),
    )


class ManualCloseForm(forms.Form):
    result = forms.ChoiceField(
        label="模拟核对结果", choices=[("", "请选择"), *PaymentOperation.ManualResult.choices]
    )
    note = forms.CharField(
        label="处理说明", widget=forms.Textarea, help_text="确认办结后，这笔流水将锁定。"
    )


class PaymentQueryAdmin(QueryAdmin):
    query_label = "模拟资金流水"
    list_display = ("id", "transfer", "kind", "purpose", "amount", "status")
    list_filter = ("kind", "status")
    search_fields = ("transfer__item__name", "business_id", "=id")
    list_select_related = ("transfer",)
    manual_statuses = (PaymentOperation.Status.NEEDS_MANUAL, PaymentOperation.Status.MANUAL_CLOSED)

    def get_list_display(self, request):
        columns = super().get_list_display(request)
        return (*columns, "receipt_link") if request.user.is_superuser else columns

    @display(description="模拟操作")
    def receipt_link(self, operation):
        if operation.status == PaymentOperation.Status.MANUAL_CLOSED:
            return None
        if operation.status == PaymentOperation.Status.NEEDS_MANUAL:
            url = reverse("market_data:close_manual_operation", args=[operation.pk])
            return format_html('<a href="{}">登记并办结</a>', url)
        url = reverse("market_data:simulate_receipt", args=[operation.pk])
        return format_html('<a href="{}">模拟回执</a>', url)

    def get_urls(self):
        get_or_post = require_http_methods(["GET", "POST"])
        receipt = self.admin_site.admin_view(get_or_post(self.receipt_view))
        close = self.admin_site.admin_view(get_or_post(self.manual_close_view))
        return [
            path("<int:operation_id>/receipt/", receipt, name="simulate_receipt"),
            path("<int:operation_id>/manual-close/", close, name="close_manual_operation"),
            *super().get_urls(),
        ]

    def receipt_view(self, request, operation_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        operation = get_object_or_404(self.model, pk=operation_id)
        if operation.status in self.manual_statuses:
            raise Http404("人工处理流水不接受模拟回执。")
        form = ReceiptForm(request.POST if request.method == "POST" else None)
        if request.method == "POST" and form.is_valid():
            result = form.cleaned_data["result"]
            with transaction.atomic():
                try:
                    operation = apply_simulated_receipt(operation_id=operation.pk, result=result)
                except PaymentOperation.DoesNotExist:
                    raise Http404("该笔模拟资金流水已不存在。") from None
                if operation.status in self.manual_statuses:
                    raise Http404("人工处理流水不接受模拟回执。")
                self.log_change(
                    request,
                    operation,
                    f"提交模拟回执 {result}，当前状态：{operation.get_status_display()}",
                )
            self.message_user(
                request,
                f"回执处理完成，当前状态：{operation.get_status_display()}",
                messages.SUCCESS,
            )
            return redirect("market_data:payments_paymentoperation_changelist")
        return self.operation_form_response(request, operation, form, "模拟回执", "提交模拟回执")

    def manual_close_view(self, request, operation_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        operation = get_object_or_404(
            self.model, pk=operation_id, status=PaymentOperation.Status.NEEDS_MANUAL
        )
        form = ManualCloseForm(request.POST if request.method == "POST" else None)
        if request.method == "POST" and form.is_valid():
            try:
                with transaction.atomic():
                    operation = close_manual_operation(
                        actor=request.user, operation_id=operation.pk, **form.cleaned_data
                    )
                    self.log_change(request, operation, "登记模拟核对结果并办结")
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                self.message_user(request, "已登记模拟核对结果并办结。", messages.SUCCESS)
                return redirect("market_data:payments_paymentoperation_changelist")
        return self.operation_form_response(request, operation, form, "人工处理", "确认办结")

    def operation_form_response(self, request, operation, form, title, submit_label):
        request.current_app = self.admin_site.name
        return TemplateResponse(
            request,
            "admin/market_receipt.html",
            {
                **self.admin_site.each_context(request),
                "title": f"{title} #{operation.pk}",
                "operation": operation,
                "form": form,
                "submit_label": submit_label,
            },
        )


class ItemQueryAdmin(QueryAdmin):
    """物品资料只读视图：不展示图片字段、文件链接或存储键。"""

    query_label = "物品资料"
    fields = (
        "name",
        "owner",
        "category",
        "description",
        "flaws",
        "flow_type",
        "price",
        "deposit_display",
        "owner_nickname",
        "campus_area",
        "contact",
        "location",
        "display_status",
        "review_reason",
        "reviewed_by",
        "reviewed_at",
    )
    list_display = ("name", "owner", "flow_type", "display_status", "created_at")
    search_fields = ("name", "owner__username", "owner_nickname", "category")


data_site = DataQuerySite(name="market_data")
data_site.register(PaymentOperation, PaymentQueryAdmin)
data_site.register(get_user_model(), AccountAdmin)
data_site.register(TransferLog, DeliveryRecordAdmin)
data_site.register(Item, ItemQueryAdmin)

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
