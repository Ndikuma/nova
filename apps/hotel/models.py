from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError

from apps.core.models import Customer


class RoomType(models.Model):
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    max_capacity = models.PositiveIntegerField(default=2)
    amenities = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Room(models.Model):
    STATUS = [
        ('AVAILABLE', 'Disponible'),
        ('MAINTENANCE', 'Maintenance'),
        ('OUT_OF_SERVICE', 'Hors service'),
    ]

    number = models.CharField(max_length=20, unique=True)
    floor = models.IntegerField(default=0)
    room_type = models.ForeignKey(RoomType, on_delete=models.PROTECT)
    operational_status = models.CharField(max_length=20, choices=STATUS, default='AVAILABLE')
    description = models.TextField(blank=True)

    def __str__(self):
        return f'Chambre {self.number} · {self.room_type}'


class RoomRate(models.Model):
    room_type = models.ForeignKey(RoomType, on_delete=models.CASCADE)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        start = self.start_date.strftime('%d/%m/%Y') if self.start_date else 'date à définir'
        return f'{self.room_type} · {self.price} · à partir du {start}'


class Reservation(models.Model):
    STATUS = [
        ('DRAFT', 'Brouillon'),
        ('CONFIRMED', 'Confirmée'),
        ('CANCELLED', 'Annulée'),
        ('CHECKED_IN', 'Arrivée'),
        ('CHECKED_OUT', 'Terminée'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    room = models.ForeignKey(Room, on_delete=models.PROTECT)
    check_in = models.DateField()
    check_out = models.DateField()
    adults = models.PositiveIntegerField(default=1)
    children = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS, default='DRAFT')
    estimated_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    contact_information = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['room', 'check_in', 'check_out']),
            models.Index(fields=['status']),
        ]

    def clean(self):
        if self.check_out <= self.check_in:
            raise ValidationError('La date de départ doit être postérieure à l’arrivée.')
        if (
            self.status in ('CONFIRMED', 'CHECKED_IN')
            and Reservation.objects.filter(
                room=self.room, status__in=['CONFIRMED', 'CHECKED_IN'],
            ).exclude(pk=self.pk).filter(
                check_in__lt=self.check_out, check_out__gt=self.check_in,
            ).exists()
        ):
            raise ValidationError('Cette chambre est déjà réservée sur cette période.')

    def __str__(self):
        check_in = self.check_in.strftime('%d/%m/%Y') if self.check_in else '?'
        check_out = self.check_out.strftime('%d/%m/%Y') if self.check_out else '?'
        return (
            f'Réservation #{self.pk or "nouvelle"} · {self.customer} · {self.room} · '
            f'{check_in} → {check_out}'
        )


class BookingRequest(models.Model):
    class ContactMethod(models.TextChoices):
        EMAIL = 'email', 'E-mail'
        PHONE = 'phone', 'Téléphone'
        WHATSAPP = 'whatsapp', 'WhatsApp'

    room_type = models.ForeignKey(RoomType, on_delete=models.PROTECT)
    check_in = models.DateField()
    check_out = models.DateField()
    adults = models.PositiveIntegerField()
    guest_name = models.CharField('Nom complet', max_length=120)
    contact_method = models.CharField('Moyen de contact', max_length=8, choices=ContactMethod.choices, default=ContactMethod.EMAIL)
    email = models.EmailField('Adresse e-mail', blank=True)
    phone = models.CharField('Numéro de téléphone', max_length=24, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    handled_at = models.DateTimeField(null=True, blank=True)
    reservation = models.ForeignKey(
        Reservation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='source_booking_requests', verbose_name='Réservation créée',
    )

    class Meta:
        verbose_name = 'demande de réservation web'
        verbose_name_plural = 'demandes de réservation web'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(check_out__gt=models.F('check_in'), adults__gte=1),
                name='booking_request_valid_stay',
            ),
            models.CheckConstraint(
                condition=(models.Q(contact_method='email', phone='') & ~models.Q(email=''))
                | (models.Q(contact_method='phone', email='') & ~models.Q(phone=''))
                | models.Q(contact_method='whatsapp', email='', phone__startswith='+'),
                name='booking_request_valid_contact',
            ),
            models.UniqueConstraint(
                fields=['room_type', 'check_in', 'check_out', 'adults', 'contact_method', 'email', 'phone'],
                condition=models.Q(handled_at__isnull=True),
                name='booking_request_unique_pending_stay',
            ),
        ]

    def __str__(self):
        return f'Demande web #{self.pk} · {self.room_type}'


class Stay(models.Model):
    STATUS = [('ACTIVE', 'Active'), ('COMPLETED', 'Terminée')]

    reservation = models.OneToOneField(Reservation, on_delete=models.PROTECT)
    actual_check_in = models.DateTimeField(null=True, blank=True)
    actual_check_out = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='ACTIVE')
    responsible_receptionist = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    @property
    def room(self):
        return self.reservation.room

    def __str__(self):
        reservation = self.reservation
        return f'Séjour #{self.pk or "nouveau"} · {reservation.customer} · {reservation.room}'


class HousekeepingTask(models.Model):
    TASK = [
        ('CLEANING', 'Nettoyage'),
        ('INSPECTION', 'Inspection'),
        ('MAINTENANCE', 'Maintenance'),
    ]
    STATUS = [
        ('PENDING', 'À faire'),
        ('IN_PROGRESS', 'En cours'),
        ('DONE', 'Terminée'),
    ]

    room = models.ForeignKey(Room, on_delete=models.PROTECT)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    task_type = models.CharField(max_length=20, choices=TASK)
    status = models.CharField(max_length=20, choices=STATUS, default='PENDING')
    scheduled_date = models.DateField()
    completion_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        scheduled = (
            self.scheduled_date.strftime('%d/%m/%Y')
            if self.scheduled_date else 'date à définir'
        )
        return f'{self.get_task_type_display()} · {self.room} · {scheduled}'
