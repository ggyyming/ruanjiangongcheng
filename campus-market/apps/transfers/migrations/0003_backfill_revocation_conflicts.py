# 数据迁移：为迁移前已存在、双方去向不一致且仍在协商的撤销记录补建待认领处理入口。
# 判定条件与 apps/transfers/services.backfill_revocation_conflicts 保持一致。

from django.db import migrations, models


def backfill_conflicts(apps, schema_editor):
    Revocation = apps.get_model("transfers", "Revocation")
    RevocationConflict = apps.get_model("transfers", "RevocationConflict")

    # 仍在协商、双方同意、双方去向已声明且不一致、未撤回
    conflicting = (
        Revocation.objects.filter(
            transfer__revoke_status="negotiating",
            owner_direction__isnull=False,
            recipient_direction__isnull=False,
            owner_agreed_at__isnull=False,
            recipient_agreed_at__isnull=False,
            owner_withdrawn_at__isnull=True,
            recipient_withdrawn_at__isnull=True,
        )
        .exclude(owner_direction=models.F("recipient_direction"))
        .exclude(conflict__isnull=False)
    )
    for revocation in conflicting:
        RevocationConflict.objects.create(
            revocation=revocation,
            status="open",
        )


def reverse_backfill(apps, schema_editor):
    # 回退只删除本次补建的待认领记录，不触碰已经进入处理流程的记录
    RevocationConflict = apps.get_model("transfers", "RevocationConflict")
    RevocationConflict.objects.filter(status="open").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("transfers", "0002_revocationconflict_revocationround"),
    ]

    operations = [
        migrations.RunPython(backfill_conflicts, reverse_backfill),
    ]
