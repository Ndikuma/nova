from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.bar.models import BarOrder, Drink, DrinkCategory
from apps.core.models import Customer
from apps.finance.models import Invoice, PaymentMethod
from apps.hotel.models import Reservation, Room, RoomType
from apps.restaurant.models import Menu, MenuItem, Order, Table


def role_user(username, role):
    user = get_user_model().objects.create_user(username=username, password='pass12345')
    group, _created = Group.objects.get_or_create(name=role)
    user.groups.add(group)
    return user


class WorkspaceAccessTests(TestCase):
    def test_role_redirects_to_its_workspace(self):
        user = role_user('chef', 'Chef')
        self.client.force_login(user)
        response = self.client.get(reverse('workspaces:home'))
        self.assertRedirects(response, reverse('workspaces:kitchen'))

    def test_role_cannot_open_another_workspace(self):
        user = role_user('waiter', 'Waiter')
        self.client.force_login(user)
        response = self.client.get(reverse('workspaces:cashier'))
        self.assertEqual(response.status_code, 403)


class OwnerManagerTests(TestCase):
    def setUp(self):
        self.owner = role_user('owner', 'Owner')
        self.client.force_login(self.owner)

    def test_owner_can_open_every_operational_workspace(self):
        for name in ('owner', 'reception', 'kitchen', 'service', 'bar', 'cashier'):
            with self.subTest(workspace=name):
                self.assertEqual(
                    self.client.get(reverse(f'workspaces:{name}')).status_code, 200)

    def test_owner_can_drive_order_through_kitchen_and_service(self):
        order = Order.objects.create(created_by=self.owner, status='CONFIRMED')
        for action, expected in (('start', 'PREPARING'), ('ready', 'READY'), ('serve', 'SERVED')):
            response = self.client.post(
                reverse('workspaces:service_order_action', args=[order.pk, action]))
            order.refresh_from_db()
            self.assertEqual(order.status, expected)
        self.assertRedirects(response, reverse('workspaces:service'))


class ChefRestaurantScopeTests(TestCase):
    def setUp(self):
        self.chef = role_user('chef', 'Chef')
        self.client.force_login(self.chef)

    def test_chef_can_open_restaurant_and_inventory_modules(self):
        for module in ('restaurant', 'inventory'):
            with self.subTest(module=module):
                self.assertEqual(
                    self.client.get(reverse('module_home', args=[module])).status_code, 200)

    def test_chef_cannot_open_hotel_or_bar_modules(self):
        for module in ('hotel', 'bar'):
            with self.subTest(module=module):
                self.assertEqual(
                    self.client.get(reverse('module_home', args=[module])).status_code, 403)

    def test_chef_cannot_open_reception_workspace(self):
        self.assertEqual(
            self.client.get(reverse('workspaces:reception')).status_code, 403)


class RestaurantFlowTests(TestCase):
    def setUp(self):
        self.waiter = role_user('waiter', 'Waiter')
        self.chef = role_user('chef', 'Chef')
        self.cashier = role_user('cashier', 'Cashier')
        self.customer = Customer.objects.create(
            first_name='Awa', last_name='Traoré', phone='0102030405',
        )
        self.table = Table.objects.create(name='T1', capacity=2, section='Salle')
        menu = Menu.objects.create(name='Carte', description='')
        self.dish = MenuItem.objects.create(
            menu=menu, name='Poulet braisé', description='',
            category='Plats', selling_price=Decimal('5000'),
        )
        self.method = PaymentMethod.objects.create(name='Espèces', is_cash=True)

    def test_order_moves_from_kitchen_to_paid(self):
        self.client.force_login(self.waiter)
        response = self.client.post(reverse('workspaces:service_order_create'), {
            'table': self.table.pk,
            'customer': self.customer.pk,
            'source': 'DINE_IN',
            'notes': '',
            f'qty_{self.dish.pk}': '2',
            f'note_{self.dish.pk}': 'Bien cuit',
            'send': '1',
        })
        self.assertRedirects(response, reverse('workspaces:service'))
        order = Order.objects.get()
        self.assertEqual(order.status, 'CONFIRMED')
        self.assertEqual(order.total_amount, Decimal('10000'))

        self.client.force_login(self.chef)
        self.client.post(reverse('workspaces:service_order_action', args=[order.pk, 'start']))
        self.client.post(reverse('workspaces:service_order_action', args=[order.pk, 'ready']))
        order.refresh_from_db()
        self.assertEqual(order.status, 'READY')

        self.client.force_login(self.waiter)
        self.client.post(reverse('workspaces:service_order_action', args=[order.pk, 'serve']))
        self.client.post(reverse('workspaces:service_request_bill', args=[order.pk]))
        invoice = Invoice.objects.get(notes__contains=f'[ORDER:{order.pk}]')
        self.assertEqual(invoice.total_amount, Decimal('10000'))

        self.client.force_login(self.cashier)
        self.client.post(reverse('workspaces:payment_create', args=[invoice.pk]), {
            'amount': '10000',
            'method': self.method.pk,
            'reference': 'TEST-001',
        })
        invoice.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(invoice.status, 'PAID')
        self.assertEqual(order.status, 'PAID')

    def test_waiter_can_edit_draft_and_see_every_order_at_a_table(self):
        other_waiter = role_user('second', 'Waiter')
        other_order = Order.objects.create(created_by=other_waiter, table=self.table, status='CONFIRMED')
        self.client.force_login(self.waiter)
        create_url = reverse('workspaces:service_order_create')
        service_url = reverse('workspaces:service')
        form_data = {'table': self.table.pk, 'source': 'DINE_IN', f'qty_{self.dish.pk}': '1'}
        new_order = self.client.get(create_url, {'table': self.table.pk})
        self.assertContains(new_order, f'<option value="{self.table.pk}" selected>')
        self.assertRedirects(self.client.post(create_url, form_data), service_url)
        draft = Order.objects.get(created_by=self.waiter)
        self.assertEqual(draft.status, 'OPEN')
        self.assertEqual(draft.table, self.table)
        dashboard = self.client.get(service_url)
        self.assertContains(dashboard, f'id="order-{draft.pk}"')
        self.assertContains(dashboard, f'id="order-{other_order.pk}"')
        own_dashboard = self.client.get(service_url, {'vue': 'mes-commandes'})
        self.assertContains(own_dashboard, f'id="order-{draft.pk}"')
        self.assertNotContains(own_dashboard, f'id="order-{other_order.pk}"')

        edit_url = reverse('workspaces:service_order_edit', args=[draft.pk])
        self.assertContains(self.client.get(edit_url), 'Envoyer en cuisine')
        self.dish.selling_price = Decimal('6000')
        self.dish.save(update_fields=['selling_price'])
        self.assertRedirects(self.client.post(edit_url, {
            f'qty_{self.dish.pk}': '3', f'note_{self.dish.pk}': 'Sans sel', 'send': '1',
        }), service_url)
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'CONFIRMED')
        self.assertEqual(draft.total_amount, Decimal('15000'))
        self.assertEqual(draft.items.get().notes, 'Sans sel')
        self.assertRedirects(self.client.post(edit_url, {f'qty_{self.dish.pk}': '9'}), service_url)
        self.assertEqual(draft.items.get().quantity, 3)

        for order, expected_state in ((draft, 'OCCUPIED'), (other_order, 'AVAILABLE')):
            self.client.post(reverse('workspaces:service_order_action', args=[order.pk, 'cancel']))
            self.table.refresh_from_db()
            self.assertEqual(self.table.status, expected_state)

    def test_reception_uses_single_order_form_and_adds_customer_with_the_items(self):
        receptionist = role_user('reception-orders', 'Receptionist')
        self.client.force_login(receptionist)
        generic = reverse('entity_create', args=['restaurant', 'order'])
        composer = reverse('workspaces:service_order_create')
        self.assertRedirects(self.client.get(generic), composer)
        self.assertContains(self.client.get(reverse('workspaces:reception')), 'Commande restaurant')
        another = MenuItem.objects.create(menu=self.dish.menu, name='Salade', selling_price=2000)
        data = {'table': self.table.pk, 'source': 'DINE_IN', 'first_name': 'Aminata',
                f'qty_{self.dish.pk}': 2, f'qty_{another.pk}': 1, 'send': '1'}
        self.assertContains(self.client.post(composer, data), 'Renseignez ce champ')
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Customer.objects.filter(first_name='Aminata').exists())
        self.assertRedirects(self.client.post(composer, data | {'last_name': 'Diallo'}), reverse('workspaces:service'))
        order = Order.objects.get()
        self.assertEqual(order.created_by, receptionist)
        self.assertEqual(order.customer.first_name, 'Aminata')
        self.assertEqual(order.total_amount, Decimal('12000'))
        self.assertEqual(order.items.count(), 2)
        detail = reverse('entity_detail', args=['restaurant', 'order', order.pk])
        self.assertContains(self.client.get(detail), 'Salade')
        self.assertRedirects(self.client.get(reverse('entity_edit', args=['restaurant', 'orderitem', order.items.first().pk])), detail)
        self.assertRedirects(self.client.post(reverse('workspaces:service_request_bill', args=[order.pk])), reverse('workspaces:service'))
        self.assertEqual(Invoice.objects.get().items.count(), 2)

    def test_waiter_can_take_bar_orders_and_cashier_can_collect_for_walk_ins(self):
        category = DrinkCategory.objects.create(name='Jus')
        drink = Drink.objects.create(category=category, name='Bissap', selling_price=3000)
        self.client.force_login(self.waiter)
        old_url = reverse('entity_create', args=['bar', 'barorder'])
        create_url = reverse('workspaces:bar_order_create')
        self.assertRedirects(self.client.get(old_url), create_url)
        self.assertContains(self.client.get(create_url), 'Choisir les boissons')
        self.assertRedirects(self.client.post(create_url, {f'qty_{drink.pk}': 1}), reverse('workspaces:bar'))
        order = BarOrder.objects.get()
        edit_url = reverse('workspaces:bar_order_edit', args=[order.pk])
        self.assertRedirects(self.client.post(edit_url, {f'qty_{drink.pk}': 2, 'send': '1'}), reverse('workspaces:bar'))
        order.refresh_from_db()
        self.assertEqual(order.status, 'CONFIRMED')
        self.assertEqual(order.items.get().quantity, 2)
        bill_url = reverse('workspaces:bar_request_bill', args=[order.pk])
        for _ in range(2):
            self.assertRedirects(self.client.post(bill_url), reverse('workspaces:bar'))
        invoice = Invoice.objects.get()
        self.assertTrue(invoice.customer.is_walk_in)
        self.assertEqual(invoice.total_amount, Decimal('6000'))
        self.assertEqual(self.client.get(reverse('workspaces:payment_create', args=[invoice.pk])).status_code, 403)

        self.client.force_login(self.cashier)
        response = self.client.post(reverse('workspaces:payment_create', args=[invoice.pk]), {
            'amount': '6000', 'method': self.method.pk,
        })
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, 'PAID')

    def test_order_customer_mode_uses_only_the_selected_fields(self):
        self.client.force_login(self.waiter)
        url = reverse('workspaces:service_order_create')
        form = self.client.get(url)
        self.assertEqual(form.context['form']['customer_mode'].value(), 'walk_in')
        self.assertContains(form, 'Récapitulatif')
        data = {'table': self.table.pk, 'source': 'DINE_IN', f'qty_{self.dish.pk}': '1'}

        missing = self.client.post(url, data | {'customer_mode': 'existing', 'first_name': 'Aminata'})
        self.assertContains(missing, 'Sélectionnez un client.')
        self.assertEqual(missing.context['form']['customer_mode'].value(), 'existing')
        self.assertFalse(Order.objects.exists())

        response = self.client.post(url, data | {
            'customer_mode': 'walk_in', 'customer': self.customer.pk, 'email': 'courriel invalide',
        })
        self.assertRedirects(response, reverse('workspaces:service'))
        self.assertIsNone(Order.objects.get().customer)
        self.assertEqual(Customer.objects.count(), 1)

    def test_waiter_cannot_order_from_an_inactive_menu_or_closed_table(self):
        self.client.force_login(self.waiter)
        url = reverse('workspaces:service_order_create')
        data = {'table': self.table.pk, 'source': 'DINE_IN', f'qty_{self.dish.pk}': '1', 'send': '1'}
        menu = self.dish.menu
        menu.active = False
        menu.save(update_fields=['active'])
        self.assertContains(self.client.post(url, data), 'Un article sélectionné n’est plus disponible')
        self.assertFalse(Order.objects.exists())
        self.table.status = 'CLOSED'
        self.table.save(update_fields=['status'])
        self.assertContains(self.client.post(url, data), 'Sélectionnez un choix valide')
        self.assertFalse(Order.objects.exists())


class ReservationCheckoutTests(TestCase):
    def setUp(self):
        self.receptionist = role_user('reception', 'Receptionist')
        self.cashier = role_user('cashier', 'Cashier')
        self.customer = Customer.objects.create(
            first_name='Moussa', last_name='Diallo', phone='0700000000',
        )
        room_type = RoomType.objects.create(name='Double')
        self.room = Room.objects.create(number='101', room_type=room_type)
        self.method = PaymentMethod.objects.create(name='Mobile Money')
        self.reservation = Reservation.objects.create(
            customer=self.customer,
            room=self.room,
            check_in=date(2026, 12, 1),
            check_out=date(2026, 12, 3),
            status='CHECKED_IN',
            estimated_total=Decimal('80000'),
            created_by=self.receptionist,
        )

    def test_checkout_requires_payment_then_completes(self):
        self.client.force_login(self.receptionist)
        self.client.post(reverse('workspaces:reservation_prepare_checkout',
                                  args=[self.reservation.pk]))
        invoice = Invoice.objects.get(notes__contains=f'[RESERVATION:{self.reservation.pk}]')

        self.client.post(reverse('workspaces:reservation_check_out', args=[self.reservation.pk]))
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, 'CHECKED_IN')

        self.client.force_login(self.cashier)
        self.client.post(reverse('workspaces:payment_create', args=[invoice.pk]), {
            'amount': '80000',
            'method': self.method.pk,
            'reference': 'SEJOUR-001',
        })

        self.client.force_login(self.receptionist)
        self.client.post(reverse('workspaces:reservation_check_out', args=[self.reservation.pk]))
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, 'CHECKED_OUT')
