"""流转页面视图。

所有业务状态变更只调用 ``services``，视图不直接改模型状态（共同约定 §3）。
A 的 Item 模型在需要处函数体内导入，避免顶层依赖导致启动失败（共同约定 §2）。
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import services
from .forms import DirectionForm, ReasonForm
from .models import Application, Revocation, Transfer


def _err(exc):
    if isinstance(exc, ValidationError):
        return "; ".join(str(m) for m in exc.messages)
    return str(exc)


@login_required
def my_transfers(request):
    transfers = Transfer.objects.filter(owner=request.user) | Transfer.objects.filter(
        recipient=request.user
    )
    transfers = transfers.select_related("item", "owner", "recipient").order_by("-reserved_at")
    return render(request, "transfers/my_transfers.html", {"transfers": transfers})


@login_required
def my_applications(request):
    applications = (
        Application.objects.filter(applicant=request.user)
        .select_related("item")
        .order_by("-created_at")
    )
    return render(request, "transfers/my_applications.html", {"applications": applications})


@login_required
def applications_for_item(request, item_id):
    from apps.catalog.models import Item  # A

    item = get_object_or_404(Item, pk=item_id)
    if item.owner_id != request.user.id:
        raise PermissionDenied("只有物主可以查看申请人")
    applications = (
        Application.objects.filter(item_id=item.id)
        .select_related("applicant")
        .order_by("-created_at")
    )
    return render(
        request,
        "transfers/applications_for_item.html",
        {"item": item, "applications": applications},
    )


@login_required
def transfer_detail(request, transfer_id):
    transfer = get_object_or_404(
        Transfer.objects.select_related("item", "owner", "recipient"), pk=transfer_id
    )
    if request.user.id not in (transfer.owner_id, transfer.recipient_id):
        raise PermissionDenied("只有本次流转当事人可以查看")

    from apps.payments.models import PaymentOperation  # B

    payments = PaymentOperation.objects.filter(transfer=transfer).order_by("id")
    revocation = Revocation.objects.filter(transfer=transfer).first()
    return render(
        request,
        "transfers/transfer_detail.html",
        {
            "transfer": transfer,
            "payments": payments,
            "revocation": revocation,
            "direction_form": DirectionForm(),
            "reason_form": ReasonForm(),
        },
    )


@login_required
@require_POST
def apply(request, item_id):
    try:
        services.apply(actor=request.user, item_id=item_id)
        messages.success(request, "申请已提交，等待物主选择")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _err(exc))
    return redirect("transfers:my_applications")


@login_required
@require_POST
def reserve(request, application_id):
    application = get_object_or_404(Application, pk=application_id)
    try:
        services.reserve(actor=request.user, application_id=application_id)
        messages.success(request, "已选择申请人并预留物品")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _err(exc))
    return redirect("transfers:applications_for_item", item_id=application.item_id)


@login_required
@require_POST
def confirm_delivery(request, transfer_id):
    try:
        services.confirm_delivery(actor=request.user, transfer_id=transfer_id)
        messages.success(request, "已记录交付确认")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _err(exc))
    return redirect("transfers:transfer_detail", transfer_id=transfer_id)


@login_required
@require_POST
def cancel(request, transfer_id):
    form = ReasonForm(request.POST)
    if not form.is_valid():
        messages.error(request, "请填写取消原因")
        return redirect("transfers:transfer_detail", transfer_id=transfer_id)
    try:
        services.cancel_before_delivery(
            actor=request.user, transfer_id=transfer_id, reason=form.cleaned_data["reason"]
        )
        messages.success(request, "已取消流转")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _err(exc))
    return redirect("transfers:transfer_detail", transfer_id=transfer_id)


@login_required
@require_POST
def start_revoke(request, transfer_id):
    form = ReasonForm(request.POST)
    if not form.is_valid():
        messages.error(request, "请填写撤销原因")
        return redirect("transfers:transfer_detail", transfer_id=transfer_id)
    try:
        services.start_revoke(
            actor=request.user, transfer_id=transfer_id, reason=form.cleaned_data["reason"]
        )
        messages.success(request, "已发起撤销协商")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _err(exc))
    return redirect("transfers:transfer_detail", transfer_id=transfer_id)


@login_required
@require_POST
def declare_direction(request, transfer_id):
    form = DirectionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "请选择物品去向")
        return redirect("transfers:transfer_detail", transfer_id=transfer_id)
    try:
        services.declare_direction(
            actor=request.user,
            transfer_id=transfer_id,
            direction=form.cleaned_data["direction"],
        )
        messages.success(request, "已声明物品去向")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _err(exc))
    return redirect("transfers:transfer_detail", transfer_id=transfer_id)


@login_required
@require_POST
def agree_revoke(request, transfer_id):
    try:
        services.agree_revoke(actor=request.user, transfer_id=transfer_id)
        messages.success(request, "已同意撤销")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _err(exc))
    return redirect("transfers:transfer_detail", transfer_id=transfer_id)


@login_required
@require_POST
def withdraw_revoke(request, transfer_id):
    try:
        services.withdraw_revoke(actor=request.user, transfer_id=transfer_id)
        messages.success(request, "已撤回撤销申请")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _err(exc))
    return redirect("transfers:transfer_detail", transfer_id=transfer_id)
