from django.contrib import admin

from apps.workspaces.admin import WorkspaceOrderAdmin

from .models import BarOrder, BarTable, Drink, DrinkCategory


@admin.register(BarOrder)
class BarOrderAdmin(WorkspaceOrderAdmin):
    workspace = 'bar'
    entity = 'barorder'


admin.site.register((DrinkCategory, Drink, BarTable))
