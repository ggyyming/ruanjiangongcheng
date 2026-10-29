"""物品市场页面（A 包，路径 /items/）。"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ItemForm
from .models import Item
from .services import (
    can_display,
    create_item,
    edit_item,
    offline_item,
    relist_item,
    review_item,
)

staff_only = user_passes_test(lambda u: u.is_staff)


def item_list(request):
    """公开列表（CP-UC-00）：仅展示满足公开展示条件的物品。

    ponytail: 当前逐条调用 can_display，物品量增大后可改为查询集子查询。
    """
    items = Item.objects.filter(display_status=Item.DisplayStatus.AVAILABLE).select_related(
        "owner"
    )
    items = [item for item in items if can_display(item_id=item.id)]
    return render(request, "catalog/item_list.html", {"items": items})


def item_detail(request, item_id):
    item = get_object_or_404(Item, id=item_id)
    is_owner = request.user.is_authenticated and item.owner_id == request.user.id
    is_staff = request.user.is_authenticated and request.user.is_staff
    if not (is_owner or is_staff):
        # 公开访问仅限可申请且物主具备资格的物品；私密字段不返回（CP-D-03）
        if not can_display(item_id=item.id):
            raise PermissionDenied("物品不存在或不可见")
        show_private = False
    else:
        # ponytail: CP-D-03 规定联系方式和地点仅在预留后向双方显示，
        # B0 合入前物主本人可见、管理员审核页不显示；预留双方可见待 B 接口接入。
        show_private = is_owner
    context = {
        "item": item,
        "show_private": show_private,
        "is_owner": is_owner,
        "is_staff": is_staff,
    }
    return render(request, "catalog/item_detail.html", context)


@login_required
def item_create(request):
    form = ItemForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            item = create_item(owner=request.user, **form.cleaned_data)
            messages.success(request, "发布成功，等待管理员审核（先审核后公开）")
            return redirect("items:detail", item_id=item.id)
        except PermissionDenied as exc:
            messages.error(request, str(exc))
    return render(request, "catalog/item_form.html", {"form": form, "editing": False})


@login_required
def item_edit(request, item_id):
    item = get_object_or_404(Item, id=item_id)
    # 先校验物主再构建表单，避免私密字段（联系方式/地点）泄露给非物主（CP-D-03）
    if item.owner_id != request.user.id:
        raise PermissionDenied("只能修改本人发布的物品")
    form = ItemForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        item = edit_item(owner=request.user, item_id=item_id, **form.cleaned_data)
        messages.success(request, "修改已保存，重新进入待审核（CP-D-10）")
        return redirect("items:detail", item_id=item.id)
    return render(
        request, "catalog/item_form.html", {"form": form, "editing": True, "item": item}
    )


@login_required
def item_offline(request, item_id):
    if request.method == "POST":
        try:
            offline_item(owner=request.user, item_id=item_id)
            messages.success(request, "物品已下架")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    return redirect("items:detail", item_id=item_id)


@login_required
def item_relist(request, item_id):
    if request.method == "POST":
        try:
            relist_item(owner=request.user, item_id=item_id)
            messages.success(request, "已申请重新上架，等待重新审核（CP-D-11）")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    return redirect("items:detail", item_id=item_id)


@staff_only
def review_list(request):
    items = Item.objects.filter(display_status=Item.DisplayStatus.PENDING).select_related("owner")
    return render(request, "catalog/review_list.html", {"items": items})


@staff_only
def review(request, item_id):
    item = get_object_or_404(Item, id=item_id)
    if request.method == "POST":
        approve = request.POST.get("approve") == "on"
        reason = request.POST.get("reason", "").strip()
        try:
            review_item(actor=request.user, item_id=item_id, approve=approve, reason=reason)
            messages.success(request, "审核完成")
            return redirect("items:review_list")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    return render(request, "catalog/review.html", {"item": item})
