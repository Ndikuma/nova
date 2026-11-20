from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.core.models import CompanyProfile, Customer, User
from apps.finance.models import Invoice, InvoiceItem
from apps.inventory.models import (
    Product, ProductCategory, StockLocation, StockMovement, UnitOfMeasure,
)
from .models import EBMSConfiguration, EBMSInvoice, EBMSStockMovement
from .services import prepare_invoice, prepare_stock_movement


class ObrEbmsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        company = CompanyProfile.load()
        company.obr_ebms_enabled = True
        company.save(update_fields=['obr_ebms_enabled'])

        cls.owner = User.objects.create_user('owner', password='pass')
        cls.owner.groups.add(Group.objects.create(name='Owner'))
        cls.waiter = User.objects.create_user('waiter', password='pass')
        cls.waiter.groups.add(Group.objects.create(name='Waiter'))

        cls.customer = Customer.objects.create(
            first_name='Jean', last_name='Ndayishimiye', phone='+257 79 00 00',
        )
        cls.invoice = Invoice.objects.create(
            customer=cls.customer, number='INV-OBR-1', status='ISSUED',
            total_amount=10000,
        )
        InvoiceItem.objects.create(
            invoice=cls.invoice, description='Service hôtelier', quantity=1,
            unit_price=10000, tax=0, source_service='hotel',
        )

        unit = UnitOfMeasure.objects.create(name='Pièce', symbol='PCE')
        category = ProductCategory.objects.create(name='Boissons')
        cls.product = Product.objects.create(
            name='Eau minérale', sku='EAU-1', category=category, unit=unit,
        )
        location = StockLocation.objects.create(name='Magasin')
        cls.movement = StockMovement.objects.create(
            product=cls.product, location=location, movement_type='SALE',
            quantity=2, responsible_user=cls.owner,
        )

    def test_management_can_open_dashboard_but_waiter_cannot(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('obr_ebms:dashboard')).status_code, 200)
        self.client.force_login(self.waiter)
        self.assertEqual(self.client.get(reverse('obr_ebms:dashboard')).status_code, 403)

    def test_prepare_invoice_creates_blocked_record_without_configuration(self):
        record = prepare_invoice(self.invoice, self.owner)
        self.assertEqual(record.status, 'blocked')
        self.assertIn('activée', record.validation_errors[0].lower())
        self.assertTrue(record.request_payload)

    def test_prepare_stock_movement_creates_blocked_record(self):
        record = prepare_stock_movement(self.movement, self.owner)
        self.assertEqual(record.status, 'blocked')
        self.assertEqual(record.movement_type, 'SN')

    def test_configuration_and_tin_views(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('obr_ebms:configuration')).status_code, 200)
        self.assertEqual(self.client.get(reverse('obr_ebms:tin_check')).status_code, 200)
        self.assertEqual(self.client.get(reverse('obr_ebms:products')).status_code, 200)

    def test_configuration_saves_singleton(self):
        self.client.force_login(self.owner)
        configuration = EBMSConfiguration.load()
        configuration.enabled = True
        configuration.username = 'demo'
        configuration.password = 'secret'
        configuration.taxpayer_tin = '123456'
        configuration.save()
        response = self.client.post(reverse('obr_ebms:configuration'), {
            'enabled': 'on',
            'auto_submit_invoices': '',
            'auto_submit_stock': '',
            'base_url': configuration.base_url,
            'username': 'demo',
            'password': '',
            'taxpayer_type': '2',
            'taxpayer_name': 'Nova',
            'taxpayer_tin': '123456',
            'trade_number': '',
            'phone_number': '',
            'address': '',
            'fiscal_center': 'DGC',
            'activity_sector': '',
            'legal_form': '',
            'default_customer_name': 'Client comptoir',
            'default_measurement_unit': 'PCE',
            'default_item_code': '',
            'hotel_item_code': '',
            'restaurant_item_code': '',
            'bar_item_code': '',
            'inventory_item_code': '',
            'default_vat_rate': '0',
            'default_consumption_tax_rate': '0',
            'default_tourism_levy_rate': '0',
            'default_special_tax_rate': '0',
            'default_other_tax_rate': '0',
            'max_attempts': '5',
            'request_timeout_seconds': '30',
        })
        self.assertEqual(response.status_code, 302)
        configuration.refresh_from_db()
        self.assertEqual(configuration.password, 'secret')

    def test_feature_disabled_blocks_access_even_for_owner(self):
        company = CompanyProfile.load()
        company.obr_ebms_enabled = False
        company.save(update_fields=['obr_ebms_enabled'])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('obr_ebms:dashboard')).status_code, 403)
