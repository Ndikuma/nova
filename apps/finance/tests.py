from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.core.models import Customer

from .models import Invoice, Payment, PaymentMethod
from .services import record_payment


class FinanceTests(TestCase):
    def setUp(self):
        self.cashier = get_user_model().objects.create_user(username='cashier')
        self.cashier.groups.add(Group.objects.create(name='Cashier'))
        customer = Customer.objects.create(first_name='A', last_name='B', phone='1')
        self.invoice = Invoice.objects.create(
            customer=customer, number='INV-1', total_amount=Decimal('100'), status='ISSUED',
        )
        self.electronic = PaymentMethod.objects.create(name='Mobile Money')
        self.cash = PaymentMethod.objects.create(name='Espèces', is_cash=True)

    def test_stale_invoice_cannot_accept_an_overpayment(self):
        stale = Invoice.objects.get(pk=self.invoice.pk)
        record_payment(invoice=self.invoice, amount='70', method=self.electronic, user=self.cashier)
        with self.assertRaises(ValueError):
            record_payment(invoice=stale, amount='70', method=self.electronic, user=self.cashier)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PARTIAL')
        self.assertEqual(self.invoice.balance, Decimal('30'))
        self.assertEqual(self.invoice.payments.count(), 1)

    def test_draft_and_void_invoices_cannot_be_paid(self):
        for status in ('DRAFT', 'VOID'):
            with self.subTest(status=status):
                Invoice.objects.filter(pk=self.invoice.pk).update(status=status)
                with self.assertRaises(ValueError):
                    record_payment(
                        invoice=self.invoice, amount='10', method=self.electronic, user=self.cashier,
                    )
        self.assertFalse(self.invoice.payments.exists())

    def test_cash_payment_records_without_session(self):
        self.client.force_login(self.cashier)
        data = {'invoice': self.invoice.pk, 'amount': '25', 'method': self.cash.pk}
        create_url = reverse('entity_create', args=['finance', 'payment'])
        response = self.client.post(create_url, data)

        payment = Payment.objects.get()
        detail = reverse('entity_detail', args=['finance', 'payment', payment.pk])
        self.assertRedirects(response, detail)
        self.assertEqual(payment.received_by, self.cashier)
        self.assertEqual(payment.amount, Decimal('25'))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.paid_amount, Decimal('25'))
        self.assertEqual(self.invoice.status, 'PARTIAL')

        for action in ('entity_edit', 'entity_delete'):
            url = reverse(action, args=['finance', 'payment', payment.pk])
            self.assertRedirects(self.client.post(url, {'amount': '1'}), detail)
        self.assertEqual(Payment.objects.get().amount, Decimal('25'))
