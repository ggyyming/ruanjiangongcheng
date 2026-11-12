"""流转页面视图。

所有业务状态变更只调用 ``services``，视图不直接改模型状态（共同约定 §3）。
A 的 Item 模型在需要处函数体内导入，避免顶层依赖导致启动失败（共同约定 §2）。
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.loans.services import delivery_ready
from apps.payments.models import PaymentOperation
from apps.payments.services import payment_deadline

from . import services
from .forms import DirectionForm, InstructionForm, ReasonForm
from .models import Application, Revocation, RevocationConflict, RevocationRound, Transfer


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
def admin_transfer_list(request):
    if not request.user.is_staff:
        raise PermissionDenied("只有管理员可以查看全部流转记录。")
    query = request.GET.get("q", "").strip()[:100]
    transfers = Transfer.objects.select_related("item", "owner", "recipient")
    if query:
        transfers = transfers.filter(item__name__icontains=query)
    page = Paginator(transfers.order_by("-reserved_at", "-pk"), 20).get_page(
        request.GET.get("page")
    )
    return render(request, "transfers/admin_transfer_list.html", {"page_obj": page, "q": query})


@login_required
def admin_transfer_detail(request, transfer_id):
    if not request.user.is_staff:
        raise PermissionDenied("只有管理员可以查看这份管理记录。")
    transfer = get_object_or_404(
        Transfer.objects.select_related("item", "owner", "recipient", "borrow_agreement"),
        pk=transfer_id,
    )
    return render(
        request,
        "transfers/admin_transfer_detail.html",
        {
            "transfer": transfer,
            "agreement": getattr(transfer, "borrow_agreement", None),
            "events": transfer.logs.select_related("actor"),
        },
    )


@login_required
def my_applications(request):
    applications = (
        Application.objects.filter(applicant=request.user)
        .select_related("item", "transfer")
        .order_by("-created_at")
    )
    return render(request, "transfers/my_applications.html", {"applications": applications})


@login_required
def applications_for_item(request, item_id):
    from apps.catalog.models import Item  # A
    from apps.catalog.services import can_display

    item = get_object_or_404(Item, pk=item_id)
    if item.owner_id != request.user.id:
        raise PermissionDenied("只有物主可以查看申请人")
    applications = (
        Application.objects.filter(item_id=item.id)
        .select_related("applicant", "transfer")
        .order_by("-created_at")
    )
    return render(
        request,
        "transfers/applications_for_item.html",
        {"item": item, "applications": applications, "can_reserve": can_display(item_id=item.pk)},
    )


@login_required
def transfer_detail(request, transfer_id):
    transfer = get_object_or_404(
        Transfer.objects.select_related("item", "owner", "recipient", "borrow_agreement"),
        pk=transfer_id,
    )
    if request.user.id not in (transfer.owner_id, transfer.recipient_id):
        raise PermissionDenied("只有本次流转当事人可以查看")

    revocation = Revocation.objects.filter(transfer=transfer).order_by("-pk").first()
    conflict = None
    if revocation:
        conflict = RevocationConflict.objects.filter(
            revocation=revocation,
            status__in=[RevocationConflict.Status.OPEN, RevocationConflict.Status.IN_PROGRESS],
        ).first()
    is_owner = request.user.id == transfer.owner_id
    side = "owner" if is_owner else "recipient"
    my_confirmation = transfer.owner_confirmed_at if is_owner else transfer.recipient_confirmed_at
    awaiting_delivery = (
        transfer.status == Transfer.Status.RESERVED
        and transfer.revoke_status == Transfer.RevokeStatus.NONE
    )
    can_quick_pay = (
        awaiting_delivery
        and not is_owner
        and transfer.kind != Transfer.Kind.DONATION
        and timezone.now() < payment_deadline(transfer)
        and (transfer.kind != Transfer.Kind.BORROW or delivery_ready(transfer_id=transfer.pk))
        and not transfer.payment_operations.filter(
            kind=PaymentOperation.Kind.PAYMENT,
            status__in=(PaymentOperation.Status.PAID, PaymentOperation.Status.UNKNOWN),
        ).exists()
    )
    return render(
        request,
        "transfers/transfer_detail.html",
        {
            "transfer": transfer,
            "agreement": getattr(transfer, "borrow_agreement", None),
            "is_owner": is_owner,
            "my_confirmation": my_confirmation,
            "delivery_block": (
                services.delivery_block_reason(transfer)
                if awaiting_delivery and not my_confirmation
                else ""
            ),
            "awaiting_delivery": awaiting_delivery,
            "can_quick_pay": can_quick_pay,
            "revocation": revocation,
            "conflict": conflict,
            "my_direction": getattr(revocation, f"{side}_direction", None),
            "my_revoke_agreement": getattr(revocation, f"{side}_agreed_at", None),
            "my_withdrawal": getattr(revocation, f"{side}_withdrawn_at", None),
            "withdrawal_pending": bool(
                revocation and (revocation.owner_withdrawn_at or revocation.recipient_withdrawn_at)
            ),
            "direction_form": DirectionForm(),
            "reason_form": ReasonForm(),
        },
    )


@login_required
@require_POST
def apply(request, item_id):
    from apps.catalog.models import Item

    get_object_or_404(Item, pk=item_id)
    try:
        services.apply(actor=request.user, item_id=item_id)
        messages.success(request, "申请已提交，等待物主选择")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _err(exc))
        return redirect("items:detail", item_id=item_id)
    return redirect("transfers:my_applications")


@login_required
@require_POST
def reserve(request, application_id):
    application = get_object_or_404(Application, pk=application_id)
    try:
        transfer = services.reserve(actor=request.user, application_id=application_id)
        messages.success(request, "已选择申请人并预留物品")
        return redirect("transfers:transfer_detail", transfer_id=transfer.pk)
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


@login_required
def admin_revocation_conflicts(request):
    if not request.user.is_staff:
        raise PermissionDenied("只有管理员可以处理撤销去向分歧。")
    conflicts = services.pending_revocation_conflicts()
    return render(request, "transfers/admin_revocation_conflicts.html", {"conflicts": conflicts})


@login_required
def revocation_conflict_detail(request, conflict_id):
    conflict = get_object_or_404(
        RevocationConflict.objects.select_related(
            "revocation__transfer__item",
            "revocation__transfer__owner",
            "revocation__transfer__recipient",
            "assigned_admin",
        ),
        pk=conflict_id,
    )
    transfer = conflict.revocation.transfer
    user = request.user
    is_assigned = conflict.assigned_admin_id == user.id
    is_party = user.id in (transfer.owner_id, transfer.recipient_id)
    if not (is_assigned or is_party):
        raise PermissionDenied("只有负责管理员或本次流转当事人可以查看")

    revocation = conflict.revocation
    side = "owner" if user.id == transfer.owner_id else "recipient"
    current_round = conflict.current_round
    my_round_direction = None
    if current_round is not None:
        my_round_direction = getattr(current_round, f"{side}_direction", None)
    not_withdrawn = (
        revocation.owner_withdrawn_at is None and revocation.recipient_withdrawn_at is None
    )
    awaiting_round = (
        conflict.status == RevocationConflict.Status.IN_PROGRESS
        and current_round is not None
        and is_party
        and my_round_direction is None
        and not_withdrawn
    )
    can_start_round = (
        conflict.status == RevocationConflict.Status.IN_PROGRESS
        and is_assigned
        and (current_round is None or current_round.result == RevocationRound.Result.CONFLICT)
        and not_withdrawn
    )
    return render(
        request,
        "transfers/revocation_conflict_detail.html",
        {
            "conflict": conflict,
            "revocation": revocation,
            "transfer": transfer,
            "rounds": conflict.rounds.select_related("created_by"),
            "current_round": current_round,
            "is_assigned": is_assigned,
            "is_party": is_party,
            "awaiting_round": awaiting_round,
            "can_start_round": can_start_round,
            "direction_form": DirectionForm(),
            "instruction_form": InstructionForm(),
        },
    )


@login_required
@require_POST
def claim_revocation_conflict(request, conflict_id):
    try:
        conflict = services.claim_revocation_conflict(actor=request.user, conflict_id=conflict_id)
        messages.success(request, "已认领该撤销去向分歧，请发起重新确认。")
        return redirect("transfers:revocation_conflict_detail", conflict_id=conflict.pk)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _err(exc))
    return redirect("transfers:admin_revocation_conflicts")


@login_required
@require_POST
def start_revocation_round(request, conflict_id):
    form = InstructionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "请填写处理说明")
        return redirect("transfers:revocation_conflict_detail", conflict_id=conflict_id)
    try:
        services.start_revocation_round(
            actor=request.user,
            conflict_id=conflict_id,
            instruction=form.cleaned_data["instruction"],
        )
        messages.success(request, "已发起新一轮重新确认")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _err(exc))
    return redirect("transfers:revocation_conflict_detail", conflict_id=conflict_id)


@login_required
@require_POST
def declare_revocation_round(request, conflict_id, round_id):
    form = DirectionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "请选择物品去向")
        return redirect("transfers:revocation_conflict_detail", conflict_id=conflict_id)
    try:
        services.declare_revocation_round(
            actor=request.user,
            conflict_id=conflict_id,
            round_id=round_id,
            direction=form.cleaned_data["direction"],
        )
        messages.success(request, "已提交本轮物品去向")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _err(exc))
    return redirect("transfers:revocation_conflict_detail", conflict_id=conflict_id)
