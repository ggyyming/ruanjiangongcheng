from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.loans import services

User = get_user_model()


def make_user(username, **kwargs):
    return User.objects.create_user(username=username, password="pass-12345", **kwargs)


def make_agreement(owner, borrower, *, deposit_amount="100.00", item_title="相机"):
    return services.create_agreement(
        owner=owner,
        borrower=borrower,
        item_ref="item-1",
        item_title=item_title,
        deposit_amount=deposit_amount,
    )


def agree_due_and_start(agreement, days=2):
    due = timezone.now() + timedelta(days=days)
    services.set_due_date(agreement, agreement.owner, due)
    services.confirm_due_date(agreement, agreement.borrower)
    services.start_borrow(agreement)
    agreement.refresh_from_db()
    return agreement


def make_overdue(agreement):
    """把有效期限移到过去并执行一次逾期扫描。"""
    agreement.due_at = timezone.now() - timedelta(hours=1)
    agreement.save(update_fields=("due_at",))
    services.scan_overdue()
    agreement.refresh_from_db()
