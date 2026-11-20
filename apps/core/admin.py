from django.contrib import admin
from django.shortcuts import redirect

from .models import AuditLog, CompanyProfile, Customer, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'get_full_name', 'email', 'job_title', 'is_active', 'is_staff')
    search_fields = ('username', 'first_name', 'last_name', 'email', 'employee_id')
    list_filter = ('is_active', 'is_staff', 'groups')


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'phone', 'email', 'city_line', 'created_at')
    search_fields = ('first_name', 'last_name', 'phone', 'email')
    list_filter = ('created_at',)

    @admin.display(description='Adresse')
    def city_line(self, obj):
        return obj.address or '—'


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action', 'object_type', 'object_id')
    list_filter = ('action', 'object_type', 'timestamp')
    search_fields = ('action', 'object_type', 'object_id', 'user__username')
    readonly_fields = ('user', 'action', 'object_type', 'object_id', 'timestamp', 'details')


@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Identité de l'établissement", {
            'fields': ('name', 'short_name', 'initials', 'tagline', 'legal_name', 'description', 'logo')
        }),
        ('Accueil du site public', {
            'fields': ('public_hero_title', 'public_hero_subtitle', 'public_about')
        }),
        ('Contact', {
            'fields': ('website', 'phone', 'phone_secondary', 'whatsapp_number', 'email', 'support_email')
        }),
        ('Adresse', {
            'fields': ('address_override', 'address_line1', 'address_line2', 'city', 'province', 'postal_code', 'country')
        }),
        ('Informations légales & bancaires', {
            'fields': ('tax_id', 'trade_number', 'registration_number', 'bank_name', 'bank_account', 'bank_swift')
        }),
        ('Fiscalité électronique (OBR eBMS)', {
            'description': "Activation du module de facturation électronique OBR eBMS pour l’établissement. Ce réglage est géré par le super administrateur.",
            'fields': ('obr_ebms_enabled',),
        }),
        ('Devise & documents', {
            'fields': ('currency', 'currency_symbol', 'document_footer', 'invoice_footer', 'receipt_footer')
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            readonly.append('obr_ebms_enabled')
        return readonly

    def has_add_permission(self, request):
        if CompanyProfile.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        try:
            obj = CompanyProfile.load()
            return redirect(f'../../core/companyprofile/{obj.pk}/change/')
        except Exception:
            return super().changelist_view(request, extra_context=extra_context)
