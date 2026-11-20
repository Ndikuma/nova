from django.contrib import admin

from .models import (
    EBMSConfiguration, EBMSInvoice, EBMSInvoiceItem, EBMSProductMapping,
    EBMSStockMovement, OBRSyncLog,
)


@admin.register(EBMSConfiguration)
class EBMSConfigurationAdmin(admin.ModelAdmin):
    list_display = ('taxpayer_name', 'taxpayer_tin', 'enabled', 'auto_submit_invoices',
                    'auto_submit_stock', 'is_sandbox')


@admin.register(EBMSProductMapping)
class EBMSProductMappingAdmin(admin.ModelAdmin):
    list_display = ('product', 'eligibility', 'item_code', 'measurement_unit')
    list_filter = ('eligibility',)
    search_fields = ('product__name', 'product__sku', 'item_code')


admin.site.register(EBMSInvoice)
admin.site.register(EBMSInvoiceItem)
admin.site.register(EBMSStockMovement)
admin.site.register(OBRSyncLog)
