import tempfile

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Customer, User
from apps.finance.models import Invoice, InvoiceItem, Payment, PaymentMethod
from .documents import REPORT_CATALOG, report_data
from .models import GeneratedReport


class ReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user('owner', password='pass')
        cls.owner.groups.add(Group.objects.create(name='Owner'))
        cls.waiter = User.objects.create_user('waiter', password='pass')
        cls.waiter.groups.add(Group.objects.create(name='Waiter'))
        cls.customer = Customer.objects.create(
            first_name='Aline', last_name='Niyonkuru', phone='+257 22 00 00',
        )
        cls.invoice = Invoice.objects.create(
            customer=cls.customer, number='INV-TEST-1', status='PAID',
            total_amount=5000, paid_amount=5000,
        )
        InvoiceItem.objects.create(
            invoice=cls.invoice, description='Nuitée', quantity=1,
            unit_price=5000, tax=0, source_service='hotel',
        )
        cls.method = PaymentMethod.objects.create(name='Espèces')
        cls.payment = Payment.objects.create(
            invoice=cls.invoice, amount=5000, method=cls.method, received_by=cls.owner,
        )

    def test_center_and_preview_are_available_to_management(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('reports:center')).status_code, 200)
        response = self.client.get(
            reverse('reports:preview', args=['invoice-register']),
            {'date_from': '2020-01-01', 'date_to': '2020-01-31'},
        )
        self.assertEqual(response.status_code, 200)

    def test_preview_rejects_role_without_permission(self):
        self.client.force_login(self.waiter)
        response = self.client.get(reverse('reports:preview', args=['expenses']))
        self.assertEqual(response.status_code, 403)

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_generate_csv_persists_report(self):
        from django.utils import timezone
        today = timezone.localdate()
        self.client.force_login(self.owner)
        response = self.client.post(reverse('reports:generate'), {
            'report_code': 'invoice-register',
            'date_from': today.isoformat(),
            'date_to': today.isoformat(),
            'file_format': 'csv',
        })
        self.assertEqual(response.status_code, 302)
        run = GeneratedReport.objects.get()
        self.assertEqual(run.status, GeneratedReport.Status.COMPLETED)
        self.assertTrue(run.file.name.endswith('.csv'))
        self.assertIn('INV-TEST-1', run.file.read().decode('utf-8-sig'))

    def test_invoice_and_receipt_documents(self):
        self.client.force_login(self.owner)
        for name, args in (
            ('reports:invoice_print', [self.invoice.pk]),
            ('reports:receipt_print', [self.payment.pk]),
        ):
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)
        try:
            import reportlab  # noqa: F401
        except ImportError:
            self.skipTest('reportlab non disponible')
        for name, args in (
            ('reports:invoice_pdf', [self.invoice.pk]),
            ('reports:receipt_pdf', [self.payment.pk]),
        ):
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_all_report_queries_execute(self):
        for code in REPORT_CATALOG:
            title, headers, rows, start, end = report_data(
                code, {'date_from': '2020-01-01', 'date_to': '2020-01-31'},
            )
            self.assertTrue(title)
            self.assertTrue(headers)
            self.assertIsInstance(rows, list)
