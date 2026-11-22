from django.db import models
from django.conf import settings


class UnitOfMeasure(models.Model):
    name = models.CharField(max_length=60, unique=True)
    symbol = models.CharField(max_length=12, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', editable=False,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', editable=False,
    )

    def __str__(self):
        return f'{self.name} ({self.symbol})' if self.symbol else self.name


class ProductCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
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


class Product(models.Model):
    name = models.CharField(max_length=120)
    sku = models.CharField(max_length=50, unique=True)
    category = models.ForeignKey(ProductCategory, on_delete=models.PROTECT)
    unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT)
    description = models.TextField(blank=True)
    minimum_stock = models.DecimalField(max_digits=12, decimal_places=3, default=0)
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
        return f'{self.name} · {self.sku}'


class StockLocation(models.Model):
    name = models.CharField(max_length=100, unique=True)
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


class Stock(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['product', 'location'], name='unique_stock_product_location'),
        ]

    def __str__(self):
        return f'{self.product} · {self.location} : {self.quantity}'


class StockMovement(models.Model):
    TYPES = [
        ('PURCHASE', 'Achat'),
        ('SALE', 'Vente'),
        ('CONSUMPTION', 'Consommation'),
        ('ADJUSTMENT', 'Ajustement'),
        ('TRANSFER_IN', 'Transfert entrant'),
        ('TRANSFER_OUT', 'Transfert sortant'),
        ('RETURN', 'Retour'),
    ]

    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT)
    movement_type = models.CharField(max_length=20, choices=TYPES)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    reference = models.CharField(max_length=120, blank=True)
    date = models.DateTimeField(auto_now_add=True)
    responsible_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', editable=False,
    )

    def __str__(self):
        return (
            f'{self.get_movement_type_display()} · {self.product} · '
            f'{self.quantity} ({self.location})'
        )


class Supplier(models.Model):
    name = models.CharField(max_length=120)
    contact = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    tax_information = models.CharField(max_length=120, blank=True)

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


class PurchaseOrder(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    order_date = models.DateField()
    expected_delivery = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, default='DRAFT')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', editable=False,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', editable=False,
    )

    def __str__(self):
        ordered = self.order_date.strftime('%d/%m/%Y') if self.order_date else 'date à définir'
        return f'Bon de commande #{self.pk or "nouveau"} · {self.supplier} · {ordered}'


class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f'{self.product} × {self.quantity}'


class Recipe(models.Model):
    name = models.CharField(max_length=120)
    instructions = models.TextField(blank=True)
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


class RecipeIngredient(models.Model):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name='ingredients')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT)

    def __str__(self):
        return f'{self.product} × {self.quantity} {self.unit.symbol or self.unit.name}'
