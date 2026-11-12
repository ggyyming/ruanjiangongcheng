"""账号与认证页面（A 包，路径 /accounts/）。"""

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Exists, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.loans.models import BorrowAgreement
from apps.transfers.models import Transfer

from .forms import IdentityForm, ReviewForm, RevokeForm
from .models import IdentityApplication
from .services import (
    claim_identity_review,
    is_verified,
    review_identity,
    revoke_identity,
    submit_identity,
)

User = get_user_model()

staff_only = user_passes_test(lambda u: u.is_staff)


def register(request):
    if request.user.is_authenticated:
        return redirect("accounts:home")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "注册成功，请提交校内身份申请以获得发布资格")
        return redirect("accounts:home")
    return render(request, "accounts/register.html", {"form": form})


@login_required
def home(request):
    applications = list(request.user.identity_applications.all())
    relevant_transfers = Transfer.objects.filter(
        item_id=OuterRef("pk"),
        status__in=(
            Transfer.Status.RESERVED,
            Transfer.Status.BORROWED,
            Transfer.Status.COMPLETED,
            Transfer.Status.DONATION_COMPLETED,
        ),
    ).order_by("-pk")
    compensated = BorrowAgreement.objects.filter(
        transfer__item_id=OuterRef("pk"),
        status=BorrowAgreement.Status.COMPENSATED,
    )
    context = {
        "verified": is_verified(user_id=request.user.id),
        "applications": applications,
        "latest": applications[0] if applications else None,
        "items": request.user.items.annotate(
            flow_status=Subquery(relevant_transfers.values("status")[:1]),
            compensated=Exists(compensated),
        ).order_by("-updated_at"),
    }
    return render(request, "accounts/home.html", context)


@login_required
def identity_apply(request):
    latest = request.user.identity_applications.first()
    locked = latest and latest.status in (
        IdentityApplication.Status.APPROVED,
        IdentityApplication.Status.PENDING,
    )
    if locked:
        if request.method == "POST":
            messages.info(request, "你已有身份申请记录，请查看当前状态。")
        return redirect("accounts:identity_detail", application_id=latest.pk)

    initial = (
        {"name": latest.name, "staff_no": latest.staff_no, "department": latest.department}
        if latest
        else {}
    )
    form = IdentityForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            submit_identity(user=request.user, **form.cleaned_data)
            messages.success(request, "身份申请已提交，正在等待审核。")
            return redirect("accounts:home")
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, "accounts/identity_apply.html", {"form": form})


@login_required
def identity_detail(request, application_id):
    application = get_object_or_404(IdentityApplication, id=application_id)
    is_reviewer = request.user.is_staff and application.reviewed_by_id == request.user.id
    if application.user_id != request.user.id and not is_reviewer:
        raise PermissionDenied("只有申请人和负责审核的管理员可以查看这份资料。")
    return render(request, "accounts/identity_detail.html", {"application": application})


@staff_only
def review_list(request):
    applications = IdentityApplication.objects.filter(
        Q(reviewed_by__isnull=True) | Q(reviewed_by=request.user),
        status=IdentityApplication.Status.PENDING,
    ).select_related("user")
    approved = IdentityApplication.objects.filter(
        reviewed_by=request.user, status=IdentityApplication.Status.APPROVED
    ).select_related("user")
    return render(
        request, "accounts/review_list.html", {"applications": applications, "approved": approved}
    )


@staff_only
@require_POST
def claim_review(request, application_id):
    get_object_or_404(IdentityApplication, pk=application_id)
    try:
        claim_identity_review(actor=request.user, application_id=application_id)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("accounts:review_list")
    return redirect("accounts:review", application_id=application_id)


@staff_only
def review(request, application_id):
    application = get_object_or_404(IdentityApplication, id=application_id)
    if application.reviewed_by_id != request.user.id:
        raise PermissionDenied("只有负责管理员可以查看身份审核资料")
    form = ReviewForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            review_identity(actor=request.user, application_id=application_id, **form.cleaned_data)
            messages.success(request, "已保存审核结果。")
            return redirect("accounts:review_list")
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, "accounts/review.html", {"application": application, "form": form})


@staff_only
def revoke(request, user_id):
    target = get_object_or_404(User, id=user_id)
    form = RevokeForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            revoke_identity(actor=request.user, user_id=user_id, **form.cleaned_data)
            messages.success(request, "认证已撤销，该用户未预留的公开物品已下架")
            return redirect("accounts:review_list")
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, "accounts/revoke.html", {"target": target, "form": form})
