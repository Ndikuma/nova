from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SyncStatus(models.TextChoices):
    NOT_REQUIRED = 'not_required', 'Non requis'
    BLOCKED = 'blocked', 'Bloqué'
    PENDING = 'pending', 'En attente'
    PROCESSING = 'processing', 'En cours'
    SENT = 'sent', 'Envoyé'
    FAILED = 'failed', 'Échec'
    CANCELLED = 'cancelled', 'Annulé'


class EBMSConfiguration(TimeStampedModel):
    """Configuration OBR eBMS de l'établissement (enregistrement unique)."""

    enabled = models.BooleanField(
        default=False, help_text='Active la création des envois eBMS.',
    )
    auto_submit_invoices = models.BooleanField(
        default=False, help_text='Envoie automatiquement les factures à OBR.',
    )
    auto_submit_stock = models.BooleanField(
        default=False, help_text='Envoie automatiquement les mouvements de stock à OBR.',
    )

    base_url = models.URLField(
        default='https://ebms.obr.bi:9443/ebms_api/',
        help_text='URL de base de l’API OBR eBMS.',
    )
    username = models.CharField(max_length=120, blank=True)
    password = models.CharField(max_length=255, blank=True)

    taxpayer_type = models.CharField(
        max_length=1,
        choices=[('1', 'Personne physique'), ('2', 'Personne morale')],
        default='2',
    )
    taxpayer_name = models.CharField(max_length=180, blank=True)
    taxpayer_tin = models.CharField(max_length=30, blank=True)
    trade_number = models.CharField(max_length=40, blank=True)
    phone_number = models.CharField(max_length=30, blank=True)

    address = models.TextField(blank=True)
    vat_taxpayer = models.BooleanField(default=False)
    consumption_taxpayer = models.BooleanField(default=False)
    tourism_levy_taxpayer = models.BooleanField(default=False)

    fiscal_center = models.CharField(max_length=80, default='DGC')
    activity_sector = models.CharField(max_length=250, blank=True)
    legal_form = models.CharField(max_length=80, blank=True)
    default_customer_name = models.CharField(max_length=100, default='Client comptoir')
    default_measurement_unit = models.CharField(max_length=20, default='PCE')

    default_item_code = models.CharField(max_length=30, blank=True)
    hotel_item_code = models.CharField(max_length=30, blank=True)
    restaurant_item_code = models.CharField(max_length=30, blank=True)
    bar_item_code = models.CharField(max_length=30, blank=True)
    inventory_item_code = models.CharField(max_length=30, blank=True)

    default_vat_rate = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal('0'))
    default_consumption_tax_rate = models.DecimalField(
        max_digits=6, decimal_places=3, default=Decimal('0'),
    )
    default_tourism_levy_rate = models.DecimalField(
        max_digits=6, decimal_places=3, default=Decimal('0'),
    )
    default_special_tax_rate = models.DecimalField(
        max_digits=6, decimal_places=3, default=Decimal('0'),
    )
    default_other_tax_rate = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal('0'))

    max_attempts = models.PositiveSmallIntegerField(default=5)
    request_timeout_seconds = models.PositiveSmallIntegerField(default=30)

    class Meta:
        verbose_name = 'Configuration OBR eBMS'
        verbose_name_plural = 'Configuration OBR eBMS'

    @classmethod
    def load(cls):
        configuration, _created = cls.objects.get_or_create(pk=1)
        return configuration

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)

    @property
    def is_sandbox(self):
        return 'sandbox' in self.base_url or '9443' in self.base_url

    @property
    def is_ready(self):
        return bool(self.enabled and self.username and self.password and self.taxpayer_tin)

    def clean(self):
        super().clean()
        errors = {}
        if (self.auto_submit_invoices or self.auto_submit_stock) and not self.enabled:
            errors['enabled'] = 'Activez eBMS avant l’envoi automatique.'
        if self.max_attempts < 1:
            errors['max_attempts'] = 'Le nombre de tentatives doit être au moins 1.'
        if self.request_timeout_seconds < 1:
            errors['request_timeout_seconds'] = 'Le délai doit être au moins 1 seconde.'
        for field in (
            'default_vat_rate', 'default_consumption_tax_rate', 'default_tourism_levy_rate',
            'default_special_tax_rate', 'default_other_tax_rate',
        ):
            value = getattr(self, field)
            if value is not None and value < 0:
                errors[field] = 'Le taux ne peut pas être négatif.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        name = self.taxpayer_name or 'OBR eBMS'
        tin = self.taxpayer_tin or 'non configuré'
        state = 'activé' if self.enabled else 'désactivé'
        return f'{name} · NIF {tin} · {state}'


class EBMSProductMapping(TimeStampedModel):
    """Classification fiscale d’un produit d’inventaire."""

    class Eligibility(models.TextChoices):
        REQUIRED = 'required', 'Fiscalisation requise'
        EXEMPT = 'exempt', 'Exonéré mais déclarable'
        EXCLUDED = 'excluded', 'Exclu eBMS'
        REVIEW = 'review', 'À vérifier'

    product = models.OneToOneField(
        'inventory.Product', on_delete=models.CASCADE, related_name='ebms_mapping',
    )
    eligibility = models.CharField(
        max_length=16, choices=Eligibility.choices, default=Eligibility.REVIEW,
    )
    item_code = models.CharField(max_length=30, blank=True, db_index=True)
    item_designation = models.CharField(max_length=500, blank=True)
    measurement_unit = models.CharField(max_length=20, blank=True)
    vat_rate = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal('0'))
    consumption_tax_rate = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal('0'))
    tourism_levy_rate = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal('0'))
    special_tax_rate = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal('0'))
    other_tax_rate = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal('0'))
    exemption_reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    verified_by = models.ForeignKey(
        'core.User', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['product__name']

    @property
    def ready(self):
        if self.eligibility == self.Eligibility.EXCLUDED:
            return True
        return bool(self.item_code and self.eligibility != self.Eligibility.REVIEW)

    def __str__(self):
        code = f' · {self.item_code}' if self.item_code else ''
        return f'{self.product} · {self.get_eligibility_display()}{code}'


class EBMSInvoice(TimeStampedModel):
    class Type(models.TextChoices):
        NORMAL = 'FN', 'Facture normale'
        CREDIT_NOTE = 'FA', 'Note de crédit'
        DEPOSIT_REFUND = 'RC', 'Remboursement d’acompte'
        OFF_INVOICE_REDUCTION = 'RHF', 'Réduction hors facture'

    invoice = models.OneToOneField(
        'finance.Invoice', on_delete=models.PROTECT, related_name='ebms_invoice',
    )
    invoice_number = models.CharField(max_length=40)
    invoice_identifier = models.CharField(max_length=120, unique=True)
    invoice_date = models.DateTimeField()
    invoice_type = models.CharField(max_length=5, choices=Type.choices, default=Type.NORMAL)
    customer_name = models.CharField(max_length=100)
    customer_tin = models.CharField(max_length=50, blank=True)
    customer_address = models.CharField(max_length=180, blank=True)
    vat_customer = models.BooleanField(default=False)
    invoice_reference = models.CharField(max_length=40, blank=True)
    credit_note_reason = models.CharField(max_length=500, blank=True)
    cancelled_invoice_reference = models.CharField(max_length=40, blank=True)
    currency = models.CharField(max_length=5, default='BIF')
    status = models.CharField(
        max_length=20, choices=SyncStatus.choices, default=SyncStatus.PENDING, db_index=True,
    )
    obr_registered_number = models.CharField(max_length=80, blank=True)
    obr_registered_date = models.DateTimeField(null=True, blank=True)
    electronic_signature = models.TextField(blank=True)
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    validation_errors = models.JSONField(default=list, blank=True)
    error_message = models.TextField(blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_attempt = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Facture OBR eBMS'
        verbose_name_plural = 'Factures OBR eBMS'

    @property
    def total_amount(self):
        return sum((item.total_amount for item in self.items.all()), Decimal('0'))

    @property
    def is_registered(self):
        return bool(self.obr_registered_number)

    @property
    def can_retry(self):
        return self.status in {SyncStatus.PENDING, SyncStatus.FAILED}

    def __str__(self):
        return (
            f'Facture OBR {self.invoice_number} · {self.customer_name} · '
            f'{self.get_status_display()}'
        )


class EBMSInvoiceItem(models.Model):
    invoice = models.ForeignKey(EBMSInvoice, on_delete=models.CASCADE, related_name='items')
    invoice_item = models.OneToOneField(
        'finance.InvoiceItem', on_delete=models.PROTECT,
        related_name='ebms_item', null=True, blank=True,
    )
    designation = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    item_price = models.DecimalField(max_digits=20, decimal_places=4)
    consumption_tax = models.DecimalField(max_digits=20, decimal_places=4, default=Decimal('0'))
    tourism_levy = models.DecimalField(max_digits=20, decimal_places=4, default=Decimal('0'))
    special_tax = models.DecimalField(max_digits=20, decimal_places=4, default=Decimal('0'))
    other_tax = models.DecimalField(max_digits=20, decimal_places=4, default=Decimal('0'))
    price_without_vat = models.DecimalField(max_digits=20, decimal_places=4)
    vat = models.DecimalField(max_digits=20, decimal_places=4, default=Decimal('0'))
    price_with_vat = models.DecimalField(max_digits=20, decimal_places=4)
    total_amount = models.DecimalField(max_digits=20, decimal_places=4)
    item_code = models.CharField(max_length=30)
    measurement_unit = models.CharField(max_length=20)

    def __str__(self):
        return f'{self.designation} × {self.quantity} {self.measurement_unit}'


class EBMSStockMovement(TimeStampedModel):
    class Type(models.TextChoices):
        ENTRY_NORMAL = 'EN', 'Entrée normale'
        ENTRY_RETURN = 'ER', 'Retour marchandise'
        ENTRY_INVENTORY = 'EI', 'Entrée inventaire'
        ENTRY_ADJUSTMENT = 'EAJ', 'Entrée ajustement'
        ENTRY_TRANSFER = 'ET', 'Entrée transfert'
        ENTRY_OTHER = 'EAU', 'Autre entrée'
        EXIT_NORMAL = 'SN', 'Sortie normale'
        EXIT_LOSS = 'SP', 'Sortie perte'
        EXIT_THEFT = 'SV', 'Sortie vol'
        EXIT_OBSOLETE = 'SD', 'Sortie désuétude'
        EXIT_BREAKAGE = 'SC', 'Sortie casse'
        EXIT_ADJUSTMENT = 'SAJ', 'Sortie ajustement'
        EXIT_TRANSFER = 'ST', 'Sortie transfert'
        EXIT_OTHER = 'SAU', 'Autre sortie'

    stock_movement = models.OneToOneField(
        'inventory.StockMovement', on_delete=models.PROTECT, related_name='ebms_movement',
    )
    movement_type = models.CharField(max_length=5, choices=Type.choices)
    movement_date = models.DateTimeField()
    description = models.CharField(max_length=500, blank=True)
    invoice_reference = models.CharField(max_length=40, blank=True)
    status = models.CharField(
        max_length=20, choices=SyncStatus.choices, default=SyncStatus.PENDING, db_index=True,
    )
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    validation_errors = models.JSONField(default=list, blank=True)
    error_message = models.TextField(blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_attempt = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Mouvement de stock OBR eBMS'
        verbose_name_plural = 'Mouvements de stock OBR eBMS'

    @property
    def can_retry(self):
        return self.status in {SyncStatus.PENDING, SyncStatus.FAILED}

    def __str__(self):
        return (
            f'{self.get_movement_type_display()} · '
            f'{self.stock_movement.product} · {self.get_status_display()}'
        )


class OBRSyncLog(models.Model):
    class Action(models.TextChoices):
        LOGIN = 'login', 'Connexion'
        ADD_INVOICE = 'add_invoice', 'Envoi facture'
        GET_INVOICE = 'get_invoice', 'Consultation facture'
        CANCEL_INVOICE = 'cancel_invoice', 'Annulation facture'
        CHECK_TIN = 'check_tin', 'Vérification NIF'
        ADD_STOCK = 'add_stock_movement', 'Envoi mouvement de stock'

    action = models.CharField(max_length=30, choices=Action.choices)
    reference = models.CharField(max_length=120, blank=True)
    success = models.BooleanField(default=False)
    request_payload = models.JSONField(null=True, blank=True)
    response_payload = models.JSONField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    performed_by = models.ForeignKey(
        'core.User', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Journal OBR eBMS'
        verbose_name_plural = 'Journal OBR eBMS'

    def __str__(self):
        reference = f' · {self.reference}' if self.reference else ''
        state = 'OK' if self.success else 'Échec'
        return f'{self.get_action_display()}{reference} · {state}'


def configuration():
    return EBMSConfiguration.load()


def ebms_enabled():
    config = configuration()
    return bool(config.enabled)
