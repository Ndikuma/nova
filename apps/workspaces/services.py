"""Business workflows shared by the role workspaces.

Everything here builds on the models and services that already exist in the
hotel / restaurant / bar / finance / inventory apps.  No parallel business
logic is introduced: invoices keep using ``finance.services.record_payment``
and stock signals reuse the audit trail instead of silently changing stock.
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.bar.models import BarOrder, BarTable
from apps.core.models import AuditLog, Customer
from apps.finance.models import Invoice, InvoiceItem
from apps.finance.services import record_payment
from apps.hotel.models import HousekeepingTask, Reservation, Stay
from apps.restaurant.models import Order, Table


ZERO = Decimal('0')


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def log_action(user, action, obj=None, *, object_type=None, object_id='', details=None):
    """Write a traceable audit entry for an operational workspace action."""
    return AuditLog.objects.create(
        user=user if getattr(user, 'is_authenticated', False) else None,
        action=action,
        object_type=object_type or (obj.__class__.__name__ if obj is not None else 'Système'),
        object_id=str(object_id or (getattr(obj, 'pk', '') or '')),
        details=details or {},
    )


# ---------------------------------------------------------------------------
# Invoice helpers
# ---------------------------------------------------------------------------

def _marker(kind, pk):
    return f'[{kind}:{pk}]'


def _find_by_marker(kind, pk):
    return Invoice.objects.filter(notes__contains=_marker(kind, pk)).order_by('-issued_at').first()


def _unique_invoice_number(prefix, pk):
    now = timezone.now()
    candidate = f'FAC-{prefix}-{pk}-{now:%y%m%d%H%M%S%f}'
    while Invoice.objects.filter(number=candidate).exists():
        now = timezone.now()
        candidate = f'FAC-{prefix}-{pk}-{now:%y%m%d%H%M%S%f}'
    return candidate


def find_reservation_invoice(reservation):
    """Return the invoice already attached to a reservation, if any."""
    invoice = _find_by_marker('RESERVATION', reservation.pk)
    if invoice:
        return invoice
    return (
        Invoice.objects.filter(
            customer=reservation.customer,
            total_amount=reservation.estimated_total,
            status__in=['ISSUED', 'PARTIAL', 'PAID'],
        )
        .exclude(notes__contains='[RESERVATION:')
        .order_by('-issued_at')
        .first()
    )


def find_order_invoice(order):
    return _find_by_marker('ORDER', order.pk)


def find_bar_invoice(order):
    return _find_by_marker('BAR', order.pk)


@transaction.atomic
def invoice_for_reservation(reservation, user):
    """Create (or recover) the departure invoice for a hotel stay."""
    marker = _marker('RESERVATION', reservation.pk)
    existing = _find_by_marker('RESERVATION', reservation.pk)
    if existing:
        return existing

    legacy = (
        Invoice.objects.filter(
            customer=reservation.customer,
            total_amount=reservation.estimated_total,
            status__in=['ISSUED', 'PARTIAL', 'PAID'],
        )
        .exclude(notes__contains='[RESERVATION:')
        .order_by('-issued_at')
        .first()
    )
    if legacy and reservation.estimated_total > ZERO:
        legacy.notes = (legacy.notes + '\n' if legacy.notes else '') + marker
        legacy.save(update_fields=['notes'])
        log_action(
            user, 'Rattachement de facture au séjour', reservation,
            details={'invoice': legacy.number, 'marker': marker},
        )
        return legacy

    total = reservation.estimated_total or ZERO
    invoice = Invoice.objects.create(
        customer=reservation.customer,
        number=_unique_invoice_number('SEJ', reservation.pk),
        status='ISSUED',
        total_amount=total,
        notes=f'Séjour #{reservation.pk}\n{marker}',
    )
    if total > ZERO:
        InvoiceItem.objects.create(
            invoice=invoice,
            description=(
                f'Séjour · chambre {reservation.room} · '
                f'{reservation.check_in:%d/%m/%Y} → {reservation.check_out:%d/%m/%Y}'
            ),
            quantity=1,
            unit_price=total,
            tax=ZERO,
            source_service='Hôtel',
            source_reference=f'RESERVATION-{reservation.pk}',
        )
    log_action(
        user, 'Préparation de la facture de séjour', reservation,
        details={'invoice': invoice.number, 'total': str(total)},
    )
    return invoice


def invoice_for_order(order, user):
    return _invoice_for_sale(order, user, 'ORDER', 'REST', 'Restaurant', 'menu_item')


def invoice_for_bar_order(order, user):
    return _invoice_for_sale(order, user, 'BAR', 'BAR', 'Bar', 'drink')


@transaction.atomic
def _invoice_for_sale(order, user, kind, prefix, service, product_field):
    order = type(order).objects.select_for_update().get(pk=order.pk)
    existing = _find_by_marker(kind, order.pk)
    if existing:
        return existing
    if order.status in ('OPEN', 'CANCELLED', 'PAID'):
        raise ValueError('Cette commande ne peut pas être facturée à ce stade.')

    items = list(order.items.select_related(product_field).order_by('pk'))
    total = sum((item.subtotal for item in items), ZERO)
    if total <= ZERO:
        raise ValueError('Ajoutez des articles payants avant de préparer l’addition.')
    if total > Decimal('9999999999.99'):
        raise ValueError('Le total dépasse le montant pris en charge.')

    customer = order.customer
    if customer is None:
        customer, _ = Customer.objects.get_or_create(
            is_walk_in=True, defaults={'first_name': 'Client', 'last_name': 'de passage', 'phone': ''},
        )
    invoice = Invoice.objects.create(
        customer=customer,
        number=_unique_invoice_number(prefix, order.pk),
        status='ISSUED',
        total_amount=total,
        notes=f'Commande {service.lower()} #{order.pk}\n{_marker(kind, order.pk)}',
    )
    for item in items:
        InvoiceItem.objects.create(
            invoice=invoice,
            description=getattr(item, product_field).name,
            quantity=item.quantity,
            unit_price=item.unit_price,
            tax=ZERO,
            source_service=service,
            source_reference=f'{kind}-{order.pk}',
        )
    if order.total_amount != total:
        order.total_amount = total
        order.save(update_fields=['total_amount'])
    log_action(
        user, f'Transmission de l’addition {service.lower()}', order,
        details={'invoice': invoice.number, 'total': str(total)},
    )
    return invoice


@transaction.atomic
def settle_invoice_sources(invoice):
    """When an invoice is fully paid, close the related restaurant/bar orders."""
    if invoice.status != 'PAID':
        return
    for item in invoice.items.all():
        service = (item.source_service or '').strip().lower()
        reference = item.source_reference or ''
        if service == 'restaurant' and reference.startswith('ORDER-'):
            order = Order.objects.filter(pk=_safe_int(reference.split('-', 1)[1])).first()
            if order and order.status != 'PAID':
                order.status = 'PAID'
                order.save(update_fields=['status'])
                _release_restaurant_table(order)
        elif service == 'bar' and reference.startswith('BAR-'):
            order = BarOrder.objects.filter(pk=_safe_int(reference.split('-', 1)[1])).first()
            if order and order.status != 'PAID':
                order.status = 'PAID'
                order.save(update_fields=['status'])
                _release_bar_table(order)


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _release_restaurant_table(order):
    if not order.table_id:
        return
    table = Table.objects.select_for_update().get(pk=order.table_id)
    if table.status != 'OCCUPIED':
        return
    still_open = Order.objects.filter(table=table).exclude(
        status__in=['PAID', 'CANCELLED']
    ).exists()
    if not still_open:
        table.status = 'AVAILABLE'
        table.save(update_fields=['status'])


def _release_bar_table(order):
    if not order.table_id:
        return
    table = BarTable.objects.select_for_update().get(pk=order.table_id)
    still_open = BarOrder.objects.filter(table=table).exclude(
        status__in=['PAID', 'CANCELLED']
    ).exists()
    if not still_open and table.status == 'OCCUPIED':
        table.status = 'AVAILABLE'
        table.save(update_fields=['status'])


# ---------------------------------------------------------------------------
# Hotel workflows
# ---------------------------------------------------------------------------

@transaction.atomic
def check_in_reservation(reservation, user):
    if reservation.status != 'CONFIRMED':
        raise ValueError('Seule une réservation confirmée peut être enregistrée à l’arrivée.')
    reservation.status = 'CHECKED_IN'
    reservation.save(update_fields=['status'])
    stay, created = Stay.objects.get_or_create(
        reservation=reservation,
        defaults={
            'room': reservation.room,
            'actual_check_in': timezone.now(),
            'status': 'ACTIVE',
            'responsible_receptionist': user,
        },
    )
    if not created and stay.status != 'ACTIVE':
        stay.status = 'ACTIVE'
        stay.actual_check_in = stay.actual_check_in or timezone.now()
        stay.actual_check_out = None
        stay.responsible_receptionist = user
        stay.save(update_fields=['status', 'actual_check_in', 'actual_check_out',
                                 'responsible_receptionist'])
    log_action(
        user, 'Check-in effectué', reservation,
        details={'room': str(reservation.room), 'stay': stay.pk},
    )
    return stay


def prepare_checkout(reservation, user):
    if reservation.status != 'CHECKED_IN':
        raise ValueError('Le départ ne peut être préparé que pour un séjour en cours.')
    invoice = invoice_for_reservation(reservation, user)
    log_action(
        user, 'Check-out préparé', reservation,
        details={'invoice': invoice.number, 'balance': str(invoice.balance)},
    )
    return invoice


@transaction.atomic
def complete_checkout(reservation, user):
    if reservation.status != 'CHECKED_IN':
        raise ValueError('Ce séjour n’est pas en cours.')
    invoice = find_reservation_invoice(reservation)
    if reservation.estimated_total > ZERO and invoice is None:
        raise ValueError('Préparez d’abord la facture de départ.')
    if invoice and invoice.balance > ZERO:
        raise ValueError(
            f'Le solde de {invoice.balance} F doit être encaissé avant la clôture du séjour.'
        )

    stay = Stay.objects.filter(reservation=reservation, status='ACTIVE').first()
    now = timezone.now()
    if stay:
        stay.status = 'COMPLETED'
        stay.actual_check_out = now
        stay.save(update_fields=['status', 'actual_check_out'])
    reservation.status = 'CHECKED_OUT'
    reservation.save(update_fields=['status'])
    HousekeepingTask.objects.get_or_create(
        room=reservation.room,
        task_type='CLEANING',
        scheduled_date=timezone.localdate(),
        defaults={'status': 'PENDING'},
    )
    log_action(
        user, 'Check-out finalisé', reservation,
        details={'room': str(reservation.room), 'invoice': getattr(invoice, 'number', '')},
    )
    return reservation


def update_housekeeping(task, status, user):
    allowed = {code for code, _label in HousekeepingTask.STATUS}
    if status not in allowed:
        raise ValueError('Statut de tâche invalide.')
    task.status = status
    if status == 'DONE':
        task.completion_date = timezone.localdate()
    task.save(update_fields=['status', 'completion_date'])
    log_action(
        user, 'Mise à jour housekeeping', task,
        details={'room': str(task.room), 'status': status},
    )
    return task


# ---------------------------------------------------------------------------
# Restaurant / bar orders
# ---------------------------------------------------------------------------

def restaurant_transition(order, action, user):
    """Apply an allowed restaurant order transition and trace it."""
    transitions = {
        'confirm': (('OPEN',), 'CONFIRMED', 'Commande envoyée en cuisine'),
        'start': (('CONFIRMED',), 'PREPARING', 'Préparation démarrée'),
        'ready': (('PREPARING',), 'READY', 'Commande marquée prête'),
        'serve': (('READY',), 'SERVED', 'Commande servie'),
        'cancel': (('OPEN', 'CONFIRMED', 'PREPARING', 'READY'), 'CANCELLED', 'Commande annulée'),
    }
    if action not in transitions:
        raise ValueError('Action inconnue.')
    from_statuses, to_status, label = transitions[action]
    if order.status not in from_statuses:
        raise ValueError('Cette transition n’est pas autorisée pour le statut actuel.')
    order.status = to_status
    order.save(update_fields=['status'])
    if to_status == 'CANCELLED':
        _release_restaurant_table(order)
    log_action(
        user, label, order,
        details={'from': from_statuses, 'to': to_status, 'table': str(order.table or '')},
    )
    return order


def bar_transition(order, action, user):
    transitions = {
        'start': (('OPEN', 'CONFIRMED'), 'PREPARING', 'Commande bar en préparation'),
        'serve': (('PREPARING',), 'SERVED', 'Commande bar servie'),
        'cancel': (('OPEN', 'CONFIRMED', 'PREPARING'), 'CANCELLED', 'Commande bar annulée'),
    }
    if action not in transitions:
        raise ValueError('Action inconnue.')
    from_statuses, to_status, label = transitions[action]
    if order.status not in from_statuses:
        raise ValueError('Cette transition n’est pas autorisée pour le statut actuel.')
    order.status = to_status
    order.save(update_fields=['status'])
    if to_status == 'CANCELLED':
        _release_bar_table(order)
    log_action(
        user, label, order,
        details={'from': from_statuses, 'to': to_status, 'table': str(order.table or '')},
    )
    return order


@transaction.atomic
def attach_order_customer(order, customer, user):
    order = type(order).objects.select_for_update().get(pk=order.pk)
    find_invoice = find_bar_invoice if isinstance(order, BarOrder) else find_order_invoice
    if order.status in ('CANCELLED', 'PAID') or find_invoice(order):
        raise ValueError('Le client de cette commande ne peut plus être modifié.')
    order.customer = customer
    order.save(update_fields=['customer'])
    log_action(
        user, 'Client associé à la commande', order,
        details={'customer': str(customer)},
    )
    return order


# ---------------------------------------------------------------------------
# Finance workflows
# ---------------------------------------------------------------------------

@transaction.atomic
def register_payment(invoice, amount, method, user, reference=''):
    payment = record_payment(
        invoice=invoice, amount=amount, method=method, user=user, reference=reference,
    )
    settle_invoice_sources(invoice)
    log_action(
        user, 'Paiement encaissé', invoice,
        details={
            'payment': payment.pk,
            'amount': str(payment.amount),
            'method': method.name,
        },
    )
    return payment


# ---------------------------------------------------------------------------
# Inventory signals
# ---------------------------------------------------------------------------

def signal_restock(product, user, note='', source=''):
    """Trace a restock need without mutating stock levels."""
    return log_action(
        user, 'Demande de réapprovisionnement', product,
        object_type='Product',
        object_id=product.pk,
        details={
            'product': product.name,
            'sku': product.sku,
            'note': note,
            'source': source,
        },
    )
