from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import Customer


class Invoice(models.Model):
    PAYABLE_STATUSES = ('ISSUED', 'PARTIAL')
    STATUS = [
        ('DRAFT', 'Brouillon'),
        ('ISSUED', 'Émise'),
        ('PARTIAL', 'Partiellement payée'),
        ('PAID', 'Payée'),
        ('VOID', 'Annulée'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=20, choices=STATUS, default='DRAFT')
    issued_at = models.DateTimeField(auto_now_add=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    @property
    def balance(self):
        return self.total_amount - self.paid_amount

    @property
    def is_payable(self):
        return self.status in self.PAYABLE_STATUSES and self.balance > 0

    def __str__(self):
        return f'Facture {self.number} · {self.customer} · {self.get_status_display()}'


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='items')
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    source_service = models.CharField(max_length=40)
    source_reference = models.CharField(max_length=80, blank=True)

    @property
    def subtotal(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f'{self.description} × {self.quantity}'


class PaymentMethod(models.Model):
    name = models.CharField(max_length=80, unique=True)
    active = models.BooleanField(default=True)
    is_cash = models.BooleanField('Paiement en espèces', default=False)

    def __str__(self):
        return self.name


class Payment(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT)
    reference = models.CharField(max_length=120, blank=True)
    paid_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default='COMPLETED')
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    def __str__(self):
        return f'Paiement #{self.pk or "nouveau"} · {self.invoice.number} · {self.amount}'


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Expense(models.Model):
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    payment_method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT)
    responsible_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reference = models.CharField(max_length=120, blank=True)

    def __str__(self):
        return f'{self.description} · {self.amount}'


class Refund(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField()
    date = models.DateTimeField(auto_now_add=True)
    responsible_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, default='COMPLETED')

    def __str__(self):
        return f'Remboursement #{self.pk or "nouveau"} · {self.payment.invoice.number} · {self.amount}'
