from django.db import models
from django.conf import settings

from apps.core.models import Customer


class DrinkCategory(models.Model):
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Drink(models.Model):
    category = models.ForeignKey(DrinkCategory, on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    serving_size = models.CharField(
        'Contenance', max_length=60, blank=True,
        help_text='Indiquez le format vendu, par exemple Verre de 25 cl ou Bouteille de 33 cl.',
    )
    public_ingredients = models.TextField(
        'Ingrédients de la carte', blank=True, max_length=800,
        help_text='Saisissez uniquement les ingrédients confirmés par le bar, un par ligne. '
                  'Si ce champ est vide, la carte utilise la recette associée.',
    )
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)
    image = models.ImageField(upload_to='drinks/', blank=True, null=True)
    available = models.BooleanField(default=True)
    recipe_id = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return self.name


class BarTable(models.Model):
    name = models.CharField(max_length=40)
    capacity = models.PositiveIntegerField(default=2)
    status = models.CharField(max_length=20, default='AVAILABLE')
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class BarOrder(models.Model):
    STATUS = [
        ('OPEN', 'Ouverte'),
        ('CONFIRMED', 'Confirmée'),
        ('PREPARING', 'En préparation'),
        ('SERVED', 'Servie'),
        ('PAID', 'Payée'),
        ('CANCELLED', 'Annulée'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, null=True, blank=True)
    table = models.ForeignKey(BarTable, on_delete=models.PROTECT, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='OPEN')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    notes = models.TextField(blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        place = self.table or self.customer or 'Comptoir'
        return f'Commande bar #{self.pk or "nouvelle"} · {place} · {self.get_status_display()}'


class BarOrderItem(models.Model):
    order = models.ForeignKey(BarOrder, on_delete=models.CASCADE, related_name='items')
    drink = models.ForeignKey(Drink, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    @property
    def subtotal(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f'{self.drink} × {self.quantity}'
