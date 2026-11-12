from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.catalog.models import Item
from apps.loans import services
from apps.payments.services import apply_simulated_receipt, pay_transfer
from apps.transfers.models import Application, Transfer
from apps.transfers.services import confirm_delivery

User = get_user_model()


def make_user(username, **kwargs):
    return User.objects.create_user(username=username, password="pass-12345", **kwargs)


def make_agreement(owner, borrower, *, deposit_amount="100.00", item_title="相机"):
    amount = Decimal(deposit_amount)
    item = Item.objects.create(
        owner=owner,
        name=item_title,
        flow_type=Item.FlowType.LOAN,
        deposit_display=amount,
        display_status=Item.DisplayStatus.OFFLINE,
    )
    application = Application.objects.create(
        item=item,
        applicant=borrower,
        kind=Application.Kind.BORROW,
        status=Application.Status.SELECTED,
    )
    transfer = Transfer.objects.create(
        item=item,
        application=application,
        owner=owner,
        recipient=borrower,
        kind=Transfer.Kind.BORROW,
        amount=amount,
    )
    return services.create_agreement(transfer=transfer)


def agree_due_and_start(agreement, days=2):
    due = timezone.now() + timedelta(days=days)
    services.set_due_date(agreement, agreement.owner, due)
    services.confirm_due_date(agreement, agreement.borrower)
    op = pay_transfer(actor=agreement.borrower, transfer_id=agreement.transfer_id)
    apply_simulated_receipt(operation_id=op.pk, result="success")
    confirm_delivery(actor=agreement.owner, transfer_id=agreement.transfer_id)
    confirm_delivery(actor=agreement.borrower, transfer_id=agreement.transfer_id)
    agreement.refresh_from_db()
    return agreement


def make_overdue(agreement):
    """把有效期限移到过去并执行一次逾期扫描。"""
    agreement.due_at = timezone.now() - timedelta(hours=1)
    agreement.save(update_fields=("due_at",))
    services.scan_overdue()
    agreement.refresh_from_db()
