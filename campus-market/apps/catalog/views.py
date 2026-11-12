"""物品市场页面（A 包，路径 /items/）。"""

import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.forms import ReviewForm
from apps.accounts.services import is_verified
from apps.loans.services import can_borrow
from apps.transfers.models import Application, Transfer
from apps.transfers.services import active_transfer_for_item

from .forms import ItemForm
from .models import Item
from .services import (
    can_display,
    completed_item_status,
    create_item,
    edit_item,
    offline_item,
    public_items,
    relist_item,
    require_manageable_item,
    review_item,
)

staff_only = user_passes_test(lambda u: u.is_staff)


def item_list(request):
    query = request.GET.get("q", "").strip()[:100]
    flow = request.GET.get("flow", "")
    items = public_items()
    if query:
        items = items.filter(
            Q(name__icontains=query)
            | Q(category__icontains=query)
            | Q(campus_area__icontains=query)
        )
    if flow in Item.FlowType.values:
        items = items.filter(flow_type=flow)
    else:
        flow = ""
    page = Paginator(items, 12).get_page(request.GET.get("page"))
    verified = request.user.is_authenticated and is_verified(user_id=request.user.id)
    return render(
        request,
        "catalog/item_list.html",
        {
            "page_obj": page,
            "q": query,
            "flow": flow,
            "flows": Item.FlowType.choices,
            "can_publish": verified and not request.user.is_staff,
        },
    )


def item_detail(request, item_id):
    item = get_object_or_404(Item, id=item_id)
    is_owner = request.user.is_authenticated and item.owner_id == request.user.id
    is_staff = request.user.is_authenticated and request.user.is_staff
    transfer = active_transfer_for_item(item_id=item.id)
    show_private = bool(transfer and request.user.id in (transfer.owner_id, transfer.recipient_id))
    public = can_display(item_id=item.id)
    if not (is_owner or is_staff or show_private or public):
        raise PermissionDenied("物品不存在或不可见")
    verified = request.user.is_authenticated and is_verified(user_id=request.user.id)
    pending = (
        public
        and request.user.is_authenticated
        and Application.objects.filter(
            item=item,
            applicant=request.user,
            status=Application.Status.PENDING,
        ).exists()
    )
    restricted = (
        public
        and verified
        and item.flow_type == Item.FlowType.LOAN
        and not can_borrow(user_id=request.user.id)
    )
    final_status = completed_item_status(item) if is_owner and not transfer and not public else ""
    status_label = final_status or item.get_display_status_display()
    if transfer:
        status_label = "借用中" if transfer.status == Transfer.Status.BORROWED else "已预留"
    context = {
        "item": item,
        "show_private": show_private,
        "is_owner": is_owner,
        "is_staff": is_staff,
        "transfer": transfer,
        "public": public,
        "verified": verified,
        "pending": pending,
        "restricted": restricted,
        "status_label": status_label,
        "can_manage": is_owner and verified and not transfer and not final_status,
        "can_apply": public and verified and not (is_owner or is_staff or pending or restricted),
    }
    return render(request, "catalog/item_detail.html", context)


@login_required
def item_create(request):
    form = ItemForm(request.POST or None, request.FILES or None)
    can_publish = is_verified(user_id=request.user.id)
    if request.method == "POST" and form.is_valid():
        try:
            data = dict(form.cleaned_data)
            image = data.pop("image")
            data.pop("remove_image", None)
            item = create_item(owner=request.user, image=image, **data)
            messages.success(request, "已提交审核。审核通过后，物品会出现在市场。")
            return redirect("items:detail", item_id=item.id)
        except PermissionDenied as exc:
            messages.error(request, str(exc))
    return render(request, "catalog/item_form.html", {"form": form, "can_publish": can_publish})


@login_required
def item_edit(request, item_id):
    item = get_object_or_404(Item, id=item_id)
    # 先校验物主再构建表单，避免私密字段（联系方式/地点）泄露给非物主（CP-D-03）
    if item.owner_id != request.user.id:
        raise PermissionDenied("只能修改本人发布的物品")
    if request.method == "GET":
        try:
            require_manageable_item(item)
        except ValidationError as exc:
            messages.info(request, "。".join(exc.messages))
            return redirect("items:detail", item_id=item.pk)
    form = ItemForm(request.POST or None, request.FILES or None, instance=item)
    if request.method == "POST" and form.is_valid():
        try:
            data = dict(form.cleaned_data)
            image = data.pop("image")
            remove_image = data.pop("remove_image", False)
            item = edit_item(
                owner=request.user, item_id=item_id, image=image, remove_image=remove_image, **data
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "修改已保存，物品将重新审核。")
            return redirect("items:detail", item_id=item.id)
    return render(
        request,
        "catalog/item_form.html",
        {
            "form": form,
            "editing": True,
            "item": item,
            "can_publish": True,
        },
    )


@login_required
@require_POST
def item_offline(request, item_id):
    try:
        offline_item(owner=request.user, item_id=item_id)
        messages.success(request, "物品已下架。")
    except ValidationError as exc:
        messages.error(request, "。".join(exc.messages))
    return redirect("items:detail", item_id=item_id)


@login_required
@require_POST
def item_relist(request, item_id):
    try:
        relist_item(owner=request.user, item_id=item_id)
        messages.success(request, "已提交重新上架申请，正在等待审核。")
    except ValidationError as exc:
        messages.error(request, "。".join(exc.messages))
    return redirect("items:detail", item_id=item_id)


@staff_only
def review_list(request):
    items = Item.objects.filter(display_status=Item.DisplayStatus.PENDING).select_related("owner")
    return render(request, "catalog/review_list.html", {"items": items})


@staff_only
def review(request, item_id):
    item = get_object_or_404(Item, id=item_id)
    form = ReviewForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            review_item(actor=request.user, item_id=item_id, **form.cleaned_data)
            messages.success(request, "已保存审核结果。")
            return redirect("items:review_list")
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, "catalog/review.html", {"item": item, "form": form})


def item_image(request, item_id, image_key):
    """物品图片入口（每次请求重新鉴权，URL 带版本标识）。

    可取得当前图片的角色：物主、有审核权限的管理员（待审预览）、
    进行中流转的双方、以及 can_display 为真的公开访问（含匿名访客）。
    替换或移除后旧地址（旧 key）不再指向新图；缓存策略保证下架或转待审后撤销访问。
    """
    item = get_object_or_404(Item, id=item_id)
    if not item.image or item.image_key != image_key:
        raise Http404("图片不存在或已被替换")
    transfer = active_transfer_for_item(item_id=item.id)
    is_owner = request.user.is_authenticated and item.owner_id == request.user.id
    is_staff = request.user.is_authenticated and request.user.is_staff
    is_party = bool(transfer and request.user.id in (transfer.owner_id, transfer.recipient_id))
    if not (is_owner or is_staff or is_party or can_display(item_id=item.id)):
        raise PermissionDenied("物品图片不可见")
    try:
        with item.image.open() as image_file:
            data = image_file.read()
    except FileNotFoundError:
        raise Http404("图片文件不存在")
    response = HttpResponse(
        data, content_type=mimetypes.guess_type(item.image.name)[0] or "image/jpeg"
    )
    response["Cache-Control"] = "private, no-store"
    return response
