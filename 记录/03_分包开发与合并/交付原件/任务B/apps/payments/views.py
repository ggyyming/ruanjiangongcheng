"""模拟资金页面视图。

付款/结算/退款均为模拟，展示时明确标注（模拟）。资金状态变更只调用 services，
普通用户无法通过页面直接把处理中写成到账（共同约定 §4）。
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.transfers.models import Transfer

from . import services
from .models import PaymentOperation


def _err(exc):
    if isinstance(exc, ValidationError):
        return "; ".join(str(m) for m in exc.messages)
    return str(exc)


@login_required
def payments_for_transfer(request, transfer_id):
    transfer = get_object_or_404(
        Transfer.objects.select_related("item", "owner", "recipient"), pk=transfer_id
    )
    if request.user.id not in (transfer.owner_id, transfer.recipient_id):
        raise PermissionDenied("只有本次流转当事人可以查看")
    payments = PaymentOperation.objects.filter(transfer=transfer).order_by("id")
    return render(
        request,
        "payments/payments_for_transfer.html",
        {"transfer": transfer, "payments": payments},
    )


@login_required
@require_POST
def pay(request, transfer_id):
    try:
        services.pay_transfer(actor=request.user, transfer_id=transfer_id)
        messages.success(request, "已发起（模拟）付款，等待受控回执到账")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _err(exc))
    return redirect("payments:payments_for_transfer", transfer_id=transfer_id)
