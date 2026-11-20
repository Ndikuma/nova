from django.contrib import admin

from .models import (
    Product, ProductCategory, PurchaseOrder, PurchaseOrderItem, Recipe, RecipeIngredient,
    Stock, StockLocation, StockMovement, Supplier, UnitOfMeasure,
)


@admin.register(Stock, StockMovement)
class StockLedgerAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register((
    Product, ProductCategory, PurchaseOrder, PurchaseOrderItem, Recipe, RecipeIngredient,
    StockLocation, Supplier, UnitOfMeasure,
))
