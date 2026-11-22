from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from types import SimpleNamespace

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from apps.bar.models import BarOrder, BarOrderItem, BarTable, Drink, DrinkCategory
from apps.core.models import Customer
from apps.finance.models import Expense, Invoice, Payment, PaymentMethod
from apps.hotel.models import (
    BookingRequest, HousekeepingTask, Reservation, Room, RoomRate, Stay,
)
from apps.inventory.models import (
    Product, PurchaseOrder, Recipe, Stock, StockMovement, Supplier,
)
from apps.restaurant.catalog import available_dishes, with_ingredients
from apps.restaurant.models import MenuItem, Order, OrderItem, Table

from .forms import (
    AttachCustomerForm, BarOrderForm, PaymentForm, ReservationForm,
    RestockForm, WaiterOrderForm,
)
from .services import (
    active_stay_reservation_for_customer, attach_order_customer, bar_transition,
    charge_order_to_stay, check_in_reservation, complete_checkout,
    find_bar_invoice, find_order_invoice, find_reservation_invoice,
    invoice_for_bar_order, invoice_for_order, invoice_for_reservation,
    log_action, prepare_checkout, register_payment, restaurant_transition,
    signal_restock, update_housekeeping,
)

ZERO = Decimal('0')


# ---------------------------------------------------------------------------
# Role access
# ---------------------------------------------------------------------------

WORKSPACE_HOME = {
    'Superadmin': 'workspaces:superadmin',
    'Owner': 'workspaces:owner',
    'Chef': 'workspaces:kitchen',
    'Receptionist': 'workspaces:reception',
    'Waiter': 'workspaces:service',
    'Cashier': 'workspaces:cashier',
    'Bartender': 'workspaces:bar',
}
ROLE_PRIORITY = ('Superadmin', 'Owner', 'Chef', 'Receptionist', 'Waiter', 'Cashier', 'Bartender')
COLLECT_ROLES = ('Cashier', 'Owner', 'Receptionist', 'Waiter', 'Bartender', 'Chef')


def _groups(user):
    return set(user.groups.values_list('name', flat=True))


def _has_role(user, roles):
    return user.is_superuser or bool(_groups(user).intersection(roles))


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            if not _has_role(request.user, set(roles)):
                raise PermissionDenied('Cet espace de travail n’est pas accessible avec votre rôle.')
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


@login_required
def workspace_home(request):
    if request.user.is_superuser:
        return redirect('workspaces:superadmin')
    user_groups = _groups(request.user)
    for role in ROLE_PRIORITY:
        if role in user_groups:
            return redirect(WORKSPACE_HOME[role])
    return redirect('dashboard')


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _money(value):
    return value or ZERO


def _parse_date(value, fallback):
    parsed = parse_date(value or '')
    return parsed or fallback


def _order_age_minutes(order):
    if not order.created_at:
        return 0
    return max(int((timezone.now() - order.created_at).total_seconds() // 60), 0)


def _paginate(request, queryset, per_page=20):
    return Paginator(queryset, per_page).get_page(request.GET.get('page'))


def _recent_audit_logs(limit=20):
    from apps.core.models import AuditLog
    return AuditLog.objects.select_related('user').order_by('-timestamp')[:limit]


# ---------------------------------------------------------------------------
# Superadmin — global system administration
# ---------------------------------------------------------------------------

@role_required('Superadmin')
def superadmin_workspace(request):
    User = get_user_model()
    users = User.objects.prefetch_related('groups').order_by('-last_login', 'username')
    groups = Group.objects.annotate(member_count=Count('user')).order_by('name')
    logs = list(_recent_audit_logs(20))

    open_orders = Order.objects.exclude(status__in=['PAID', 'CANCELLED']).count()
    open_bar_orders = BarOrder.objects.exclude(status__in=['PAID', 'CANCELLED']).count()
    pending_invoices = Invoice.objects.filter(status__in=['ISSUED', 'PARTIAL'])
    low_stock = Stock.objects.select_related('product', 'location').filter(
        Q(quantity__lte=0) | Q(quantity__lt=F('product__minimum_stock'))
    ).order_by('quantity')
    overdue_tasks = HousekeepingTask.objects.filter(
        status__in=['PENDING', 'IN_PROGRESS'],
        scheduled_date__lt=timezone.localdate(),
    ).select_related('room')
    payments_total = Payment.objects.aggregate(total=Sum('amount'))['total'] or ZERO
    expenses_total = Expense.objects.aggregate(total=Sum('amount'))['total'] or ZERO
    outstanding = pending_invoices.aggregate(
        total=Sum(F('total_amount') - F('paid_amount')))['total'] or ZERO

    modules = [
        {'label': 'Réservations', 'value': Reservation.objects.count(),
         'meta': f"{Reservation.objects.filter(status__in=['CONFIRMED', 'CHECKED_IN']).count()} actives",
         'url': '/module/hotel/reservation/', 'icon': 'reservations'},
        {'label': 'Commandes restaurant', 'value': Order.objects.count(),
         'meta': f'{open_orders} en cours', 'url': '/module/restaurant/order/', 'icon': 'orders'},
        {'label': 'Commandes bar', 'value': BarOrder.objects.count(),
         'meta': f'{open_bar_orders} en cours', 'url': '/module/bar/barorder/', 'icon': 'orders'},
        {'label': 'Factures', 'value': Invoice.objects.count(),
         'meta': f'{pending_invoices.count()} à traiter', 'url': '/module/finance/invoice/',
         'icon': 'invoices'},
        {'label': 'Stocks', 'value': Stock.objects.count(),
         'meta': f'{low_stock.count()} alerte(s)', 'url': '/module/inventory/stock/',
         'icon': 'inventory'},
        {'label': 'Utilisateurs', 'value': User.objects.count(),
         'meta': f'{User.objects.filter(is_active=True).count()} actifs',
         'url': '/module/core/user/', 'icon': 'team'},
    ]

    anomalies = []
    if low_stock.count():
        anomalies.append({
            'label': 'Stocks sous le seuil',
            'detail': f'{low_stock.count()} référence(s) à réapprovisionner',
            'url': '/module/inventory/stock/', 'tone': 'danger',
        })
    if overdue_tasks.count():
        anomalies.append({
            'label': 'Housekeeping en retard',
            'detail': f'{overdue_tasks.count()} tâche(s) non clôturée(s)',
            'url': '/module/hotel/housekeepingtask/', 'tone': 'warning',
        })
    if pending_invoices.count():
        anomalies.append({
            'label': 'Encaissements en attente',
            'detail': f'{pending_invoices.count()} facture(s) ouverte(s) · {outstanding} F',
            'url': '/module/finance/invoice/', 'tone': 'warning',
        })

    today = timezone.localdate()
    planning = _month_planning(request, today)
    context = {
        'today': today,
        'users': users[:12],
        'user_total': users.count(),
        'groups': groups,
        'logs': logs,
        'modules': modules,
        'anomalies': anomalies,
        'open_orders': open_orders,
        'open_bar_orders': open_bar_orders,
        'pending_invoice_count': pending_invoices.count(),
        'low_stock_count': low_stock.count(),
        'low_stock': low_stock[:6],
        'overdue_tasks': overdue_tasks[:6],
        'payments_total': payments_total,
        'expenses_total': expenses_total,
        'outstanding': outstanding,
        'recent_payments': Payment.objects.select_related(
            'invoice', 'method', 'received_by'
        ).order_by('-paid_at')[:8],
        'superadmin_actions': [
            {'label': 'Bilan financier', 'url': reverse('workspaces:finance_balance'), 'icon': 'analytics'},
            {'label': 'Rapports', 'url': '/reports/', 'icon': 'reports'},
            {'label': 'Administration Django', 'url': '/admin/', 'icon': 'settings'},
            {'label': 'Journal d’audit', 'url': '/module/core/auditlog/', 'icon': 'audit'},
        ],
        **planning,
    }
    return render(request, 'workspaces/superadmin.html', context)


# ---------------------------------------------------------------------------
# Owner — business management
# ---------------------------------------------------------------------------

@role_required('Owner')
def owner_workspace(request):
    today = timezone.localdate()
    hotel_revenue = Reservation.objects.exclude(status='CANCELLED').aggregate(
        total=Sum('estimated_total'))['total'] or ZERO
    restaurant_revenue = Order.objects.exclude(status='CANCELLED').aggregate(
        total=Sum('total_amount'))['total'] or ZERO
    bar_revenue = BarOrder.objects.exclude(status='CANCELLED').aggregate(
        total=Sum('total_amount'))['total'] or ZERO
    activity_revenue = hotel_revenue + restaurant_revenue + bar_revenue
    collected = Payment.objects.aggregate(total=Sum('amount'))['total'] or ZERO
    expenses_total = Expense.objects.aggregate(total=Sum('amount'))['total'] or ZERO
    outstanding = Invoice.objects.filter(status__in=['ISSUED', 'PARTIAL']).aggregate(
        total=Sum(F('total_amount') - F('paid_amount')))['total'] or ZERO
    estimated_profit = activity_revenue - expenses_total

    rooms_total = Room.objects.count()
    occupied = Reservation.objects.filter(
        status__in=['CONFIRMED', 'CHECKED_IN'],
        check_in__lte=today, check_out__gt=today,
    ).values('room_id').distinct().count()
    occupancy_rate = round(occupied / rooms_total * 100) if rooms_total else 0

    orders_volume = (
        Order.objects.exclude(status='CANCELLED').count()
        + BarOrder.objects.exclude(status='CANCELLED').count()
    )

    top_dishes = (
        OrderItem.objects.filter(order__status__in=['SERVED', 'PAID'])
        .values('menu_item__name')
        .annotate(sold=Sum('quantity'), revenue=Sum(F('quantity') * F('unit_price')))
        .order_by('-quantity')[:6]
    )
    top_drinks = (
        BarOrderItem.objects.filter(order__status__in=['SERVED', 'PAID'])
        .values('drink__name')
        .annotate(sold=Sum('quantity'), revenue=Sum(F('quantity') * F('unit_price')))
        .order_by('-quantity')[:6]
    )
    table_performance = (
        Order.objects.exclude(status='CANCELLED').filter(table__isnull=False)
        .values('table__name')
        .annotate(orders=Count('id'), revenue=Sum('total_amount'))
        .order_by('-orders')[:6]
    )

    low_stock = Stock.objects.select_related('product', 'location').filter(
        Q(quantity__lte=0) | Q(quantity__lt=F('product__minimum_stock'))
    ).order_by('quantity')
    purchase_orders = PurchaseOrder.objects.select_related('supplier').order_by('-order_date')[:6]
    pending_purchases = PurchaseOrder.objects.exclude(status__in=['RECEIVED', 'CANCELLED']).count()

    recent_reservations = Reservation.objects.select_related(
        'customer', 'room').order_by('-created_at')[:6]
    recent_invoices = Invoice.objects.select_related('customer').order_by('-issued_at')[:6]
    recent_payments = Payment.objects.select_related(
        'invoice', 'method', 'received_by').order_by('-paid_at')[:6]
    recent_expenses = Expense.objects.select_related('category').order_by('-date')[:6]

    planning = _month_planning(request, today)
    context = {
        'today': today,
        'hotel_revenue': hotel_revenue,
        'restaurant_revenue': restaurant_revenue,
        'bar_revenue': bar_revenue,
        'activity_revenue': activity_revenue,
        'collected': collected,
        'expenses_total': expenses_total,
        'outstanding': outstanding,
        'estimated_profit': estimated_profit,
        'occupancy_rate': occupancy_rate,
        'occupied_rooms': occupied,
        'rooms_total': rooms_total,
        'orders_volume': orders_volume,
        'top_dishes': top_dishes,
        'top_drinks': top_drinks,
        'table_performance': table_performance,
        'low_stock': low_stock[:8],
        'low_stock_count': low_stock.count(),
        'purchase_orders': purchase_orders,
        'pending_purchases': pending_purchases,
        'supplier_count': Supplier.objects.count(),
        'recent_reservations': recent_reservations,
        'recent_invoices': recent_invoices,
        'recent_payments': recent_payments,
        'recent_expenses': recent_expenses,
        'owner_actions': [
            {'label': 'Bilan financier', 'url': reverse('workspaces:finance_balance'), 'icon': 'analytics'},
            {'label': 'Rapports', 'url': '/reports/', 'icon': 'reports'},
            {'label': 'Stocks & achats', 'url': '/module/inventory/stock/', 'icon': 'inventory'},
        ],
        **planning,
    }
    return render(request, 'workspaces/owner.html', context)


def _month_planning(request, today, rooms=None):
    raw = request.GET.get('planning', '').strip()
    try:
        year_s, month_s = raw.split('-', 1)
        first = datetime(int(year_s), int(month_s), 1).date()
    except Exception:
        first = today.replace(day=1)
    if first.month == 12:
        next_month = first.replace(year=first.year + 1, month=1, day=1)
    else:
        next_month = first.replace(month=first.month + 1, day=1)
    prev_month = (first - timedelta(days=1)).replace(day=1)
    days = []
    current = first
    while current < next_month:
        days.append(current)
        current += timedelta(days=1)
    if rooms is None:
        rooms = list(Room.objects.select_related('room_type').order_by('number'))
    reservations = (
        Reservation.objects.select_related('customer', 'room')
        .exclude(status='CANCELLED')
        .filter(check_in__lt=next_month, check_out__gt=first)
    )
    by_room = {}
    for reservation in reservations:
        by_room.setdefault(reservation.room_id, []).append(reservation)
    rows = []
    for room in rooms:
        cells = []
        for day in days:
            found = next(
                (r for r in by_room.get(room.pk, []) if r.check_in <= day < r.check_out),
                None,
            )
            cells.append({'date': day, 'reservation': found, 'is_today': day == today})
        rows.append({'room': room, 'cells': cells})
    return {
        'calendar_days': days,
        'calendar_rows': rows,
        'planning_month': first,
        'planning_prev': prev_month,
        'planning_next': next_month,
    }



# ---------------------------------------------------------------------------
# Reception — hotel operations
# ---------------------------------------------------------------------------

@role_required('Receptionist', 'Owner')
def reception_workspace(request):
    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)

    rooms = list(Room.objects.select_related('room_type').order_by('number'))
    active_reservations = list(
        Reservation.objects.filter(
            status__in=['CONFIRMED', 'CHECKED_IN'],
            check_in__lte=today,
            check_out__gt=today,
        ).select_related('customer', 'room')
    )
    active_by_room = {}
    for reservation in active_reservations:
        reservation.invoice = find_reservation_invoice(reservation)
        active_by_room.setdefault(reservation.room_id, reservation)

    cleaning_tasks = HousekeepingTask.objects.filter(
        status__in=['PENDING', 'IN_PROGRESS'],
        scheduled_date__lte=today,
    ).select_related('room', 'assigned_to')
    cleaning_by_room = {task.room_id: task for task in cleaning_tasks}

    room_cards = []
    for room in rooms:
        reservation = active_by_room.get(room.pk)
        task = cleaning_by_room.get(room.pk)
        if room.operational_status == 'MAINTENANCE':
            state, label = 'maintenance', 'Maintenance'
        elif room.operational_status == 'OUT_OF_SERVICE':
            state, label = 'out_of_order', 'Hors service'
        elif reservation:
            state, label = 'occupied', 'Occupée'
        elif task:
            state, label = 'cleaning', 'À nettoyer'
        else:
            state, label = 'available', 'Disponible'
        room_cards.append({
            'room': room,
            'state': state,
            'state_label': label,
            'reservation': reservation,
            'task': task,
        })

    arrivals = list(
        Reservation.objects.select_related('customer', 'room', 'room__room_type')
        .filter(check_in=today).exclude(status__in=['CANCELLED', 'CHECKED_OUT'])
        .order_by('customer__last_name')
    )
    departures = list(
        Reservation.objects.select_related('customer', 'room', 'room__room_type')
        .filter(check_out=today, status='CHECKED_IN')
        .order_by('customer__last_name')
    )
    for reservation in departures:
        reservation.departure_invoice = find_reservation_invoice(reservation)

    upcoming = Reservation.objects.select_related(
        'customer', 'room', 'room__room_type'
    ).filter(
        check_in__gte=today, check_in__lte=today + timedelta(days=14)
    ).exclude(status__in=['CANCELLED', 'CHECKED_OUT']).order_by('check_in', 'room__number')[:10]

    reservation_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    reservations = Reservation.objects.select_related('customer', 'room', 'room__room_type')
    if reservation_query:
        reservations = reservations.filter(
            Q(customer__first_name__icontains=reservation_query)
            | Q(customer__last_name__icontains=reservation_query)
            | Q(customer__phone__icontains=reservation_query)
            | Q(room__number__icontains=reservation_query)
        )
    if status_filter:
        reservations = reservations.filter(status=status_filter)
    reservation_page = _paginate(request, reservations.order_by('-created_at'), 15)

    audit_logs = _recent_audit_logs(10)
    recent_customers = Customer.objects.order_by('-created_at')[:8]
    housekeeping_open = cleaning_tasks.order_by('scheduled_date', 'room__number')

    avail_from = _parse_date(request.GET.get('avail_from'), today)
    avail_to = _parse_date(request.GET.get('avail_to'), tomorrow)
    if avail_to <= avail_from:
        avail_to = avail_from + timedelta(days=1)
    conflicting = (
        Reservation.objects.select_related('customer')
        .filter(status__in=['CONFIRMED', 'CHECKED_IN'], check_in__lt=avail_to, check_out__gt=avail_from)
        .order_by('check_in')
    )
    conflict_by_room = {}
    for reservation in conflicting:
        conflict_by_room.setdefault(reservation.room_id, reservation)
    availability_rooms = []
    available_count = 0
    for room in rooms:
        reservation = conflict_by_room.get(room.pk)
        if room.operational_status == 'MAINTENANCE':
            state, label = 'maintenance', 'Maintenance'
        elif room.operational_status == 'OUT_OF_SERVICE':
            state, label = 'out_of_service', 'Hors service'
        elif reservation:
            state = 'occupied' if reservation.status == 'CHECKED_IN' else 'reserved'
            label = 'Occupée' if reservation.status == 'CHECKED_IN' else 'Réservée'
        else:
            state, label = 'available', 'Disponible'
            available_count += 1
        availability_rooms.append({'room': room, 'state': state, 'state_label': label, 'reservation': reservation})

    planning = _month_planning(request, today, rooms=rooms)

    rates = RoomRate.objects.select_related('room_type').filter(active=True).order_by('price')
    pending_requests = BookingRequest.objects.filter(handled_at__isnull=True).select_related('room_type').order_by('created_at', 'pk')
    booking_requests = Paginator(pending_requests, 10).get_page(request.GET.get('demandes'))
    pending_request_count = pending_requests.count()

    can_collect = _has_role(request.user, COLLECT_ROLES)
    context = {
        'today': today,
        'tomorrow': tomorrow,
        'room_cards': room_cards,
        'arrivals': arrivals,
        'arrival_count': len(arrivals),
        'departures': departures,
        'departure_count': len(departures),
        'upcoming': upcoming,
        'reservations': reservation_page,
        'reservation_query': reservation_query,
        'status_filter': status_filter,
        'invoice_statuses': Invoice.STATUS,
        'housekeeping_tasks': housekeeping_open,
        'housekeeping_count': housekeeping_open.count(),
        'recent_customers': recent_customers,
        'audit_logs': audit_logs,
        'avail_from': avail_from,
        'avail_to': avail_to,
        'availability_rooms': availability_rooms,
        'available_count': available_count,
        **planning,
        'rates': rates,
        'booking_requests': booking_requests,
        'pending_request_count': pending_request_count,
        'occupied_count': sum(1 for card in room_cards if card['state'] == 'occupied'),
        'available_count_total': sum(1 for card in room_cards if card['state'] == 'available'),
        'can_collect': can_collect,
    }
    return render(request, 'workspaces/reception.html', context)


def _booking_request_available_rooms(booking_request):
    if not booking_request or not booking_request.room_type_id:
        return Room.objects.none()
    conflicting = Reservation.objects.filter(
        status__in=['CONFIRMED', 'CHECKED_IN'],
        check_in__lt=booking_request.check_out,
        check_out__gt=booking_request.check_in,
    ).values_list('room_id', flat=True)
    return Room.objects.filter(
        room_type=booking_request.room_type,
        operational_status='AVAILABLE',
    ).exclude(pk__in=conflicting).select_related('room_type').order_by('number')


def _match_customer_for_booking(booking_request):
    qs = Customer.objects.filter(is_walk_in=False)
    email = (booking_request.email or '').strip()
    phone = (booking_request.phone or '').strip()
    if email:
        match = qs.filter(email__iexact=email).first()
        if match:
            return match
    if phone:
        match = qs.filter(phone=phone).first()
        if match:
            return match
    return None


@role_required('Receptionist', 'Owner')
@require_POST
@transaction.atomic
def resolve_booking_request(request, pk):
    booking_request = get_object_or_404(BookingRequest.objects.select_for_update(), pk=pk)
    if booking_request.reservation_id:
        messages.info(request, 'Cette demande est déjà liée à une réservation.')
    elif booking_request.handled_at:
        messages.info(request, 'Cette demande a déjà été traitée.')
    else:
        booking_request.handled_at = timezone.now()
        booking_request.save(update_fields=['handled_at'])
        log_action(request.user, 'Demande de réservation web traitée', booking_request)
        messages.success(request, 'Demande marquée comme traitée.')
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('workspaces:reception')
    if '/bookingrequest/' in next_url and '/module/' in next_url:
        return redirect(next_url)
    return redirect('workspaces:reception')


@role_required('Receptionist', 'Owner')
@require_POST
@transaction.atomic
def reopen_booking_request(request, pk):
    booking_request = get_object_or_404(BookingRequest.objects.select_for_update(), pk=pk)
    if booking_request.reservation_id:
        messages.error(request, 'Impossible de rouvrir une demande déjà convertie en réservation.')
    elif not booking_request.handled_at:
        messages.info(request, 'Cette demande est déjà en attente.')
    else:
        booking_request.handled_at = None
        booking_request.save(update_fields=['handled_at'])
        log_action(request.user, 'Demande de réservation web rouverte', booking_request)
        messages.success(request, 'Demande remise en attente.')
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('workspaces:reception')
    return redirect(next_url)


@role_required('Receptionist', 'Owner')
@transaction.atomic
def reservation_create(request):
    booking_request = None
    booking_request_id = request.POST.get('booking_request') or request.GET.get('booking_request')
    if booking_request_id:
        booking_request = BookingRequest.objects.select_for_update().select_related('room_type', 'reservation').filter(pk=booking_request_id).first()

    initial = {}
    if request.GET.get('room'):
        initial['room'] = request.GET.get('room')
    if booking_request:
        if booking_request.reservation_id:
            messages.info(request, 'Cette demande a déjà été convertie en réservation.')
            return redirect('entity_detail', 'hotel', 'reservation', booking_request.reservation_id)
        initial.update({
            'check_in': booking_request.check_in,
            'check_out': booking_request.check_out,
            'adults': booking_request.adults,
            'contact_information': booking_request.phone or booking_request.email or '',
            'notes': f"Demande web #{booking_request.pk} · {booking_request.guest_name} · {booking_request.get_contact_method_display()} {booking_request.phone or booking_request.email}".strip(),
            'status': 'CONFIRMED',
        })
        matched = _match_customer_for_booking(booking_request)
        if matched:
            initial['customer'] = matched.pk
            initial['customer_mode'] = 'existing'
        else:
            parts = (booking_request.guest_name or '').strip().split(None, 1)
            initial.update({
                'customer_mode': 'new',
                'first_name': parts[0] if parts else booking_request.guest_name or '',
                'last_name': parts[1] if len(parts) > 1 else '',
                'phone': booking_request.phone or '',
                'email': booking_request.email or '',
            })

    form = ReservationForm(request.POST or None, initial=initial)
    if booking_request:
        form.fields['room'].queryset = Room.objects.filter(
            room_type=booking_request.room_type
        ).select_related('room_type').order_by('number')

    if request.method == 'POST' and form.is_valid():
        reservation = form.save(commit=False)
        reservation.created_by = request.user
        reservation.save()
        form.save_m2m()
        if booking_request and not booking_request.reservation_id:
            booking_request.reservation = reservation
            booking_request.handled_at = booking_request.handled_at or timezone.now()
            booking_request.save(update_fields=['reservation', 'handled_at'])
            log_action(
                request.user, 'Demande web convertie en réservation', booking_request,
                details={'reservation': reservation.pk, 'customer': str(reservation.customer)},
            )
            messages.success(request, f'Réservation créée et demande #{booking_request.pk} liée.')
        else:
            log_action(
                request.user, 'Réservation créée', reservation,
                details={'customer': str(reservation.customer), 'room': str(reservation.room), 'status': reservation.status},
            )
            messages.success(request, 'Réservation créée avec succès.')
        return redirect('entity_detail', 'hotel', 'reservation', reservation.pk)

    suggested_rooms = _booking_request_available_rooms(booking_request) if booking_request else Room.objects.none()
    return render(request, 'workspaces/reservation_form.html', {
        'form': form,
        'reservation': None,
        'booking_request': booking_request,
        'suggested_rooms': suggested_rooms,
    })


@role_required('Receptionist', 'Owner')
def reservation_edit(request, pk):
    reservation = get_object_or_404(Reservation, pk=pk)
    if reservation.status not in ('DRAFT', 'CONFIRMED'):
        messages.error(request, 'Cette réservation ne peut plus être modifiée à ce stade.')
        return redirect('workspaces:reception')
    form = ReservationForm(request.POST or None, instance=reservation)
    if request.method == 'POST' and form.is_valid():
        reservation = form.save(commit=False)
        reservation.created_by = reservation.created_by or request.user
        reservation.save()
        form.save_m2m()
        log_action(
            request.user, 'Réservation modifiée', reservation,
            details={'customer': str(reservation.customer), 'status': reservation.status},
        )
        messages.success(request, 'Réservation mise à jour.')
        return redirect('workspaces:reception')
    return render(request, 'workspaces/reservation_form.html', {
        'form': form,
        'reservation': reservation,
    })


@role_required('Receptionist', 'Owner')
def reservation_check_in(request, pk):
    reservation = get_object_or_404(Reservation, pk=pk)
    if request.method != 'POST':
        return redirect('workspaces:reception')
    try:
        check_in_reservation(reservation, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'Client enregistré pour la chambre {reservation.room}.')
    return redirect('workspaces:reception')


@role_required('Receptionist', 'Owner')
def reservation_prepare_checkout(request, pk):
    reservation = get_object_or_404(Reservation, pk=pk)
    if request.method != 'POST':
        return redirect('workspaces:reception')
    try:
        invoice = prepare_checkout(reservation, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f'Facture {invoice.number} préparée. Solde à encaisser : {invoice.balance} F.',
        )
    return redirect('workspaces:reception')


@role_required('Receptionist', 'Owner')
def reservation_check_out(request, pk):
    reservation = get_object_or_404(Reservation, pk=pk)
    if request.method != 'POST':
        return redirect('workspaces:reception')
    try:
        complete_checkout(reservation, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f'Départ finalisé · chambre {reservation.room} prête pour le ménage.',
        )
    return redirect('workspaces:reception')


@role_required('Receptionist', 'Owner')
def reservation_cancel(request, pk):
    reservation = get_object_or_404(Reservation, pk=pk)
    if request.method != 'POST':
        return redirect('entity_detail', 'hotel', 'reservation', reservation.pk)
    if reservation.status not in ('DRAFT', 'CONFIRMED'):
        messages.error(request, 'Seule une réservation en brouillon ou confirmée peut être annulée.')
        return redirect('entity_detail', 'hotel', 'reservation', reservation.pk)
    reservation.status = 'CANCELLED'
    reservation.save(update_fields=['status'])
    log_action(
        request.user, 'Réservation annulée', reservation,
        details={'customer': str(reservation.customer), 'room': str(reservation.room)},
    )
    messages.success(request, 'Réservation annulée.')
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('entity_detail', args=['hotel', 'reservation', reservation.pk])
    return redirect(next_url)


@role_required('Receptionist', 'Owner')
def housekeeping_status(request, pk):
    task = get_object_or_404(HousekeepingTask, pk=pk)
    if request.method != 'POST':
        return redirect('workspaces:reception')
    status = request.POST.get('status', '')
    try:
        update_housekeeping(task, status, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, 'Tâche de ménage mise à jour.')
    return redirect('workspaces:reception')


# ---------------------------------------------------------------------------
# Chef — kitchen operations / KDS
# ---------------------------------------------------------------------------

@role_required('Chef', 'Owner')
def kitchen_workspace(request):
    today = timezone.localdate()
    active_orders = list(
        Order.objects.select_related('table', 'customer')
        .prefetch_related('items__menu_item')
        .filter(status__in=['CONFIRMED', 'PREPARING', 'READY'])
        .order_by('created_at')
    )
    for order in active_orders:
        order.waiting_minutes = _order_age_minutes(order)

    new_orders = [order for order in active_orders if order.status == 'CONFIRMED']
    preparing_orders = [order for order in active_orders if order.status == 'PREPARING']
    ready_orders = [order for order in active_orders if order.status == 'READY']

    history = list(
        Order.objects.select_related('table', 'customer')
        .prefetch_related('items__menu_item')
        .filter(status__in=['SERVED', 'PAID'])
        .order_by('-created_at')[:10]
    )

    menu_items = list(MenuItem.objects.select_related('menu').order_by('category', 'name'))
    recipes = {recipe.pk: recipe for recipe in Recipe.objects.prefetch_related(
        'ingredients__product', 'ingredients__unit'
    )}
    for item in menu_items:
        item.recipe = recipes.get(item.recipe_id)

    stocks = list(Stock.objects.select_related('product', 'location').order_by('quantity'))
    low_stocks = [
        stock for stock in stocks
        if stock.quantity <= 0 or stock.quantity < stock.product.minimum_stock
    ]
    movements = StockMovement.objects.select_related(
        'product', 'location', 'responsible_user').order_by('-date')[:10]

    context = {
        'today': today,
        'new_orders': new_orders,
        'preparing_orders': preparing_orders,
        'ready_orders': ready_orders,
        'active_orders': active_orders,
        'history': history,
        'menu_items': menu_items,
        'available_items': sum(1 for item in menu_items if item.available),
        'unavailable_items': sum(1 for item in menu_items if not item.available),
        'stocks': stocks[:12],
        'low_stocks': low_stocks[:8],
        'low_stock_count': len(low_stocks),
        'movements': movements,
        'restock_form': RestockForm(),
    }
    return render(request, 'workspaces/kitchen.html', context)


@role_required('Chef', 'Owner')
def kitchen_restock(request):
    if request.method != 'POST':
        return redirect('workspaces:kitchen')
    form = RestockForm(request.POST)
    if form.is_valid():
        signal_restock(
            form.cleaned_data['product'], request.user,
            note=form.cleaned_data['note'], source='Cuisine',
        )
        messages.success(request, 'Besoin de réapprovisionnement signalé à l’inventaire.')
    else:
        messages.error(request, 'Sélectionnez un produit pour signaler le besoin.')
    return redirect('workspaces:kitchen')


@role_required('Chef', 'Owner')
def menu_item_toggle(request, pk):
    item = get_object_or_404(MenuItem, pk=pk)
    if request.method != 'POST':
        return redirect('workspaces:kitchen')
    item.available = not item.available
    item.save(update_fields=['available'])
    log_action(
        request.user,
        'Disponibilité du plat modifiée',
        item,
        details={'available': item.available, 'menu': str(item.menu)},
    )
    messages.success(
        request,
        f'{item.name} est maintenant {"disponible" if item.available else "indisponible"}.',
    )
    return redirect('workspaces:kitchen')


# ---------------------------------------------------------------------------
# Waiter — restaurant service
# ---------------------------------------------------------------------------

@role_required('Waiter', 'Receptionist', 'Owner')
def waiter_workspace(request):
    tables = list(Table.objects.filter(active=True).order_by('section', 'name', 'pk'))
    active_orders = list(
        Order.objects.select_related('customer', 'table', 'created_by')
        .prefetch_related('items__menu_item')
        .exclude(status__in=['PAID', 'CANCELLED'])
        .order_by('created_at')
    )
    for order in active_orders:
        order.invoice = find_order_invoice(order)
        order.stay_reservation = active_stay_reservation_for_customer(order.customer) if not order.invoice else None
    table_orders = {}
    for order in active_orders:
        table_orders.setdefault(order.table_id, []).append(order)
    for table in tables:
        table.active_orders = table_orders.get(table.pk, ())

    ready_orders = [order for order in active_orders if order.status == 'READY']
    my_orders = [order for order in active_orders if order.created_by_id == request.user.pk]
    show_mine = request.GET.get('vue') == 'mes-commandes'

    bar_tables = list(BarTable.objects.filter(active=True).order_by('name'))
    bar_active_orders = list(
        BarOrder.objects.select_related('customer', 'table', 'created_by')
        .prefetch_related('items__drink')
        .exclude(status__in=['PAID', 'CANCELLED'])
        .order_by('created_at')
    )
    for order in bar_active_orders:
        order.invoice = find_bar_invoice(order)
        order.stay_reservation = active_stay_reservation_for_customer(order.customer) if not order.invoice else None
    bar_table_orders = {}
    for order in bar_active_orders:
        if order.table_id and order.table_id not in bar_table_orders:
            bar_table_orders[order.table_id] = order
    for table in bar_tables:
        table.active_order = bar_table_orders.get(table.pk)

    context = {
        'tables': tables,
        'active_orders': my_orders if show_mine else active_orders,
        'active_order_count': len(active_orders),
        'my_order_count': len(my_orders),
        'show_mine': show_mine,
        'ready_orders': ready_orders,
        'customers': Customer.objects.filter(is_walk_in=False),
        'bar_tables': bar_tables,
        'bar_active_orders': bar_active_orders,
        'bar_ready_orders': [o for o in bar_active_orders if o.status == 'SERVED' and not o.invoice],
    }
    return render(request, 'workspaces/service.html', context)


def _order_rows(items, previous_lines, product_field, request):
    by_product = {}
    for line in previous_lines:
        by_product.setdefault(getattr(line, f'{product_field}_id'), []).append(line)
    rows = []
    for item in items:
        category = item.category.name if product_field == 'drink' else item.category
        for index, line in enumerate(by_product.get(item.pk) or [None]):
            key = f'{item.pk}_{line.pk}' if index else str(item.pk)
            rows.append(SimpleNamespace(
                item=item, key=key, category=category, line=line,
                quantity=request.POST.get(f'qty_{key}', '') if request.method == 'POST' else (line.quantity if line else ''),
                note=request.POST.get(f'note_{key}', '') if request.method == 'POST' else getattr(line, 'notes', ''),
                price=line.unit_price if line else item.selling_price,
                max_quantity=max(99, line.quantity) if line else 99,
                orderable=item.orderable,
            ))
    return rows


def _selected_order_rows(form, rows, request):
    selected = []
    expected_fields = {f'qty_{row.key}' for row in rows}
    if any(key.startswith('qty_') and key not in expected_fields and value.strip() not in ('', '0')
           for key, value in request.POST.items()):
        form.add_error(None, 'Un article sélectionné n’est plus disponible. Retirez-le pour continuer.')
    for row in rows:
        try:
            quantity = int(row.quantity or 0)
        except ValueError:
            quantity = -1
        if quantity == 0:
            continue
        if not 0 < quantity <= row.max_quantity:
            form.add_error(None, f'Quantité invalide pour {row.item.name} (de 1 à {row.max_quantity}).')
        elif not row.orderable:
            form.add_error(None, f'{row.item.name} n’est plus disponible. Retirez-le pour continuer.')
        else:
            selected.append((row, quantity))
    if not selected and not form.errors:
        form.add_error(None, 'Ajoutez au moins un article à la commande.')
    return selected


@transaction.atomic
def _compose_order(request, pk, *, bar=False):
    order_model, line_model, product_field = (BarOrder, BarOrderItem, 'drink') if bar else (Order, OrderItem, 'menu_item')
    catalog = Drink.objects.filter(available=True, category__active=True).select_related('category') if bar else available_dishes()
    form_class, table_model = (BarOrderForm, BarTable) if bar else (WaiterOrderForm, Table)
    next_ws = request.GET.get('next') or request.POST.get('next')
    back = f'workspaces:{next_ws}' if next_ws in ('service', 'bar') else ('workspaces:bar' if bar else 'workspaces:service')
    find_invoice = find_bar_invoice if bar else find_order_invoice
    draft_query = order_model.objects.select_for_update() if request.method == 'POST' else order_model.objects.all()
    draft = get_object_or_404(draft_query, pk=pk) if pk is not None else None
    if draft and (draft.status != 'OPEN' or find_invoice(draft)):
        messages.error(request, 'Cette commande ne peut plus être modifiée.')
        return redirect(back)

    items = with_ingredients(catalog)
    included = {item.pk for item in items}
    previous_lines = list(draft.items.order_by('pk')) if draft else []
    previous_items = {getattr(line, f'{product_field}_id') for line in previous_lines}
    items += list(catalog.model.objects.filter(pk__in=previous_items - included))
    for item in items:
        item.orderable = item.pk in included
    items.sort(key=lambda item: (str(item.category), item.name, item.pk))
    rows = _order_rows(items, previous_lines, product_field, request)

    initial = {'table': request.GET.get('table')}
    if draft:
        initial = {'table': draft.table_id, 'customer': draft.customer_id, 'notes': draft.notes}
        if not bar:
            initial['source'] = draft.source
    form = form_class(request.POST if request.method == 'POST' else None, initial=initial)
    if draft:
        form.fields['table'].queryset = table_model.objects.filter(pk=draft.table_id)
        form.fields['table'].disabled = True
        if not bar:
            form.fields['source'].disabled = True

    if request.method == 'POST' and form.is_valid():
        selected = _selected_order_rows(form, rows, request)
        table = form.cleaned_data['table']
        total = sum((row.price * quantity for row, quantity in selected), ZERO)
        if total > Decimal('9999999999.99'):
            form.add_error(None, 'Le total de la commande dépasse le montant pris en charge.')
        if not form.errors and not draft and table and not table_model.objects.filter(
            pk=table.pk, active=True,
        ).exclude(status='CLOSED').update(status='OCCUPIED'):
            form.add_error('table', 'Cette table n’est plus ouverte au service.')
        if not form.errors:
            order = draft or order_model(created_by=request.user, table=table)
            if not bar:
                order.source = form.cleaned_data['source']
            order.customer = form.save_customer()
            order.notes = form.cleaned_data['notes']
            order.status = 'CONFIRMED' if request.POST.get('send') else 'OPEN'
            order.total_amount = total
            order.save()
            if draft:
                retained = [row.line.pk for row, _ in selected if row.line]
                order.items.exclude(pk__in=retained).delete()
            new_lines = []
            updated_lines = []
            for row, quantity in selected:
                line = row.line or line_model(order=order, unit_price=row.price, **{product_field: row.item})
                line.quantity = quantity
                if not bar:
                    line.notes = row.note.strip()
                (updated_lines if row.line else new_lines).append(line)
            line_model.objects.bulk_create(new_lines)
            line_model.objects.bulk_update(updated_lines, ['quantity'] if bar else ['quantity', 'notes'])
            log_action(request.user, 'Commande modifiée' if draft else 'Commande créée', order,
                       details={'status': order.status, 'total': str(total), 'items': len(selected)})
            destination = 'au bar' if bar else 'en cuisine'
            feedback = f'transmise {destination}' if order.status == 'CONFIRMED' else 'enregistrée en brouillon'
            messages.success(request, f'Commande #{order.pk} {feedback}.')
            return redirect(back)

    return render(request, 'workspaces/service_order.html', {
        'form': form, 'menu_rows': rows, 'draft': draft,
        'bar_order': bar, 'back_to_orders': back, 'next_workspace': next_ws if next_ws in ('service', 'bar') else '',
    })


@role_required('Waiter', 'Receptionist', 'Owner')
def service_order_create(request, pk=None):
    return _compose_order(request, pk)


def _can(role_action, user):
    roles = {
        'confirm': {'Waiter', 'Receptionist', 'Owner'},
        'serve': {'Waiter', 'Receptionist', 'Owner'},
        'cancel': {'Waiter', 'Receptionist', 'Owner'},
        'start': {'Chef', 'Owner'},
        'ready': {'Chef', 'Owner'},
        'bar_start': {'Bartender', 'Waiter', 'Owner'},
        'bar_serve': {'Bartender', 'Waiter', 'Owner'},
        'bar_cancel': {'Bartender', 'Waiter', 'Owner'},
    }
    if user.is_superuser:
        return True
    return bool(_groups(user).intersection(roles.get(role_action, set())))


@login_required
@transaction.atomic
def restaurant_order_action(request, pk, action):
    if not _can(action, request.user):
        raise PermissionDenied('Action non autorisée pour votre rôle.')
    if request.method != 'POST':
        return redirect('workspaces:service')
    order = get_object_or_404(Order.objects.select_for_update(), pk=pk)
    try:
        if action == 'cancel' and find_order_invoice(order):
            raise ValueError('L’addition a déjà été transmise à la caisse.')
        if action == 'confirm' and order.status == 'OPEN' and not order.items.exists():
            raise ValueError('Ajoutez des articles à la commande avant de l’envoyer.')
        restaurant_transition(order, action, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, 'Commande mise à jour.')
    if action in {'start', 'ready'}:
        return redirect('workspaces:kitchen')
    return redirect('workspaces:service')


@role_required('Waiter', 'Receptionist', 'Owner')
def service_attach_customer(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.method != 'POST':
        return redirect('workspaces:service')
    form = AttachCustomerForm(request.POST)
    if form.is_valid():
        try:
            attach_order_customer(order, form.cleaned_data['customer'], request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, 'Client associé à la commande.')
    else:
        messages.error(request, 'Sélectionnez un client valide.')
    return redirect('workspaces:service')


@role_required('Waiter', 'Receptionist', 'Owner')
def service_request_bill(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.method != 'POST':
        return redirect('workspaces:service')
    try:
        invoice = invoice_for_order(order, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f'Addition #{invoice.number} transmise à la caisse · solde {invoice.balance} F.',
        )
    return redirect('workspaces:service')


# ---------------------------------------------------------------------------
# Bartender — bar operations
# ---------------------------------------------------------------------------

@role_required('Bartender', 'Waiter', 'Owner')
def bartender_workspace(request):
    tables = list(BarTable.objects.filter(active=True).order_by('name'))
    active_orders = list(
        BarOrder.objects.select_related('customer', 'table')
        .prefetch_related('items__drink')
        .exclude(status__in=['PAID', 'CANCELLED'])
        .order_by('created_at')
    )
    for order in active_orders:
        order.invoice = find_bar_invoice(order)
        order.stay_reservation = active_stay_reservation_for_customer(order.customer) if not order.invoice else None
    table_orders = {}
    for order in active_orders:
        if order.table_id and order.table_id not in table_orders:
            table_orders[order.table_id] = order
    for table in tables:
        table.active_order = table_orders.get(table.pk)

    drinks = list(
        Drink.objects.select_related('category').order_by('category__name', 'name')
    )
    categories = sorted({drink.category.name for drink in drinks})
    served_orders = [order for order in active_orders if order.status == 'SERVED']
    low_stocks = Stock.objects.select_related('product', 'location').filter(
        Q(quantity__lte=0) | Q(quantity__lt=F('product__minimum_stock'))
    ).order_by('quantity')

    context = {
        'today': timezone.localdate(),
        'tables': tables,
        'available_tables': sum(1 for table in tables if table.status == 'AVAILABLE'),
        'occupied_tables': sum(1 for table in tables if table.status == 'OCCUPIED'),
        'active_orders': active_orders,
        'served_orders': served_orders,
        'invoiced_orders': [order for order in active_orders if order.invoice],
        'drinks': drinks,
        'categories': categories,
        'drink_count': len(drinks),
        'available_drinks': sum(1 for drink in drinks if drink.available),
        'low_stocks': low_stocks[:8],
        'low_stock_count': low_stocks.count(),
        'customers': Customer.objects.filter(is_walk_in=False),
        'attach_form': AttachCustomerForm(),
        'restock_form': RestockForm(),
        'can_collect': _has_role(request.user, COLLECT_ROLES),
    }
    return render(request, 'workspaces/bar.html', context)


@role_required('Bartender', 'Waiter', 'Owner')
def bar_order_create(request, pk=None):
    return _compose_order(request, pk, bar=True)


@login_required
@transaction.atomic
def bar_order_action(request, pk, action):
    role_action = f'bar_{action}'
    if not _can(role_action, request.user):
        raise PermissionDenied('Action non autorisée pour votre rôle.')
    next_ws = request.POST.get('next')
    dest = f'workspaces:{next_ws}' if next_ws in ('service', 'bar') else 'workspaces:bar'
    if request.method != 'POST':
        return redirect(dest)
    order = get_object_or_404(BarOrder.objects.select_for_update(), pk=pk)
    try:
        if action == 'cancel' and find_bar_invoice(order):
            raise ValueError('L’addition a déjà été transmise à la caisse.')
        if action == 'start' and order.status == 'OPEN' and not order.items.exists():
            raise ValueError('Ajoutez des articles à la commande avant de l’envoyer.')
        bar_transition(order, action, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, 'Commande bar mise à jour.')
    return redirect(dest)


@role_required('Bartender', 'Waiter', 'Owner')
def bar_attach_customer(request, pk):
    order = get_object_or_404(BarOrder, pk=pk)
    next_ws = request.POST.get('next')
    dest = f'workspaces:{next_ws}' if next_ws in ('service', 'bar') else 'workspaces:bar'
    if request.method != 'POST':
        return redirect(dest)
    form = AttachCustomerForm(request.POST)
    if form.is_valid():
        try:
            attach_order_customer(order, form.cleaned_data['customer'], request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, 'Client associé à la commande bar.')
    else:
        messages.error(request, 'Sélectionnez un client valide.')
    return redirect(dest)


@role_required('Bartender', 'Waiter', 'Owner')
def bar_request_bill(request, pk):
    order = get_object_or_404(BarOrder, pk=pk)
    next_ws = request.POST.get('next')
    dest = f'workspaces:{next_ws}' if next_ws in ('service', 'bar') else 'workspaces:bar'
    if request.method != 'POST':
        return redirect(dest)
    try:
        invoice = invoice_for_bar_order(order, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f'Addition bar #{invoice.number} transmise à la caisse · solde {invoice.balance} F.',
        )
    return redirect(dest)


@role_required('Bartender', 'Owner')
def bar_restock(request):
    if request.method != 'POST':
        return redirect('workspaces:bar')
    form = RestockForm(request.POST)
    if form.is_valid():
        signal_restock(
            form.cleaned_data['product'], request.user,
            note=form.cleaned_data['note'], source='Bar',
        )
        messages.success(request, 'Besoin de réapprovisionnement signalé à l’inventaire.')
    else:
        messages.error(request, 'Sélectionnez un produit pour signaler le besoin.')
    return redirect('workspaces:bar')



# ---------------------------------------------------------------------------
# Room & table detail pages (status, payment, upcoming)
# ---------------------------------------------------------------------------

@role_required('Receptionist', 'Owner')
def reception_room_detail(request, pk):
    room = get_object_or_404(Room.objects.select_related('room_type'), pk=pk)
    today = timezone.localdate()
    current_reservation = (
        Reservation.objects.select_related('customer')
        .filter(room=room, status__in=['CONFIRMED', 'CHECKED_IN'], check_in__lte=today, check_out__gt=today)
        .order_by('-status', 'check_in')
        .first()
    )
    if not current_reservation:
        current_reservation = (
            Reservation.objects.select_related('customer')
            .filter(room=room, status='CHECKED_IN')
            .order_by('-check_in', '-pk')
            .first()
        )
    current_invoice = find_reservation_invoice(current_reservation) if current_reservation else None
    if current_reservation:
        current_reservation.invoice = current_invoice

    next_reservations = (
        Reservation.objects.select_related('customer')
        .filter(room=room, check_in__gte=today)
        .exclude(status__in=['CANCELLED', 'CHECKED_OUT'])
        .order_by('check_in')
    )
    if current_reservation:
        next_reservations = next_reservations.exclude(pk=current_reservation.pk)
    next_reservations = list(next_reservations[:6])
    for reservation in next_reservations:
        reservation.invoice = find_reservation_invoice(reservation)

    recent_reservations = list(
        Reservation.objects.select_related('customer')
        .filter(room=room)
        .order_by('-check_in', '-created_at')[:12]
    )
    for reservation in recent_reservations:
        reservation.invoice = find_reservation_invoice(reservation)

    active_stay = (
        Stay.objects.select_related(
            'reservation', 'reservation__customer', 'reservation__room', 'responsible_receptionist',
        )
        .filter(reservation__room=room, status='ACTIVE')
        .order_by('-actual_check_in', '-pk')
        .first()
    )
    housekeeping = list(
        HousekeepingTask.objects.select_related('assigned_to')
        .filter(room=room)
        .order_by('-scheduled_date', '-pk')[:8]
    )
    active_housekeeping = [task for task in housekeeping if task.status in ('PENDING', 'IN_PROGRESS')]

    can_collect = _has_role(request.user, COLLECT_ROLES)
    state = 'available'
    if room.operational_status == 'MAINTENANCE':
        state = 'maintenance'
    elif room.operational_status == 'OUT_OF_SERVICE':
        state = 'out_of_service'
    elif current_reservation:
        state = 'occupied'
    elif active_housekeeping:
        state = 'cleaning'

    context = {
        'room': room,
        'today': today,
        'state': state,
        'current_reservation': current_reservation,
        'current_invoice': current_invoice,
        'active_stay': active_stay,
        'next_reservations': next_reservations,
        'recent_reservations': recent_reservations,
        'housekeeping_tasks': housekeeping,
        'active_housekeeping': active_housekeeping,
        'can_collect': can_collect,
    }
    return render(request, 'workspaces/room_detail.html', context)


@role_required('Bartender', 'Waiter', 'Owner')
def bar_table_detail(request, pk):
    table = get_object_or_404(BarTable, pk=pk)
    active_orders = list(
        BarOrder.objects.select_related('customer', 'created_by')
        .prefetch_related('items__drink')
        .filter(table=table)
        .exclude(status__in=['PAID', 'CANCELLED'])
        .order_by('created_at')
    )
    for order in active_orders:
        order.invoice = find_bar_invoice(order)
        order.stay_reservation = active_stay_reservation_for_customer(order.customer) if not order.invoice else None
    unpaid_orders = [o for o in active_orders if o.invoice and o.invoice.balance > 0]
    unbilled_orders = [o for o in active_orders if not o.invoice]
    recent_orders = list(
        BarOrder.objects.select_related('customer', 'created_by')
        .prefetch_related('items__drink')
        .filter(table=table)
        .order_by('-created_at')[:12]
    )
    for order in recent_orders:
        order.invoice = find_bar_invoice(order)
    can_collect = _has_role(request.user, COLLECT_ROLES)
    context = {
        'table': table,
        'active_orders': active_orders,
        'unpaid_orders': unpaid_orders,
        'unbilled_orders': unbilled_orders,
        'recent_orders': recent_orders,
        'can_collect': can_collect,
    }
    return render(request, 'workspaces/bar_table_detail.html', context)


@role_required('Waiter', 'Receptionist', 'Owner')
def service_table_detail(request, pk):
    table = get_object_or_404(Table, pk=pk)
    active_orders = list(
        Order.objects.select_related('customer', 'created_by')
        .prefetch_related('items__menu_item')
        .filter(table=table)
        .exclude(status__in=['PAID', 'CANCELLED'])
        .order_by('created_at')
    )
    for order in active_orders:
        order.invoice = find_order_invoice(order)
        order.stay_reservation = active_stay_reservation_for_customer(order.customer) if not order.invoice else None
    unpaid_orders = [o for o in active_orders if o.invoice and o.invoice.balance > 0]
    unbilled_orders = [o for o in active_orders if not o.invoice]
    recent_orders = list(
        Order.objects.select_related('customer', 'created_by')
        .prefetch_related('items__menu_item')
        .filter(table=table)
        .order_by('-created_at')[:12]
    )
    for order in recent_orders:
        order.invoice = find_order_invoice(order)
    can_collect = _has_role(request.user, COLLECT_ROLES)
    context = {
        'table': table,
        'active_orders': active_orders,
        'unpaid_orders': unpaid_orders,
        'unbilled_orders': unbilled_orders,
        'recent_orders': recent_orders,
        'can_collect': can_collect,
    }
    return render(request, 'workspaces/restaurant_table_detail.html', context)


@role_required('Waiter', 'Receptionist', 'Owner')
def service_charge_room(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.method != 'POST':
        return redirect('workspaces:service')
    try:
        folio, reservation = charge_order_to_stay(order, request.user, bar=False)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f'Commande #{order.pk} imputée à la chambre {reservation.room} (note {folio.number}).',
        )
    next_url = request.POST.get('next')
    if next_url == 'table' and order.table_id:
        return redirect('workspaces:service_table_detail', pk=order.table_id)
    return redirect('workspaces:service')


@role_required('Bartender', 'Waiter', 'Owner')
def bar_charge_room(request, pk):
    order = get_object_or_404(BarOrder, pk=pk)
    next_ws = request.POST.get('next')
    dest = f'workspaces:{next_ws}' if next_ws in ('service', 'bar') else 'workspaces:bar'
    if request.method != 'POST':
        return redirect(dest)
    try:
        folio, reservation = charge_order_to_stay(order, request.user, bar=True)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f'Commande bar #{order.pk} imputée à la chambre {reservation.room} (note {folio.number}).',
        )
    if next_ws == 'table' and order.table_id:
        return redirect('workspaces:bar_table_detail', pk=order.table_id)
    return redirect(dest)


def _collect_fallback_url(request):
    ref = request.META.get('HTTP_REFERER')
    if ref:
        return ref
    roles = set(user_roles(request.user))
    if request.user.is_superuser or 'Owner' in roles or 'Cashier' in roles:
        return reverse('workspaces:cashier')
    if 'Bartender' in roles:
        return reverse('workspaces:bar')
    if 'Receptionist' in roles:
        return reverse('workspaces:reception')
    return reverse('workspaces:service')

# ---------------------------------------------------------------------------
# Cashier — financial operations
# ---------------------------------------------------------------------------

@role_required('Cashier', 'Owner')
def cashier_workspace(request):
    today = timezone.localdate()

    invoice_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    invoices = Invoice.objects.select_related('customer').order_by('-issued_at')
    if invoice_query:
        invoices = invoices.filter(
            Q(number__icontains=invoice_query)
            | Q(customer__first_name__icontains=invoice_query)
            | Q(customer__last_name__icontains=invoice_query)
        )
    if status_filter:
        invoices = invoices.filter(status=status_filter)
    invoice_page = _paginate(request, invoices, 15)

    pending_qs = Invoice.objects.filter(status__in=['ISSUED', 'PARTIAL'])
    pending_invoices = pending_qs.select_related('customer').order_by('-issued_at')[:8]
    pending_invoice_count = pending_qs.count()
    outstanding = pending_qs.aggregate(
        total=Sum(F('total_amount') - F('paid_amount')))['total'] or ZERO

    additions = []
    for order in Order.objects.select_related('customer', 'table').filter(status='SERVED').order_by('created_at')[:12]:
        order.invoice = find_order_invoice(order)
        order.kind = 'restaurant'
        order.kind_label = 'Restaurant'
        additions.append(order)
    for order in BarOrder.objects.select_related('customer', 'table').filter(status='SERVED').order_by('created_at')[:12]:
        order.invoice = find_bar_invoice(order)
        order.kind = 'bar'
        order.kind_label = 'Bar'
        additions.append(order)
    additions.sort(key=lambda o: o.created_at)
    additions = additions[:12]

    payments_today = Payment.objects.filter(paid_at__date=today)
    collected_today = payments_today.aggregate(total=Sum('amount'))['total'] or ZERO
    payments_by_method = list(
        payments_today.values('method__name').annotate(
            total=Sum('amount'), count=Count('id')
        ).order_by('-total')
    )
    recent_payments = Payment.objects.select_related(
        'invoice', 'method', 'received_by').order_by('-paid_at')[:10]

    context = {
        'today': today,
        'invoices': invoice_page,
        'invoice_query': invoice_query,
        'status_filter': status_filter,
        'invoice_statuses': Invoice.STATUS,
        'pending_invoices': pending_invoices,
        'pending_invoice_count': pending_invoice_count,
        'outstanding': outstanding,
        'additions': additions,
        'collected_today': collected_today,
        'payment_count_today': payments_today.count(),
        'payments_by_method': payments_by_method,
        'recent_payments': recent_payments,
        'payment_methods': PaymentMethod.objects.filter(active=True).order_by('name'),
    }
    return render(request, 'workspaces/cashier.html', context)


@role_required(*COLLECT_ROLES)
def payment_create(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    if invoice.balance <= ZERO:
        messages.info(request, 'Cette facture est déjà soldée.')
        return redirect(_collect_fallback_url(request))
    if not invoice.is_payable:
        messages.error(request, 'Seule une facture émise ou partiellement payée peut être encaissée.')
        return redirect(_collect_fallback_url(request))
    initial = {'amount': invoice.balance}
    default_method = PaymentMethod.objects.filter(active=True).order_by('name').first()
    if default_method:
        initial['method'] = default_method.pk
    form = PaymentForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            payment = register_payment(
                invoice,
                form.cleaned_data['amount'],
                form.cleaned_data['method'],
                request.user,
                reference=form.cleaned_data['reference'],
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, 'Paiement enregistré.')
            return redirect('workspaces:payment_receipt', pk=payment.pk)

    return render(request, 'workspaces/payment_form.html', {
        'invoice': invoice,
        'form': form,
        'invoice_items': invoice.items.all(),
        'payment_methods': PaymentMethod.objects.filter(active=True).order_by('name'),
    })


@login_required
def payment_receipt(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related('invoice', 'invoice__customer', 'method', 'received_by'),
        pk=pk,
    )
    back_url = _collect_fallback_url(request)
    can_access_cashier = _has_role(request.user, {'Cashier', 'Owner'})
    return render(request, 'workspaces/receipt.html', {
        'payment': payment,
        'back_url': back_url,
        'can_access_cashier': can_access_cashier,
    })


@role_required(*COLLECT_ROLES)
def cashier_prepare_order_invoice(request, pk):
    order = get_object_or_404(Order, pk=pk)
    dest = request.POST.get('next_url') or request.META.get('HTTP_REFERER') or reverse('workspaces:cashier')
    if request.method != 'POST':
        return redirect(dest)
    try:
        invoice = invoice_for_order(order, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(dest)
    messages.success(request, f'Facture {invoice.number} préparée.')
    return redirect('workspaces:payment_create', pk=invoice.pk)


@role_required(*COLLECT_ROLES)
def cashier_prepare_bar_invoice(request, pk):
    order = get_object_or_404(BarOrder, pk=pk)
    dest = request.POST.get('next_url') or request.META.get('HTTP_REFERER') or reverse('workspaces:cashier')
    if request.method != 'POST':
        return redirect(dest)
    try:
        invoice = invoice_for_bar_order(order, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(dest)
    messages.success(request, f'Facture {invoice.number} préparée.')
    return redirect('workspaces:payment_create', pk=invoice.pk)


# ---------------------------------------------------------------------------
# Finance balance (Owner / Superadmin)
# ---------------------------------------------------------------------------

def _invoice_segment(invoice):
    items = getattr(invoice, '_prefetched_objects_cache', {}).get('items')
    if items is None:
        items = list(invoice.items.all())
    for item in items:
        service = (getattr(item, 'source_service', '') or '').strip().lower()
        if service in ('hôtel', 'hotel'):
            return 'hotel'
        if service == 'restaurant':
            return 'restaurant'
        if service == 'bar':
            return 'bar'
    notes = invoice.notes or ''
    if '[RESERVATION:' in notes:
        return 'hotel'
    if '[ORDER:' in notes:
        return 'restaurant'
    if '[BAR:' in notes:
        return 'bar'
    return 'other'


@role_required('Superadmin', 'Owner')
def finance_balance(request):
    today = timezone.localdate()
    start = _parse_date(request.GET.get('date_from'), today.replace(day=1))
    end = _parse_date(request.GET.get('date_to'), today)
    if end < start:
        end = start

    payments = list(
        Payment.objects.filter(paid_at__date__range=(start, end))
        .select_related('invoice', 'invoice__customer', 'method', 'received_by')
        .prefetch_related('invoice__items')
        .order_by('-paid_at')
    )

    segments = {
        'hotel': {'label': 'Hôtel', 'icon': 'building', 'collected': ZERO, 'count': 0},
        'restaurant': {'label': 'Restaurant', 'icon': 'restaurant', 'collected': ZERO, 'count': 0},
        'bar': {'label': 'Bar', 'icon': 'bar', 'collected': ZERO, 'count': 0},
        'other': {'label': 'Autre', 'icon': 'payments', 'collected': ZERO, 'count': 0},
    }
    for payment in payments:
        key = _invoice_segment(payment.invoice)
        bucket = segments.get(key, segments['other'])
        bucket['collected'] += payment.amount
        bucket['count'] += 1

    segment_rows = [segments['hotel'], segments['restaurant'], segments['bar']]
    if segments['other']['count']:
        segment_rows.append(segments['other'])

    collected_total = sum((s['collected'] for s in segment_rows), ZERO)

    expenses_qs = (
        Expense.objects.filter(date__range=(start, end))
        .select_related('category', 'payment_method', 'responsible_user')
        .order_by('-date', '-pk')
    )
    expenses_total = expenses_qs.aggregate(total=Sum('amount'))['total'] or ZERO
    expenses_by_category = list(
        expenses_qs.values('category__name').annotate(total=Sum('amount'), count=Count('id')).order_by('-total')
    )
    recent_expenses = list(expenses_qs[:20])

    net_balance = collected_total - expenses_total

    outstanding = Invoice.objects.filter(status__in=['ISSUED', 'PARTIAL']).aggregate(
        total=Sum(F('total_amount') - F('paid_amount')))['total'] or ZERO

    period_label = f"{start:%d/%m/%Y} → {end:%d/%m/%Y}"
    context = {
        'today': today,
        'date_from': start,
        'date_to': end,
        'period_label': period_label,
        'segment_rows': segment_rows,
        'collected_total': collected_total,
        'expenses_total': expenses_total,
        'net_balance': net_balance,
        'outstanding': outstanding,
        'expenses_by_category': expenses_by_category,
        'recent_expenses': recent_expenses,
        'recent_payments': payments[:20],
        'payment_count': len(payments),
    }
    return render(request, 'workspaces/finance_balance.html', context)

