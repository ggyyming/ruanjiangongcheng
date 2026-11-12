"""模拟资金页面视图。

付款/结算/退款均为模拟，展示时明确标注（模拟）。资金状态变更只调用 services，
普通用户无法通过页面直接把处理中写成到账（共同约定 §4）。
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.loans.services import delivery_ready
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
        Transfer.objects.select_related("item", "borrow_agreement"), pk=transfer_id
    )
    if request.user.id not in (transfer.owner_id, transfer.recipient_id):
        raise PermissionDenied("只有本次流转当事人可以查看")
    payments = list(transfer.payment_operations.all())
    payment = next((op for op in payments if op.kind == PaymentOperation.Kind.PAYMENT), None)
    recipient = request.user.id == transfer.recipient_id
    deadline = services.payment_deadline(transfer)
    past_deadline = timezone.now() >= deadline
    agreement = getattr(transfer, "borrow_agreement", None)
    awaiting_terms = transfer.kind == Transfer.Kind.BORROW and not delivery_ready(
        transfer_id=transfer.pk
    )
    can_pay = (
        recipient
        and transfer.kind != Transfer.Kind.DONATION
        and transfer.status == Transfer.Status.RESERVED
        and transfer.revoke_status == Transfer.RevokeStatus.NONE
        and not past_deadline
        and not awaiting_terms
        and (
            payment is None
            or payment.status
            in (
                PaymentOperation.Status.UNPAID,
                PaymentOperation.Status.PAY_FAILED,
            )
        )
    )
    return render(
        request,
        "payments/payments_for_transfer.html",
        {
            "transfer": transfer,
            "payments": payments,
            "payment": payment,
            "can_pay": can_pay,
            "deadline": deadline,
            "past_deadline": past_deadline,
            "awaiting_terms": awaiting_terms,
            "agreement": agreement,
        },
    )


@login_required
@require_POST
def pay(request, transfer_id):
    get_object_or_404(Transfer, pk=transfer_id)
    try:
        payment = services.pay_transfer(actor=request.user, transfer_id=transfer_id)
        if payment.status == PaymentOperation.Status.PAID:
            messages.info(request, "这笔模拟付款已成功。")
        else:
            messages.info(request, "模拟付款正在处理，请稍后查看结果。")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _err(exc))
    return redirect("payments:payments_for_transfer", transfer_id=transfer_id)
