from django.db import models
from django.conf import settings

from apps.core.models import Customer


class Table(models.Model):
    STATUS = [
        ('AVAILABLE', 'Disponible'),
        ('OCCUPIED', 'Occupée'),
        ('RESERVED', 'Réservée'),
        ('CLOSED', 'Fermée'),
    ]

    name = models.CharField(max_length=40)
    capacity = models.PositiveIntegerField(default=2)
    section = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='AVAILABLE')
    active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', editable=False,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', editable=False,
    )

    def __str__(self):
        return self.name


class Menu(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    available_from = models.DateField(null=True, blank=True)
    available_until = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', editable=False,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', editable=False,
    )

    def __str__(self):
        return self.name


class MenuItem(models.Model):
    menu = models.ForeignKey(Menu, on_delete=models.PROTECT, related_name='items')
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    serving_size = models.CharField(
        'Portion', max_length=60, blank=True,
        help_text='Indiquez le format servi, par exemple 250 g ou 2 personnes.',
    )
    public_ingredients = models.TextField(
        'Ingrédients de la carte', blank=True, max_length=800,
        help_text='Saisissez uniquement les ingrédients confirmés par la cuisine, un par ligne. '
                  'Si ce champ est vide, la carte utilise la recette associée.',
    )
    category = models.CharField(max_length=80, blank=True)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)
    image = models.ImageField(upload_to='menu/', blank=True, null=True)
    available = models.BooleanField(default=True)
    recipe = models.ForeignKey(
        'inventory.Recipe', null=True, blank=True, on_delete=models.SET_NULL,
        verbose_name='Recette', related_name='menu_items',
        help_text='Recette/composition (ingrédients inventaire) utilisée pour ce plat.',
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', editable=False,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', editable=False,
    )

    def __str__(self):
        return self.name


class Order(models.Model):
    SOURCE = [
        ('DINE_IN', 'Sur place'),
        ('TAKEAWAY', 'À emporter'),
        ('ROOM_SERVICE', 'Room service'),
    ]
    STATUS = [
        ('OPEN', 'Ouverte'),
        ('CONFIRMED', 'Confirmée'),
        ('PREPARING', 'En préparation'),
        ('READY', 'Prête'),
        ('SERVED', 'Servie'),
        ('PAID', 'Payée'),
        ('CANCELLED', 'Annulée'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, null=True, blank=True)
    table = models.ForeignKey(Table, on_delete=models.PROTECT, null=True, blank=True)
    source = models.CharField(max_length=20, choices=SOURCE, default='DINE_IN')
    status = models.CharField(max_length=20, choices=STATUS, default='OPEN')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    notes = models.TextField(blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', editable=False,
    )

    def __str__(self):
        place = self.table or self.customer or 'Sans table'
        return f'Commande #{self.pk or "nouvelle"} · {place} · {self.get_status_display()}'


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    menu_item = models.ForeignKey(MenuItem, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(blank=True)

    @property
    def subtotal(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f'{self.menu_item} × {self.quantity}'


class RestaurantReservation(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    table = models.ForeignKey(Table, on_delete=models.PROTECT)
    reservation_at = models.DateTimeField()
    guests = models.PositiveIntegerField()
    status = models.CharField(max_length=20, default='CONFIRMED')
    contact_information = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', editable=False,
    )

    def __str__(self):
        when = (
            self.reservation_at.strftime('%d/%m/%Y %H:%M')
            if self.reservation_at else 'date à définir'
        )
        return f'Réservation restaurant · {self.customer} · {self.table} · {when}'
