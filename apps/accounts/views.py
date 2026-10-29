"""账号与认证页面（A 包，路径 /accounts/）。

ponytail: 审核页面当前以 is_staff 作为"负责管理员"的简化判断，
CP-D-22 的负责管理员对象级授权在管理员体系明确后收紧。
"""
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from .models import IdentityApplication
from .services import is_verified, review_identity, revoke_identity, submit_identity

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
    context = {
        "verified": is_verified(user_id=request.user.id),
        "applications": request.user.identity_applications.all(),
        "items": request.user.items.select_related("owner"),
    }
    return render(request, "accounts/home.html", context)


@login_required
def identity_apply(request):
    if request.method == "POST":
        form_data = {
            "name": request.POST.get("name", "").strip(),
            "staff_no": request.POST.get("staff_no", "").strip(),
            "department": request.POST.get("department", "").strip(),
        }
        if not all(form_data.values()):
            messages.error(request, "姓名、学号或工号、院系或部门均须填写")
        else:
            try:
                submit_identity(user=request.user, **form_data)
                messages.success(request, "身份申请已提交，等待管理员审核")
                return redirect("accounts:home")
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
    return render(request, "accounts/identity_apply.html")


@login_required
def identity_detail(request, application_id):
    application = get_object_or_404(IdentityApplication, id=application_id)
    if application.user_id != request.user.id and not request.user.is_staff:
        raise PermissionDenied("身份资料仅申请人本人及审核管理员可见（CP-D-22）")
    return render(request, "accounts/identity_detail.html", {"application": application})


@staff_only
def review_list(request):
    applications = IdentityApplication.objects.filter(
        status=IdentityApplication.Status.PENDING
    ).select_related("user")
    return render(request, "accounts/review_list.html", {"applications": applications})


@staff_only
def review(request, application_id):
    application = get_object_or_404(IdentityApplication, id=application_id)
    if request.method == "POST":
        approve = request.POST.get("approve") == "on"
        reason = request.POST.get("reason", "").strip()
        try:
            review_identity(
                actor=request.user, application_id=application_id, approve=approve, reason=reason
            )
            messages.success(request, "审核完成")
            return redirect("accounts:review_list")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    return render(request, "accounts/review.html", {"application": application})


@staff_only
def revoke(request, user_id):
    target = get_object_or_404(User, id=user_id)
    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        try:
            revoke_identity(actor=request.user, user_id=user_id, reason=reason)
            messages.success(request, "认证已撤销，该用户未预留的公开物品已下架")
            return redirect("accounts:review_list")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    return render(request, "accounts/revoke.html", {"target": target})
