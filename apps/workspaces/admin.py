from django.contrib import admin
from django.shortcuts import redirect


class WorkspaceOrderAdmin(admin.ModelAdmin):
    workspace = ''
    entity = ''

    def add_view(self, request, form_url='', extra_context=None):
        return redirect(f'workspaces:{self.workspace}_order_create')

    def change_view(self, request, object_id, form_url='', extra_context=None):
        return redirect('entity_detail', self.model._meta.app_label, self.entity, object_id)

    def has_delete_permission(self, request, obj=None):
        return False
