"""物品市场路由（A 包，路径 /items/）。"""
from django.urls import path

from . import views

app_name = "items"

urlpatterns = [
    path("", views.item_list, name="list"),
    path("new/", views.item_create, name="create"),
    path("review/", views.review_list, name="review_list"),
    path("review/<int:item_id>/", views.review, name="review"),
    path("<int:item_id>/", views.item_detail, name="detail"),
    path("<int:item_id>/edit/", views.item_edit, name="edit"),
    path("<int:item_id>/offline/", views.item_offline, name="offline"),
    path("<int:item_id>/relist/", views.item_relist, name="relist"),
]
