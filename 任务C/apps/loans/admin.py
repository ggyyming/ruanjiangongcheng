from django.contrib import admin

from .models import (
    BorrowAgreement,
    BorrowRestriction,
    Dispute,
    DisputeEvent,
    ExtensionRequest,
    Notification,
)


@admin.register(BorrowAgreement)
class BorrowAgreementAdmin(admin.ModelAdmin):
    list_display = ("item_title", "owner", "borrower", "status", "due_at", "deposit_amount")
    list_filter = ("status",)
    search_fields = ("item_title", "item_ref", "owner__username", "borrower__username")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ExtensionRequest)
class ExtensionRequestAdmin(admin.ModelAdmin):
    list_display = ("agreement", "previous_due_at", "proposed_due_at", "status", "requested_at")
    list_filter = ("status",)


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = ("agreement", "kind", "status", "opened_by", "assigned_admin", "created_at")
    list_filter = ("kind", "status")


@admin.register(DisputeEvent)
class DisputeEventAdmin(admin.ModelAdmin):
    list_display = ("dispute", "action", "actor", "created_at")
    list_filter = ("action",)


@admin.register(BorrowRestriction)
class BorrowRestrictionAdmin(admin.ModelAdmin):
    list_display = ("user", "cause", "active", "reason", "created_at", "released_at")
    list_filter = ("cause", "active")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "business_kind", "event", "title", "created_at", "read_at")
    list_filter = ("business_kind", "event")
    search_fields = ("recipient__username", "title", "body")
