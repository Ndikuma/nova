
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.bar.models import BarOrder, BarOrderItem, BarTable, Drink, DrinkCategory
from apps.core.models import AuditLog, Customer
from apps.finance.models import (
    Expense,
    ExpenseCategory,
    Invoice,
    Payment,
    PaymentMethod,
)
from apps.hotel.models import (
    HousekeepingTask,
    Reservation,
    Room,
    RoomRate,
    RoomType,
    Stay,
)
from apps.inventory.models import (
    Product,
    ProductCategory,
    PurchaseOrder,
    Recipe,
    RecipeIngredient,
    Stock,
    StockLocation,
    StockMovement,
    Supplier,
    UnitOfMeasure,
)
from apps.restaurant.models import (
    Menu,
    MenuItem,
    Order,
    OrderItem,
    RestaurantReservation,
    Table,
)

DEMO_DISHES = (
    ('Poulet braisé', 'Plats', 8500, 'Poulet braisé au feu de bois.'),
    ('Poisson grillé', 'Plats', 9500, 'Poisson préparé au gril.'),
    ('Salade composée', 'Entrées', 4500, 'Une salade composée servie en entrée.'),
    ('Jus de bissap', 'Boissons', 2000, 'Boisson à base de bissap.'),
    ('Attiéké garni', 'Plats', 6000, 'Attiéké servi avec sa garniture.'),
)

DEMO_DRINKS = (
    ('Bissap maison', 2500, 'Boisson maison à base de bissap.'),
    ('Gingembre', 2500, 'Boisson au gingembre.'),
    ('Coca-Cola', 1500, 'Soda au cola.'),
    ('Eau minérale', 1000, 'Eau minérale.'),
)


ROLE_ACCOUNTS = [
    (
        'superadmin',
        'Super',
        'Admin',
        'Superadmin',
        'Super@Nova2026',
        'Super administrateur',
        True,
        True,
    ),
    (
        'owner',
        'Awa',
        'Koné',
        'Owner',
        'Owner@Nova2026',
        'Gérant',
        True,
        False,
    ),
    (
        'chef',
        'Koffi',
        'Bamba',
        'Chef',
        'Chef@Nova2026',
        'Chef de cuisine',
        False,
        False,
    ),
    (
        'receptionniste',
        'Fatou',
        'Traoré',
        'Receptionist',
        'Reception@Nova2026',
        'Réceptionniste',
        False,
        False,
    ),
    (
        'housekeeping',
        'Aminata',
        'Diallo',
        'Housekeeper',
        'House@Nova2026',
        'Housekeeping',
        False,
        False,
    ),
    (
        'serveur',
        'Yao',
        'Kouassi',
        'Waiter',
        'Serveur@Nova2026',
        'Serveur',
        False,
        False,
    ),
    (
        'caissier',
        'Mariam',
        'Diallo',
        'Cashier',
        'Caissier@Nova2026',
        'Caissier',
        False,
        False,
    ),
    (
        'barman',
        'Ibrahim',
        'Sylla',
        'Bartender',
        'Barman@Nova2026',
        'Barman',
        False,
        False,
    ),
]


class Command(BaseCommand):
    help = (
        'Initialise les groupes, comptes utilisateurs '
        'et données de démonstration idempotentes.'
    )

    def handle(self, *args, **kwargs):
        self.stdout.write(
            self.style.WARNING(
                'Initialisation des données de démonstration...'
            )
        )

        # ---------------------------------------------------------
        # 1. ROLE GROUPS
        # ---------------------------------------------------------

        groups = {}

        group_names = [
            'Superadmin',
            'Owner',
            'Comptable',
            'Chef',
            'Receptionist',
            'Housekeeper',
            'Waiter',
            'Cashier',
            'Bartender',
        ]

        for name in group_names:
            groups[name], created = Group.objects.get_or_create(
                name=name
            )

            if created:
                self.stdout.write(f'  Groupe créé: {name}')

        # ---------------------------------------------------------
        # 2. ROLE ACCOUNTS
        # ---------------------------------------------------------

        accounts = self._create_role_accounts(groups)

        # ---------------------------------------------------------
        # 3. BASELINE REFERENCE DATA
        # ---------------------------------------------------------

        self.stdout.write('Initialisation des données de référence...')

        for name, symbol in [
            ('Pièce', 'pc'),
            ('Kilogramme', 'kg'),
            ('Litre', 'L'),
            ('Bouteille', 'bt'),
        ]:
            UnitOfMeasure.objects.get_or_create(
                name=name,
                defaults={'symbol': symbol},
            )

        for name in [
            'Épicerie',
            'Boissons',
            'Produits frais',
            'Entretien',
        ]:
            ProductCategory.objects.get_or_create(name=name)

        for name in [
            'Entrepôt principal',
            'Cuisine',
            'Stock bar',
        ]:
            StockLocation.objects.get_or_create(name=name)

        for name in [
            'Espèces',
            'Mobile Money',
            'Carte bancaire',
            'Virement',
        ]:
            PaymentMethod.objects.get_or_create(name=name, defaults={'is_cash': name == 'Espèces'})

        for name in [
            'Achats',
            'Salaires',
            'Énergie',
            'Maintenance',
        ]:
            ExpenseCategory.objects.get_or_create(name=name)

        # ---------------------------------------------------------
        # 4. HOTEL BASELINE
        # ---------------------------------------------------------

        room_specs = [
            ('Simple', 1, ['101', '102']),
            ('Double', 2, ['201', '202']),
            ('Suite', 4, ['301']),
        ]
        for name, capacity, numbers in room_specs:
            room_type, _ = RoomType.objects.get_or_create(
                name=name,
                defaults={'max_capacity': capacity, 'active': True},
            )
            for idx, number in enumerate(numbers, start=1):
                Room.objects.get_or_create(
                    number=number,
                    defaults={
                        'floor': int(number[0]),
                        'room_type': room_type,
                        'operational_status': 'AVAILABLE',
                    },
                )

        # ---------------------------------------------------------
        # 5. OPERATIONAL DEMO DATA
        # ---------------------------------------------------------

        self._seed_operations(accounts['superadmin'])

        # ---------------------------------------------------------
        # 6. COMPLETION
        # ---------------------------------------------------------

        self.stdout.write(
            self.style.SUCCESS(
                '\nInitialisation terminée avec succès.'
            )
        )

        self.stdout.write('\nCOMPTES DE DÉMONSTRATION')

        for (
            role,
            first_name,
            last_name,
            username,
            password,
            job_title,
            is_staff,
            is_superuser,
        ) in ROLE_ACCOUNTS:

            self.stdout.write(
                f'  {role:<18} '
                f'Username: {username:<15} '
                f'Password: {password}'
            )

        self.stdout.write(
            self.style.SUCCESS(
                '\nTous les comptes et les données de démonstration '
                'sont prêts.'
            )
        )

    # =============================================================
    # CREATE ROLE ACCOUNTS
    # =============================================================

    def _create_role_accounts(self, groups):
        User = get_user_model()

        accounts = {}

        role_group_mapping = {
            'superadmin': 'Superadmin',
            'owner': 'Owner',
            'comptable': 'Comptable',
            'chef': 'Chef',
            'receptionniste': 'Receptionist',
            'housekeeping': 'Housekeeper',
            'serveur': 'Waiter',
            'caissier': 'Cashier',
            'barman': 'Bartender',
        }

        for (
            role,
            first_name,
            last_name,
            username,
            password,
            job_title,
            is_staff,
            is_superuser,
        ) in ROLE_ACCOUNTS:

            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'first_name': first_name,
                    'last_name': last_name,
                    'is_staff': is_staff,
                    'is_superuser': is_superuser,
                    'job_title': job_title,
                    'is_active': True,
                },
            )

            if created:
                user.set_password(password)

            # Synchronize account information.
            user.first_name = first_name
            user.last_name = last_name
            user.job_title = job_title
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.is_active = True

            user.save()

            # Assign the corresponding group.
            group = groups[role_group_mapping[role]]
            user.groups.set([group])

            accounts[role] = user

            status = 'créé' if created else 'mis à jour'

            self.stdout.write(
                self.style.SUCCESS(
                    f'  Compte {status}: {username} ({job_title})'
                )
            )

        return accounts

    # =============================================================
    # SEED OPERATIONAL DATA
    # =============================================================

    def _seed_operations(self, user):
        today = timezone.localdate()

        # ---------------------------------------------------------
        # HOTEL ROOMS
        # ---------------------------------------------------------

        rooms = list(
            Room.objects.select_related('room_type').order_by('number')
        )

        if not rooms:
            return

        rooms_by_number = {room.number: room for room in rooms}
        room_simple = rooms_by_number.get('101') or rooms[0]
        room_double = rooms_by_number.get('201') or rooms[min(1, len(rooms) - 1)]
        room_suite = rooms_by_number.get('301') or rooms[-1]

        # ---------------------------------------------------------
        # ROOM RATES
        # ---------------------------------------------------------

        for room_type, price in [
            (room_simple.room_type, 45000),
            (room_double.room_type, 65000),
            (room_suite.room_type, 120000),
        ]:
            RoomRate.objects.get_or_create(
                room_type=room_type,
                start_date=today.replace(month=1, day=1),
                defaults={
                    'price': price,
                    'active': True,
                },
            )

        # ---------------------------------------------------------
        # CUSTOMERS
        # ---------------------------------------------------------

        customer_specs = [
            (
                'Awa',
                'Traoré',
                'awa.traore@example.com',
                '+225 07 00 00 01',
                'Cocody, Abidjan',
            ),
            (
                'Koffi',
                'Bamba',
                'koffi.bamba@example.com',
                '+225 07 00 00 02',
                'Marcory, Abidjan',
            ),
            (
                'Fatou',
                'Koné',
                'fatou.kone@example.com',
                '+225 07 00 00 03',
                'Plateau, Abidjan',
            ),
            (
                'Yao',
                'Kouassi',
                'yao.kouassi@example.com',
                '+225 07 00 00 04',
                'Yopougon, Abidjan',
            ),
            (
                'Mariam',
                'Diallo',
                'mariam.diallo@example.com',
                '+225 07 00 00 05',
                'Treichville, Abidjan',
            ),
        ]

        customers = []

        for first, last, email, phone, address in customer_specs:
            customer, _ = Customer.objects.get_or_create(
                first_name=first,
                last_name=last,
                phone=phone,
                defaults={
                    'email': email,
                    'address': address,
                },
            )

            customers.append(customer)

        # ---------------------------------------------------------
        # HOTEL RESERVATIONS
        # ---------------------------------------------------------

        reservation_specs = [
            (
                customers[0],
                room_double,
                today - timedelta(days=1),
                today + timedelta(days=2),
                'CHECKED_IN',
                195000,
            ),
            (
                customers[1],
                room_simple,
                today,
                today + timedelta(days=1),
                'CONFIRMED',
                45000,
            ),
            (
                customers[2],
                room_suite,
                today + timedelta(days=2),
                today + timedelta(days=5),
                'CONFIRMED',
                360000,
            ),
            (
                customers[3],
                room_double,
                today - timedelta(days=4),
                today - timedelta(days=2),
                'CHECKED_OUT',
                130000,
            ),
            (
                customers[4],
                room_simple,
                today + timedelta(days=1),
                today + timedelta(days=3),
                'DRAFT',
                90000,
            ),
        ]

        for (
            customer,
            room,
            check_in,
            check_out,
            status,
            total,
        ) in reservation_specs:
            Reservation.objects.get_or_create(
                customer=customer,
                room=room,
                check_in=check_in,
                defaults={
                    'check_out': check_out,
                    'adults': 2,
                    'children': 0,
                    'status': status,
                    'estimated_total': total,
                    'created_by': user,
                },
            )

        # ---------------------------------------------------------
        # HOTEL STAYS
        # ---------------------------------------------------------

        checked_in = Reservation.objects.filter(
            status='CHECKED_IN'
        ).first()

        if checked_in:
            Stay.objects.get_or_create(
                reservation=checked_in,
                defaults={
                    'actual_check_in': timezone.now(),
                    'status': 'ACTIVE',
                    'responsible_receptionist': user,
                },
            )

        # ---------------------------------------------------------
        # HOUSEKEEPING
        # ---------------------------------------------------------

        HousekeepingTask.objects.get_or_create(
            room=room_simple,
            task_type='CLEANING',
            scheduled_date=today,
            defaults={
                'status': 'PENDING',
                'assigned_to': user,
            },
        )

        HousekeepingTask.objects.get_or_create(
            room=room_double,
            task_type='INSPECTION',
            scheduled_date=today,
            defaults={
                'status': 'IN_PROGRESS',
                'assigned_to': user,
            },
        )

        # =========================================================
        # RESTAURANT
        # =========================================================

        table, _ = Table.objects.get_or_create(
            name='Table 1',
            defaults={
                'capacity': 4,
                'section': 'Salle',
            },
        )

        table_two, _ = Table.objects.get_or_create(
            name='Table 2',
            defaults={
                'capacity': 2,
                'section': 'Terrasse',
            },
        )

        menu, _ = Menu.objects.get_or_create(
            name='Carte du jour',
            defaults={
                'description': 'Menu de saison',
            },
        )

        menu_items = []

        for name, category, price, description in DEMO_DISHES:
            item, _ = MenuItem.objects.get_or_create(
                menu=menu,
                name=name,
                defaults={
                    'category': category,
                    'selling_price': price,
                    'description': description,
                    'available': True,
                },
            )

            menu_items.append(item)

        # OPEN RESTAURANT ORDER

        order, _ = Order.objects.get_or_create(
            customer=customers[0],
            table=table,
            status='OPEN',
            defaults={
                'source': 'DINE_IN',
                'created_by': user,
                'total_amount': 23000,
            },
        )

        OrderItem.objects.get_or_create(
            order=order,
            menu_item=menu_items[0],
            defaults={
                'quantity': 2,
                'unit_price': menu_items[0].selling_price,
            },
        )

        OrderItem.objects.get_or_create(
            order=order,
            menu_item=menu_items[3],
            defaults={
                'quantity': 1,
                'unit_price': menu_items[3].selling_price,
            },
        )

        # PAID RESTAURANT ORDER

        Order.objects.get_or_create(
            customer=customers[1],
            table=table_two,
            status='PAID',
            defaults={
                'source': 'DINE_IN',
                'created_by': user,
                'total_amount': 9500,
            },
        )

        # RESTAURANT RESERVATION

        RestaurantReservation.objects.get_or_create(
            customer=customers[2],
            table=table,
            reservation_at=timezone.make_aware(
                datetime.combine(
                    today + timedelta(days=1),
                    time(19, 30),
                )
            ),
            defaults={
                'guests': 4,
                'status': 'CONFIRMED',
                'notes': 'Table près de la fenêtre',
            },
        )

        # =========================================================
        # BAR
        # =========================================================

        bar_cat, _ = DrinkCategory.objects.get_or_create(
            name='Jus & sodas'
        )

        drink_objs = []

        for name, price, description in DEMO_DRINKS:
            drink, _ = Drink.objects.get_or_create(
                category=bar_cat,
                name=name,
                defaults={
                    'selling_price': price,
                    'description': description,
                    'available': True,
                },
            )

            drink_objs.append(drink)

        bar_tables = {}
        for name, capacity in [
            ('Comptoir 1', 6),
            ('Comptoir 2', 4),
            ('Terrasse bar', 4),
        ]:
            bar_tables[name], _ = BarTable.objects.get_or_create(
                name=name,
                defaults={'capacity': capacity, 'status': 'AVAILABLE', 'active': True},
            )
        bar_table = bar_tables['Comptoir 1']

        bar_order, _ = BarOrder.objects.get_or_create(
            customer=customers[2],
            table=bar_table,
            status='OPEN',
            defaults={
                'created_by': user,
                'total_amount': 5000,
            },
        )

        BarOrderItem.objects.get_or_create(
            order=bar_order,
            drink=drink_objs[0],
            defaults={
                'quantity': 2,
                'unit_price': drink_objs[0].selling_price,
            },
        )

        # =========================================================
        # INVENTORY
        # =========================================================

        pcats = {
            category.name: category
            for category in ProductCategory.objects.all()
        }

        units = {
            unit.name: unit
            for unit in UnitOfMeasure.objects.all()
        }

        locations = {
            location.name: location
            for location in StockLocation.objects.all()
        }

        # WATER PRODUCT

        product, _ = Product.objects.get_or_create(
            sku='BOIS-001',
            defaults={
                'name': 'Eau minérale 1,5 L',
                'category': pcats.get('Boissons'),
                'unit': units.get('Bouteille'),
                'minimum_stock': 12,
                'active': True,
            },
        )

        # TOMATO PRODUCT

        Product.objects.get_or_create(
            sku='FRAIS-001',
            defaults={
                'name': 'Tomates fraîches',
                'category': pcats.get('Produits frais'),
                'unit': units.get('Kilogramme'),
                'minimum_stock': 5,
                'active': True,
            },
        )

        # CHICKEN PRODUCT

        chicken, _ = Product.objects.get_or_create(
            sku='VOLAILLE-001',
            defaults={
                'name': 'Poulet entier',
                'category': pcats.get('Produits frais'),
                'unit': units.get('Kilogramme'),
                'minimum_stock': 10,
                'active': True,
            },
        )

        # STOCK

        Stock.objects.get_or_create(
            product=product,
            location=locations.get('Stock bar'),
            defaults={
                'quantity': 8,
            },
        )

        # SUPPLIER

        supplier, _ = Supplier.objects.get_or_create(
            name='Grand Marché d’Abidjan',
            defaults={
                'contact': 'Service achats',
                'phone': '+225 07 00 00 09',
                'email': 'achats@example.com',
            },
        )

        # PURCHASE ORDER

        PurchaseOrder.objects.get_or_create(
            supplier=supplier,
            order_date=today,
            defaults={
                'status': 'DRAFT',
                'total_amount': 96000,
            },
        )

        # STOCK MOVEMENT

        StockMovement.objects.get_or_create(
            product=product,
            location=locations.get('Stock bar'),
            movement_type='PURCHASE',
            quantity=24,
            reference='DEMO-001',
            defaults={
                'responsible_user': user,
            },
        )

        # RECIPE

        recipe, _ = Recipe.objects.get_or_create(
            name='Poulet braisé maison',
            defaults={
                'instructions': 'Mariner puis cuire au feu de bois.',
                'active': True,
            },
        )

        RecipeIngredient.objects.get_or_create(
            recipe=recipe,
            product=chicken,
            defaults={
                'quantity': 2,
                'unit': units.get('Kilogramme'),
            },
        )
        MenuItem.objects.filter(menu=menu, name='Poulet braisé', recipe_id__isnull=True).update(recipe_id=recipe.pk)

        # =========================================================
        # FINANCE
        # =========================================================

        method = (
            PaymentMethod.objects.filter(
                name='Mobile Money'
            ).first()
            or PaymentMethod.objects.first()
        )

        expense_cat = (
            ExpenseCategory.objects.filter(
                name='Achats'
            ).first()
            or ExpenseCategory.objects.first()
        )

        # INVOICE 1

        invoice, _ = Invoice.objects.get_or_create(
            number='FAC-DEMO-001',
            defaults={
                'customer': customers[0],
                'status': 'ISSUED',
                'total_amount': 195000,
                'paid_amount': 50000,
            },
        )

        # INVOICE 2

        Invoice.objects.get_or_create(
            number='FAC-DEMO-002',
            defaults={
                'customer': customers[2],
                'status': 'PARTIAL',
                'total_amount': 360000,
                'paid_amount': 100000,
            },
        )

        # PAYMENT

        if method and not Payment.objects.filter(invoice=invoice, reference='PAY-DEMO-001').exists():
            Payment.objects.create(
                invoice=invoice,
                amount=50000,
                method=method,
                reference='PAY-DEMO-001',
                received_by=user,
            )

        # EXPENSE

        if expense_cat and method:
            Expense.objects.get_or_create(
                reference='EXP-DEMO-001',
                defaults={
                    'category': expense_cat,
                    'description': 'Achat produits frais',
                    'amount': 35000,
                    'date': today,
                    'payment_method': method,
                    'responsible_user': user,
                },
            )

        # =========================================================
        # AUDIT LOG
        # =========================================================

        AuditLog.objects.get_or_create(
            user=user,
            action='Initialisation de la démonstration',
            object_type='Système',
            object_id='DEMO',
            defaults={
                'details': {
                    'source': 'seed_demo',
                },
            },
        )
