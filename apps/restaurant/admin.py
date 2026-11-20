from django.contrib import admin

from apps.workspaces.admin import WorkspaceOrderAdmin

from .models import Menu, MenuItem, Order, RestaurantReservation, Table


@admin.register(Order)
class OrderAdmin(WorkspaceOrderAdmin):
    workspace = 'service'
    entity = 'order'


admin.site.register((Table, Menu, MenuItem, RestaurantReservation))
