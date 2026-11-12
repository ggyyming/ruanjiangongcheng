"""模拟资金路由，挂载于 /payments/。"""

from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("<int:transfer_id>/", views.payments_for_transfer, name="payments_for_transfer"),
    path("<int:transfer_id>/pay/", views.pay, name="pay"),
]
