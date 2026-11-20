from django.contrib import admin

from .models import (
    Expense, ExpenseCategory, Invoice, InvoiceItem, Payment, PaymentMethod, Refund,
)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    readonly_fields = ('paid_amount',)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register((Expense, ExpenseCategory, InvoiceItem, PaymentMethod, Refund))
