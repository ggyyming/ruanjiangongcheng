from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.transfers.models import Transfer

from . import services
from .forms import (
    AdminCloseForm,
    DisputeAttachmentForm,
    DisputeForm,
    DueDateForm,
    ExtensionForm,
    PlanForm,
)
from .models import BorrowAgreement, Dispute, DisputeAttachment, DisputeEvent, Notification


def _party_agreement(request, pk):
    agreement = get_object_or_404(
        BorrowAgreement.objects.select_related("owner", "borrower", "transfer"), pk=pk
    )
    if not agreement.involves(request.user):
        raise PermissionDenied("仅本次借用的当事双方可以查看。")
    return agreement


def _error_redirect(request, pk, exc):
    messages.error(request, str(exc))
    return redirect("loans:detail", pk=pk)


@login_required
def loan_list(request):
    open_disputes = Dispute.objects.filter(agreement=OuterRef("pk"), status=Dispute.Status.OPEN)
    agreements = (
        BorrowAgreement.objects.filter(Q(owner=request.user) | Q(borrower=request.user))
        .select_related("owner", "borrower")
        .annotate(has_open_dispute=Exists(open_disputes))
    )
    return render(request, "loans/loan_list.html", {"agreements": agreements})


@login_required
def loan_detail(request, pk):
    agreement = _party_agreement(request, pk)
    extensions = agreement.extensions.select_related("requested_by", "decided_by")
    open_dispute = agreement.disputes.filter(status=Dispute.Status.OPEN).first()
    pending_extension = extensions.filter(status="pending").first()
    is_owner = request.user.pk == agreement.owner_id
    now = timezone.now()
    transfer = agreement.transfer
    terms_editable = (
        agreement.status == BorrowAgreement.Status.PENDING_DELIVERY
        and transfer.revoke_status == Transfer.RevokeStatus.NONE
        and not transfer.owner_confirmed_at
        and not transfer.recipient_confirmed_at
    )
    amount_locked = transfer.payment_operations.filter(kind="payment").exists()
    context = {
        "agreement": agreement,
        "extensions": extensions,
        "open_dispute": open_dispute,
        "pending_extension": pending_extension,
        "due_form": DueDateForm(
            initial={"due_at": agreement.due_at, "deposit_amount": agreement.deposit_amount}
        ),
        "extension_form": ExtensionForm(),
        "dispute_form": DisputeForm(),
        "is_owner": is_owner,
        "is_borrower": request.user.pk == agreement.borrower_id,
        "terms_editable": terms_editable,
        "terms_expired": agreement.due_at is not None and agreement.due_at <= now,
        "can_extend": agreement.due_at is not None and agreement.due_at > now,
        "amount_locked": amount_locked,
        "my_due_confirmed": bool(
            agreement.due_owner_confirmed_at if is_owner else agreement.due_borrower_confirmed_at
        ),
    }
    if amount_locked:
        context["due_form"].fields["deposit_amount"].disabled = True
    return render(request, "loans/loan_detail.html", context)


@login_required
@require_POST
def set_due_date(request, pk):
    agreement = _party_agreement(request, pk)
    form = DueDateForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("loans:detail", pk=pk)
    try:
        services.set_due_date(agreement, request.user, **form.cleaned_data)
    except services.LoanError as exc:
        return _error_redirect(request, pk, exc)
    messages.success(request, "已记录你对归还时间和押金的确认。")
    return redirect("loans:detail", pk=pk)


@login_required
@require_POST
def confirm_due_date(request, pk):
    agreement = _party_agreement(request, pk)
    try:
        services.confirm_due_date(agreement, request.user, terms_key=request.POST.get("terms", ""))
    except services.LoanError as exc:
        return _error_redirect(request, pk, exc)
    messages.success(request, "已确认归还时间和押金。")
    return redirect("loans:detail", pk=pk)


@login_required
@require_POST
def confirm_return(request, pk):
    agreement = _party_agreement(request, pk)
    try:
        services.confirm_return(agreement, request.user)
    except services.LoanError as exc:
        return _error_redirect(request, pk, exc)
    messages.success(request, "已记录你的确认。")
    return redirect("loans:detail", pk=pk)


@login_required
@require_POST
def request_extension(request, pk):
    agreement = _party_agreement(request, pk)
    form = ExtensionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "请填写有效的延期日期和时间。")
        return redirect("loans:detail", pk=pk)
    try:
        services.request_extension(agreement, request.user, form.cleaned_data["proposed_due_at"])
    except services.LoanError as exc:
        return _error_redirect(request, pk, exc)
    messages.success(request, "延期申请已提交，等待物主同意。")
    return redirect("loans:detail", pk=pk)


@login_required
@require_POST
def decide_extension(request, pk, extension_pk):
    agreement = _party_agreement(request, pk)
    extension = get_object_or_404(agreement.extensions, pk=extension_pk)
    decision = request.POST.get("decision")
    if decision not in ("approve", "reject"):
        return _error_redirect(request, pk, "请选择同意或拒绝延期。")
    approve = decision == "approve"
    try:
        services.decide_extension(extension, request.user, approve)
    except services.LoanError as exc:
        return _error_redirect(request, pk, exc)
    messages.success(request, "延期申请已同意。" if approve else "延期申请已拒绝。")
    return redirect("loans:detail", pk=pk)


@login_required
@require_POST
def open_dispute(request, pk):
    agreement = _party_agreement(request, pk)
    form = DisputeForm(request.POST)
    if not form.is_valid():
        messages.error(request, "请填写争议类型和情况说明。")
        return redirect("loans:detail", pk=pk)
    try:
        dispute = services.open_dispute(
            agreement,
            request.user,
            form.cleaned_data["kind"],
            form.cleaned_data["description"],
            form.cleaned_data["materials"],
        )
    except services.LoanError as exc:
        return _error_redirect(request, pk, exc)
    messages.success(request, "争议已提交，归还确认和自动退款将暂缓。")
    return redirect("loans:dispute_detail", pk=dispute.pk)


@login_required
@require_POST
def add_attachment(request, pk):
    dispute = get_object_or_404(Dispute, pk=pk)
    form = DisputeAttachmentForm(request.POST, request.FILES)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("loans:dispute_detail", pk=pk)
    try:
        services.add_dispute_attachment(dispute, request.user, form.cleaned_data["file"])
    except services.LoanError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "附件已上传。")
    return redirect("loans:dispute_detail", pk=pk)


@login_required
def download_attachment(request, pk, attachment_pk):
    dispute = get_object_or_404(Dispute.objects.select_related("agreement"), pk=pk)
    if not dispute.can_view(request.user):
        raise PermissionDenied("争议材料仅当事双方及负责处理的管理员可见。")
    attachment = get_object_or_404(DisputeAttachment, pk=attachment_pk, dispute=dispute)
    if not default_storage.exists(attachment.storage_key):
        raise Http404("附件文件不存在或已被清理。")
    response = FileResponse(
        default_storage.open(attachment.storage_key, "rb"),
        as_attachment=True,
        filename=attachment.original_name,
        content_type=attachment.content_type,
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def dispute_detail(request, pk):
    dispute = get_object_or_404(
        Dispute.objects.select_related("agreement", "agreement__owner", "agreement__borrower"),
        pk=pk,
    )
    if not dispute.can_view(request.user):
        raise PermissionDenied("争议材料仅当事双方及负责处理的管理员可见。")
    is_owner = request.user.pk == dispute.agreement.owner_id
    return render(
        request,
        "loans/dispute_detail.html",
        {
            "dispute": dispute,
            "events": dispute.events.select_related("actor"),
            "attachments": dispute.attachments.select_related("uploaded_by"),
            "attachment_form": DisputeAttachmentForm(),
            "plan_form": PlanForm(initial={"plan": dispute.plan}),
            "is_party": dispute.is_party(request.user),
            "performed": (
                dispute.owner_performed_at if is_owner else dispute.borrower_performed_at
            ),
            "agreed": (dispute.owner_end_agreed_at if is_owner else dispute.borrower_end_agreed_at),
        },
    )


@login_required
@require_POST
def record_plan(request, pk):
    dispute = get_object_or_404(Dispute, pk=pk)
    form = PlanForm(request.POST)
    if not form.is_valid():
        messages.error(request, "请填写方案。")
        return redirect("loans:dispute_detail", pk=pk)
    try:
        services.record_plan(dispute, request.user, form.cleaned_data["plan"])
    except services.LoanError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "方案已记录。")
    return redirect("loans:dispute_detail", pk=pk)


@login_required
@require_POST
def confirm_performed(request, pk):
    dispute = get_object_or_404(Dispute, pk=pk)
    try:
        services.confirm_plan_performed(
            dispute, request.user, plan_key=request.POST.get("plan", "")
        )
    except services.LoanError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "已记录你的履行确认。")
    return redirect("loans:dispute_detail", pk=pk)


@login_required
@require_POST
def agree_end(request, pk):
    dispute = get_object_or_404(Dispute, pk=pk)
    try:
        services.agree_dispute_end(dispute, request.user, plan_key=request.POST.get("plan", ""))
    except services.LoanError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "已记录你同意结束争议。")
    return redirect("loans:dispute_detail", pk=pk)


@login_required
def notification_list(request):
    notifications = request.user.loan_notifications.all()
    unread = notifications.filter(read_at__isnull=True)
    unread_only = request.GET.get("view") == "unread"
    page = Paginator(unread if unread_only else notifications, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "loans/notifications.html",
        {"page_obj": page, "unread_only": unread_only, "unread_count": unread.count()},
    )


@login_required
@require_POST
def mark_notification_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    Notification.objects.filter(pk=notification.pk, read_at__isnull=True).update(
        read_at=timezone.now()
    )
    if request.POST.get("view") == "unread":
        return redirect(f"{reverse('loans:notifications')}?view=unread")
    return redirect("loans:notifications")


@login_required
def admin_dispute_list(request):
    if not request.user.is_staff:
        raise PermissionDenied("仅管理员可以查看争议列表。")
    disputes = (
        Dispute.objects.filter(Q(assigned_admin__isnull=True) | Q(assigned_admin=request.user))
        .select_related("agreement", "opened_by", "assigned_admin")
        .order_by("status", "-created_at")
    )
    return render(request, "loans/admin_dispute_list.html", {"disputes": disputes})


@login_required
def admin_dispute_detail(request, pk):
    if not request.user.is_staff:
        raise PermissionDenied("仅管理员可以查看争议。")
    dispute = get_object_or_404(
        Dispute.objects.select_related("agreement", "opened_by", "assigned_admin"), pk=pk
    )
    if dispute.assigned_admin_id != request.user.pk:
        raise PermissionDenied("只有负责管理员可以查看该争议材料。")
    DisputeEvent.objects.create(
        dispute=dispute, action="admin_viewed", actor=request.user, note="查看争议材料"
    )
    return render(
        request,
        "loans/admin_dispute_detail.html",
        {
            "dispute": dispute,
            "events": dispute.events.select_related("actor"),
            "attachments": dispute.attachments.select_related("uploaded_by"),
            "close_form": AdminCloseForm(initial={"resolution": dispute.resolution}),
        },
    )


@login_required
@require_POST
def claim_dispute(request, pk):
    dispute = get_object_or_404(Dispute, pk=pk)
    try:
        services.claim_dispute(dispute, request.user)
    except services.LoanError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "已认领该争议。")
    return redirect("loans:admin_dispute_detail", pk=pk)


@login_required
@require_POST
def admin_close_dispute(request, pk):
    dispute = get_object_or_404(Dispute, pk=pk)
    if not request.user.is_staff or dispute.assigned_admin_id != request.user.pk:
        raise PermissionDenied("只有负责管理员可以关闭该争议。")
    form = AdminCloseForm(request.POST)
    if not form.is_valid():
        messages.error(request, "请检查处理说明后再提交。")
        return redirect("loans:admin_dispute_detail", pk=pk)
    resolution = form.cleaned_data["resolution"]
    try:
        services.admin_close_dispute(dispute, request.user, resolution)
    except services.LoanError as exc:
        messages.error(request, str(exc))
        return redirect("loans:admin_dispute_detail", pk=pk)
    messages.success(request, "争议已关闭。")
    return redirect("loans:admin_dispute_list")
