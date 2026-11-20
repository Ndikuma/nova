from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .models import Product, ProductCategory, Stock, StockLocation, StockMovement, UnitOfMeasure
from .services import move_stock


class StockTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='chef')
        self.user.groups.add(Group.objects.create(name='Chef'))
        self.product = Product.objects.create(
            name='Eau', sku='E1',
            category=ProductCategory.objects.create(name='Test'),
            unit=UnitOfMeasure.objects.create(name='Pièce'),
        )
        self.location = StockLocation.objects.create(name='Main')

    def test_atomic_stock_movement_rejects_negative_balance(self):
        with self.assertRaises(ValueError):
            move_stock(
                product=self.product, location=self.location, quantity=1,
                movement_type='CONSUMPTION', user=self.user,
            )
        self.assertFalse(Stock.objects.exists())
        self.assertFalse(StockMovement.objects.exists())

    def test_generic_movements_update_stock_and_protect_posted_rows(self):
        self.client.force_login(self.user)
        create_url = reverse('entity_create', args=['inventory', 'stockmovement'])
        data = {'product': self.product.pk, 'location': self.location.pk, 'reference': 'Test'}
        for kind, quantity, balance in (
            ('PURCHASE', '10', '10'), ('SALE', '2', '8'), ('ADJUSTMENT', '-1.5', '6.5'),
        ):
            with self.subTest(kind=kind):
                response = self.client.post(create_url, {
                    **data, 'movement_type': kind, 'quantity': quantity,
                })
                movement = StockMovement.objects.get(movement_type=kind)
                detail = reverse('entity_detail', args=['inventory', 'stockmovement', movement.pk])
                self.assertRedirects(response, detail)
                self.assertEqual(movement.responsible_user, self.user)
                self.assertEqual(Stock.objects.get().quantity, Decimal(balance))

        for quantity, message in (('7', 'Stock insuffisant'), ('-1', 'quantité positive')):
            response = self.client.post(create_url, {**data, 'movement_type': 'SALE', 'quantity': quantity})
            self.assertContains(response, message)

        movement = StockMovement.objects.get(movement_type='SALE')
        balance = Stock.objects.get()
        for entity, record in (('stockmovement', movement), ('stock', balance)):
            detail = reverse('entity_detail', args=['inventory', entity, record.pk])
            for action in ('entity_edit', 'entity_delete'):
                url = reverse(action, args=['inventory', entity, record.pk])
                self.assertRedirects(self.client.post(url, {'quantity': '0'}), detail)
        self.assertEqual(StockMovement.objects.count(), 3)
        self.assertEqual(Stock.objects.get().quantity, Decimal('6.5'))
