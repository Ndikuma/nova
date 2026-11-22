from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models


class User(AbstractUser):
    employee_id = models.CharField(max_length=30, unique=True, null=True, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    job_title = models.CharField(max_length=120, blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    created_by = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='created_users', editable=False,
    )
    updated_by = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='updated_users', editable=False,
    )

    def __str__(self):
        return self.get_full_name() or self.username


class Customer(models.Model):
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30)
    identity_number = models.CharField("Numéro de pièce d’identité", max_length=80, blank=True)
    nationality = models.CharField("Nationalité", max_length=80, blank=True)
    address = models.TextField(blank=True)
    tax_id = models.CharField(max_length=60, blank=True)
    notes = models.TextField(blank=True)
    is_walk_in = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['last_name', 'first_name']
        indexes = [
            models.Index(fields=['last_name', 'first_name']),
            models.Index(fields=['phone']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['is_walk_in'], condition=models.Q(is_walk_in=True), name='customer_single_walk_in'),
        ]

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', editable=False,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', editable=False,
    )

    def __str__(self):
        return f'{self.first_name} {self.last_name}'.strip()


class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=120)
    object_type = models.CharField(max_length=120)
    object_id = models.CharField(max_length=80)
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.JSONField(default=dict, blank=True)

    def __str__(self):
        actor = self.user or 'Système'
        return f'{self.action} · {self.object_type} #{self.object_id} · {actor}'


class HousekeepingStaff(models.Model):
    """Agent housekeeping terrain, sans accès plateforme."""
    first_name = models.CharField('Prénom', max_length=80)
    last_name = models.CharField('Nom', max_length=80, blank=True)
    phone = models.CharField('Téléphone', max_length=30, blank=True)
    role_title = models.CharField('Rôle / fonction', max_length=80, default='Agent housekeeping')
    active = models.BooleanField('Actif', default=True)
    notes = models.TextField('Notes', blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='created_housekeeping_staff', editable=False,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='updated_housekeeping_staff', editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['first_name', 'last_name']
        verbose_name = 'Agent housekeeping'
        verbose_name_plural = 'Agents housekeeping'

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    def __str__(self):
        return self.full_name


class CompanyProfile(models.Model):
    """Profil de l'établissement — singleton éditable depuis l'administration."""

    name = models.CharField("Nom de l'établissement", max_length=120, default='Nova Hospitality')
    short_name = models.CharField('Nom court', max_length=40, default='NOVA')
    initials = models.CharField('Initiales', max_length=8, default='N')
    tagline = models.CharField('Slogan', max_length=160, default='Hospitality suite')
    legal_name = models.CharField('Raison sociale', max_length=160, blank=True, default='')
    description = models.TextField(
        'Description',
        blank=True,
        default='Réception, chambres, restaurant, bar, inventaire et finances dans un seul espace.',
    )
    logo = models.ImageField('Logo', upload_to='company/', blank=True, null=True)

    website = models.URLField('Site web', blank=True, default='')
    phone = models.CharField('Téléphone', max_length=40, blank=True, default='')
    phone_secondary = models.CharField('Téléphone secondaire', max_length=40, blank=True, default='')
    whatsapp_number = models.CharField(
        'WhatsApp', max_length=16, blank=True,
        help_text='Numéro WhatsApp de la réception au format international, avec + et sans espace.',
        validators=[RegexValidator(r'^\+[1-9][0-9]{5,14}\Z', 'Saisissez un numéro international, par exemple +257XXXXXXXX.')],
    )
    email = models.EmailField('E-mail', blank=True, default='')
    support_email = models.EmailField('E-mail support', blank=True, default='')

    address_override = models.CharField('Adresse (ligne libre)', max_length=255, blank=True, default='')
    address_line1 = models.CharField('Adresse ligne 1', max_length=120, blank=True, default='')
    address_line2 = models.CharField('Adresse ligne 2', max_length=120, blank=True, default='')
    city = models.CharField('Ville', max_length=80, blank=True, default='')
    province = models.CharField('Province / région', max_length=80, blank=True, default='')
    postal_code = models.CharField('Code postal', max_length=20, blank=True, default='')
    country = models.CharField('Pays', max_length=80, blank=True, default='')

    tax_id = models.CharField('NIF / TIN', max_length=60, blank=True, default='')
    trade_number = models.CharField('RCCM', max_length=60, blank=True, default='')
    registration_number = models.CharField("Numéro d'enregistrement", max_length=60, blank=True, default='')

    bank_name = models.CharField('Banque', max_length=120, blank=True, default='')
    bank_account = models.CharField('Compte bancaire', max_length=120, blank=True, default='')
    bank_swift = models.CharField('SWIFT / BIC', max_length=60, blank=True, default='')

    currency = models.CharField('Devise', max_length=10, default='BIF')
    currency_symbol = models.CharField('Symbole devise', max_length=10, blank=True, default='FBu')

    document_footer = models.CharField(
        'Pied de page documents', max_length=255, blank=True,
        default='Merci de votre confiance. Document généré par Nova Hospitality.',
    )
    invoice_footer = models.CharField(
        'Pied de page facture', max_length=255, blank=True,
        default='Merci de votre confiance. Conservez cette facture comme preuve de paiement.',
    )
    receipt_footer = models.CharField(
        'Pied de page reçu', max_length=255, blank=True,
        default='Ce reçu est généré automatiquement. Conservez-le comme preuve de paiement.',
    )

    public_hero_title = models.CharField(
        "Titre d'accueil (site public)", max_length=160, blank=True, default='',
    )
    public_hero_subtitle = models.TextField(
        "Sous-titre d'accueil (site public)", blank=True, default='',
    )
    public_about = models.TextField('À propos (site public)', blank=True)

    obr_ebms_enabled = models.BooleanField(
        'Activer OBR eBMS',
        default=False,
        help_text=(
            "Autorise l’utilisation du module OBR eBMS pour cet établissement "
            "(affichage, configuration et transmissions fiscales). Réservé au super administrateur."
        ),
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Profil de l'établissement"
        verbose_name_plural = "Profil de l'établissement"

    def __str__(self):
        return self.name or "Profil de l'établissement"

    @classmethod
    def load(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def logo_url(self):
        if self.logo:
            try:
                return self.logo.url
            except Exception:
                return ''
        return ''

    @property
    def public_description(self):
        if self.public_hero_subtitle:
            return self.public_hero_subtitle
        if self.description and self.description != self._meta.get_field('description').get_default():
            return self.description
        return 'Découvrez nos chambres, notre restaurant et notre bar.'

    @property
    def address(self):
        if self.address_override:
            return self.address_override
        city_line = ' '.join(part for part in (self.postal_code, self.city) if part)
        return ', '.join(
            part for part in (
                self.address_line1, self.address_line2, city_line,
                self.province, self.country,
            ) if part
        )

    @property
    def full_address(self):
        return self.address

    @property
    def contact_line(self):
        return ' · '.join(part for part in (self.phone, self.phone_secondary, self.email, self.website) if part)

    @property
    def whatsapp_url(self):
        return f'https://wa.me/{self.whatsapp_number.removeprefix("+")}' if self.whatsapp_number else ''

    @property
    def phone_line(self):
        return ' · '.join(part for part in (self.phone, self.phone_secondary) if part)

    @property
    def bank_line(self):
        details = []
        if self.bank_name:
            details.append(f'Banque : {self.bank_name}')
        if self.bank_account:
            details.append(f'Compte : {self.bank_account}')
        if self.bank_swift:
            details.append(f'SWIFT : {self.bank_swift}')
        return ' · '.join(details)

    @property
    def legal_line(self):
        details = []
        if self.tax_id:
            details.append(f'NIF/TIN : {self.tax_id}')
        if self.trade_number:
            details.append(f'RCCM : {self.trade_number}')
        if self.registration_number:
            details.append(f'Registre : {self.registration_number}')
        return ' · '.join(details)

    @property
    def theme_light(self):
        return {
            '--bg': '#f4f6f9', '--surface': '#ffffff', '--surface-2': '#f6f8fb',
            '--surface-3': '#eceff5', '--border': '#e2e7ef', '--border-strong': '#ccd5e1',
            '--text': '#15202f', '--text-soft': '#556172', '--text-faint': '#8794a6',
            '--brand': '#1f4d7a', '--brand-strong': '#16436c', '--brand-soft': '#e7eef7',
            '--accent': '#b3873f', '--accent-soft': '#f8f0e2',
            '--danger': '#d64545', '--danger-soft': '#fdecec',
            '--warn': '#b45309', '--warn-soft': '#fbf0e0',
            '--ok': '#15803d', '--ok-soft': '#e5f4ea',
            '--on-brand': '#ffffff', '--white': '#ffffff', '--black': '#000000',
        }

    @property
    def theme_dark(self):
        return {
            '--bg': '#0c111b', '--surface': '#141c28', '--surface-2': '#1a2432',
            '--surface-3': '#212d3e', '--border': '#2b3648', '--border-strong': '#3a4759',
            '--text': '#e7ecf3', '--text-soft': '#a3afc0', '--text-faint': '#717f93',
            '--brand': '#3f83c8', '--brand-strong': '#6aa4dc', '--brand-soft': '#16273b',
            '--accent': '#d3a463', '--accent-soft': '#2c2416',
            '--danger': '#f27a7a', '--danger-soft': '#2c1a1c',
            '--warn': '#f0b45f', '--warn-soft': '#2c2416',
            '--ok': '#52c47f', '--ok-soft': '#16281d',
            '--on-brand': '#ffffff', '--white': '#ffffff', '--black': '#000000',
        }

    @property
    def theme_color(self):
        return self.theme_light['--brand']

    @property
    def print_colors(self):
        return {
            'bg': '#eef2f6', 'paper': '#ffffff', 'ink': '#0f172a',
            'muted': '#5b6b7c', 'border': '#dbe3ea', 'soft': '#f4f7fa',
            'page': '#7a8a99', 'cell': '#24332e',
        }
