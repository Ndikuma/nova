from django.contrib import admin

from .models import GeneratedReport


@admin.register(GeneratedReport)
class GeneratedReportAdmin(admin.ModelAdmin):
    list_display = ('report_type', 'file_format', 'status', 'row_count', 'file_size', 'created_by', 'created_at')
    list_filter = ('status', 'file_format', 'report_type')
    search_fields = ('report_type', 'created_by__username')
    readonly_fields = ('completed_at', 'created_at', 'file_size', 'row_count')
