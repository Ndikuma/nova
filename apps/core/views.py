from django import forms
from django.apps import apps
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import models
from django.db.models import Count, F, Q, Sum
from django.forms import modelform_factory
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from apps.bar.models import BarOrder, BarOrderItem, BarTable, Drink, DrinkCategory
from apps.finance.models import Expense, Invoice, InvoiceItem, Payment
from apps.hotel.models import BookingRequest, HousekeepingTask, Reservation, Room, RoomRate, Stay
from apps.inventory.models import (Product, PurchaseOrder, PurchaseOrderItem, Recipe,
                                    RecipeIngredient, Stock, StockMovement, Supplier)
from apps.inventory.services import move_stock
from apps.restaurant.models import Menu, MenuItem, Order, OrderItem, RestaurantReservation, Table
from apps.workspaces.services import active_stay_reservation_for_customer, find_bar_invoice, find_order_invoice, find_reservation_invoice, log_action, register_payment
from apps.workspaces.views import workspace_home as _workspace_home
from apps.core.models import AuditLog, Customer

from .navigation import (MODULES, accessible_modules, build_nav, field_label,
                         model_icon, model_label, module_cards, user_can_access_module, user_roles)
from .public_views import public_home

# Fields that should never be shown in the generic list/detail screens.
HIDDEN_FIELDS = {'password', 'last_login', 'date_joined', 'user_permissions', 'groups', 'is_walk_in'}
# User references that the console fills in automatically.
AUDIT_USER_FIELDS = ('created_by', 'updated_by', 'responsible_user', 'received_by', 'opening_user', 'closing_user')
# Technical fields left out of the auto-generated forms for some models.
FORM_EXCLUDES = {
    'User': ('id', 'password', 'last_login', 'date_joined', 'groups', 'user_permissions',
             'is_superuser', 'is_staff'),
    'Invoice': ('paid_amount',),
    'Payment': ('status',),
}


HOUSEKEEPER_HOTEL_MODELS = {'room', 'housekeepingtask'}

def _ensure_module_access(request, module, entity=None):
    if module not in MODULES:
        raise Http404('Module introuvable')
    if not user_can_access_module(request.user, module):
        raise PermissionDenied('Vous n’avez pas accès à ce module.')
    if entity and module == 'hotel':
        roles = set(user_roles(request.user))
        if 'Housekeeper' in roles and not (request.user.is_superuser or bool({'Owner','Receptionist'} & roles)):
            if entity.lower() not in HOUSEKEEPER_HOTEL_MODELS:
                raise PermissionDenied('Accès limité aux chambres et tâches housekeeping.')


def model_for(module, entity):
    cfg = MODULES.get(module)
    if not cfg:
        raise Http404('Module introuvable')
    canonical = next((name for name in cfg['models'] if name.lower() == entity.lower()), None)
    if not canonical:
        raise Http404('Écran introuvable')
    try:
        return apps.get_model(module, canonical)
    except LookupError:
        raise Http404('Modèle introuvable')


def label(entity):
    return model_label(entity)


def field_value(obj, field):
    """Return a human friendly value for a model field."""
    value = getattr(obj, field.name, None)
    if value is None or value == '':
        return '—'
    if field.choices:
        return dict(field.choices).get(value, value)
    if isinstance(field, models.BooleanField):
        return 'Oui' if value else 'Non'
    if isinstance(field, models.DateTimeField):
        return value
    if isinstance(field, models.DateField):
        return value
    if isinstance(field, (list, dict)):
        return str(value)
    return str(value)


def _visible_fields(model):
    return [f for f in model._meta.fields if f.name != 'id' and f.name not in HIDDEN_FIELDS]


def _record_cells(obj, fields):
    """Build the cell list for the list/detail screens."""
    cells = []
    for field in fields:
        value = getattr(obj, field.name, None)
        cells.append({
            'name': field.name,
            'label': field_label(field.name, field.verbose_name.capitalize()),
            'value': field_value(obj, field),
            'raw': value,
            'is_status': field.name.endswith('status') or field.name in ('kind', 'movement_type'),
            'is_date': isinstance(field, models.DateField),
            'is_datetime': isinstance(field, models.DateTimeField),
        })
    return cells


def _formfield_callback(field):

    formfield = field.formfield()
    if formfield is None:
        return None
    widget = formfield.widget

    if isinstance(field, models.BooleanField):
        widget = forms.CheckboxInput()
    elif isinstance(field, models.DateTimeField):
        widget = forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'})
    elif isinstance(field, models.DateField):
        widget = forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'})
    elif isinstance(field, models.TextField):
        widget = forms.Textarea(attrs={'rows': 3})
    elif isinstance(field, models.DecimalField):
        step = '0.001' if field.decimal_places >= 3 else ('0.01' if field.decimal_places >= 2 else '1')
        widget = forms.NumberInput(attrs={'step': step})
    elif isinstance(field, models.IntegerField):
        widget = forms.NumberInput()
    elif isinstance(field, models.EmailField):
        widget = forms.EmailInput()

    formfield.widget = widget
    formfield.label = field_label(field.name, formfield.label)

    if isinstance(widget, forms.CheckboxInput):
        css = 'checkbox-input'
    elif isinstance(widget, forms.Select):
        css = 'select-input'
    elif isinstance(widget, forms.Textarea):
        css = 'textarea-input'
    elif isinstance(widget, forms.FileInput):
        css = 'file-input'
    else:
        css = 'text-input'
    widget.attrs['class'] = (widget.attrs.get('class', '') + ' ' + css).strip()
    return formfield


def build_form(model):
    excludes = list(FORM_EXCLUDES.get(model.__name__, ()))
    if 'id' not in excludes:
        excludes.append('id')
    field_names = {f.name for f in model._meta.fields}
    excludes.extend(name for name in AUDIT_USER_FIELDS if name in field_names)
    return modelform_factory(model, exclude=tuple(excludes), formfield_callback=_formfield_callback)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

WEEKDAYS = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim']


def _quick_actions(user):
    actions = [
        {'module': 'hotel', 'label': 'Nouvelle réservation', 'meta': 'Planifier une arrivée',
         'url': reverse('entity_create', args=['hotel', 'reservation']),
         'icon': 'reservations', 'tone': 'blue'},
        {'module': 'restaurant', 'label': 'Nouvelle commande', 'meta': 'Ouvrir une table ou un takeaway',
         'url': reverse('entity_create', args=['restaurant', 'order']),
         'icon': 'orders', 'tone': 'orange'},
        {'module': 'finance', 'label': 'Nouveau paiement', 'meta': 'Encaisser une facture',
         'url': reverse('entity_create', args=['finance', 'payment']),
         'icon': 'payments', 'tone': 'green'},
        {'module': 'inventory', 'label': 'Nouveau mouvement de stock', 'meta': 'Entrée, sortie ou ajustement',
         'url': reverse('entity_create', args=['inventory', 'stockmovement']),
         'icon': 'inventory', 'tone': 'dark'},
    ]
    return [action for action in actions if user_can_access_module(user, action['module'])]


def _weekly_performance(today):
    series = []
    max_revenue = Decimal('0')
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        revenue = Payment.objects.filter(paid_at__date=day).aggregate(total=Sum('amount'))['total'] or 0
        reservations = Reservation.objects.filter(created_at__date=day).count()
        orders = (Order.objects.filter(created_at__date=day).count()
                  + BarOrder.objects.filter(created_at__date=day).count())
        max_revenue = max(max_revenue, revenue)
        series.append({
            'date': day,
            'label': WEEKDAYS[day.weekday()],
            'short_date': day.strftime('%d/%m'),
            'revenue': revenue,
            'reservations': reservations,
            'orders': orders,
        })
    for row in series:
        pct = int(round(float(row['revenue']) / float(max_revenue) * 100)) if max_revenue else 0
        row['pct'] = max(pct, 6) if row['revenue'] else 2
    totals = {
        'revenue': sum((row['revenue'] for row in series), Decimal('0')),
        'reservations': sum(row['reservations'] for row in series),
        'orders': sum(row['orders'] for row in series),
    }
    return series, totals


def _health_snapshot(today, low_stock, pending_invoices, allowed):
    items = []
    penalties = 0
    if 'inventory' in allowed:
        items.append({'label': 'Stocks', 'ok': low_stock == 0,
                      'detail': 'Tous les seuils sont respectés' if low_stock == 0 else f'{low_stock} alerte(s) de stock'})
        penalties += low_stock * 6
    if 'hotel' in allowed:
        overdue_tasks = HousekeepingTask.objects.filter(
            status__in=['PENDING', 'IN_PROGRESS'], scheduled_date__lt=today
        ).count()
        items.append({'label': 'Housekeeping', 'ok': overdue_tasks == 0,
                      'detail': 'Aucune tâche en retard' if overdue_tasks == 0 else f'{overdue_tasks} tâche(s) en retard'})
        penalties += overdue_tasks * 8
    if 'finance' in allowed:
        items.append({'label': 'Encaissements', 'ok': pending_invoices == 0,
                      'detail': 'Toutes les factures sont réglées' if pending_invoices == 0 else f'{pending_invoices} facture(s) à traiter'})
        penalties += max(0, pending_invoices - 3) * 4
    score = max(0, 100 - penalties)
    if not items:
        return {'score': 100, 'status': 'good', 'label': 'Aucune alerte sur vos périmètres',
                'items': [{'label': 'Périmètre', 'ok': True, 'detail': 'Modules autorisés opérationnels'}]}
    if score >= 80:
        status, label = 'good', 'Établissement en bonne santé'
    elif score >= 55:
        status, label = 'warning', 'À surveiller'
    else:
        status, label = 'critical', 'Action requise'
    return {'score': score, 'status': status, 'label': label, 'items': items}


def dashboard(request):
    if not request.user.is_authenticated:
        return public_home(request)
    # Route staff users to their operational workspace when available.
    from apps.core.navigation import primary_workspace
    if primary_workspace(request.user):
        return redirect('workspaces:home')
    return staff_dashboard(request)


@login_required
def staff_dashboard(request):
    today = timezone.localdate()
    reserved_statuses = ['CONFIRMED', 'CHECKED_IN']

    counts = {
        'rooms': Room.objects.count(),
        'available_rooms': Room.objects.filter(operational_status='AVAILABLE').count(),
        'reservations': Reservation.objects.filter(status__in=reserved_statuses).count(),
        'arrivals': Reservation.objects.filter(check_in=today).exclude(status='CANCELLED').count(),
        'departures': Reservation.objects.filter(check_out=today).exclude(status='CANCELLED').count(),
        'restaurant_orders': Order.objects.exclude(status__in=['PAID', 'CANCELLED']).count(),
        'bar_orders': BarOrder.objects.exclude(status__in=['PAID', 'CANCELLED']).count(),
        'pending_invoices': Invoice.objects.filter(status__in=['ISSUED', 'PARTIAL']).count(),
        'customers': Customer.objects.count(),
    }
    counts['open_orders'] = counts['restaurant_orders'] + counts['bar_orders']
    counts['occupied_rooms'] = Reservation.objects.filter(
        status__in=reserved_statuses, check_in__lte=today, check_out__gt=today
    ).values('room_id').distinct().count()
    counts['occupancy_rate'] = (
        round(counts['occupied_rooms'] / counts['rooms'] * 100) if counts['rooms'] else 0
    )

    low_stock = _low_stock_count()
    overdue = Stock.objects.select_related('product', 'location').filter(
        Q(quantity__lte=0) | Q(quantity__lt=F('product__minimum_stock'))
    ).order_by('quantity')[:6]

    revenue = Payment.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    outstanding = Invoice.objects.filter(status__in=['ISSUED', 'PARTIAL']).aggregate(
        total=Sum(F('total_amount') - F('paid_amount'))
    )['total'] or Decimal('0')
    estimated_revenue = revenue + outstanding

    recent_reservations = Reservation.objects.select_related(
        'customer', 'room', 'room__room_type'
    ).order_by('-created_at')[:6]

    arrivals = Reservation.objects.select_related('customer', 'room').filter(
        check_in=today
    ).exclude(status='CANCELLED').order_by('check_in')[:5]

    departures = Reservation.objects.select_related('customer', 'room').filter(
        check_out=today
    ).exclude(status='CANCELLED').order_by('check_out')[:5]

    upcoming_arrivals = Reservation.objects.select_related(
        'customer', 'room', 'room__room_type'
    ).filter(
        check_in__gte=today, check_in__lte=today + timedelta(days=7)
    ).exclude(status__in=['CANCELLED', 'CHECKED_OUT']).order_by('check_in', 'customer__last_name')[:8]

    weekly, week_totals = _weekly_performance(today)
    allowed = accessible_modules(request.user)
    health = _health_snapshot(today, low_stock, counts['pending_invoices'], allowed)

    module_summary = []
    for module, cfg in MODULES.items():
        if module not in allowed:
            continue
        total = 0
        for name in cfg['models']:
            try:
                total += apps.get_model(module, name).objects.count()
            except LookupError:
                pass
        module_summary.append({
            'key': module,
            'title': cfg['title'],
            'icon': cfg['icon'],
            'description': cfg['description'],
            'url': f'/module/{module}/',
            'count': total,
        })

    context = {
        'today': today,
        'counts': counts,
        'rooms': counts['rooms'],
        'available_rooms': counts['available_rooms'],
        'reservations': counts['reservations'],
        'restaurant_orders': counts['restaurant_orders'],
        'pending_invoices': counts['pending_invoices'],
        'low_stock': low_stock,
        'overdue_stock': overdue,
        'revenue': revenue,
        'outstanding': outstanding,
        'estimated_revenue': estimated_revenue,
        'occupancy_rate': counts['occupancy_rate'],
        'occupied_rooms': counts['occupied_rooms'],
        'recent_reservations': recent_reservations,
        'arrivals': arrivals,
        'departures': departures,
        'upcoming_arrivals': upcoming_arrivals,
        'weekly': weekly,
        'week_totals': week_totals,
        'health': health,
        'quick_actions': _quick_actions(request.user),
        'module_summary': module_summary,
        'allowed_modules': allowed,
        'modules': MODULES,
    }
    return render(request, 'dashboard.html', context)


# ---------------------------------------------------------------------------
# Module home
# ---------------------------------------------------------------------------

def _low_stock_qs():
    return Stock.objects.select_related('product', 'location').filter(
        Q(quantity__lte=0) | Q(quantity__lt=F('product__minimum_stock'))
    ).order_by('quantity')


def _low_stock_count():
    return _low_stock_qs().count()


def _fmt_money(value):
    try:
        return f'{value:,.0f}'.replace(',', ' ') + ' F'
    except (TypeError, ValueError):
        return value


def _stat(label, value, meta='', tone='', money=False):
    return {'label': label, 'value': value, 'meta': meta, 'tone': tone, 'money': money}


def _item(label, meta='', url='', status='', status_label=''):
    return {'label': label, 'meta': meta, 'url': url, 'status': status,
            'status_label': status_label or status}


def _panel(title, description, rows, kind='list', eyebrow='', empty='Aucune donnée pour le moment.'):
    return {'title': title, 'description': description, 'rows': rows, 'kind': kind,
            'eyebrow': eyebrow, 'empty': empty}


def _detail_url(module, entity, pk):
    return reverse('entity_detail', args=[module, entity, pk])


def _create_url(module, entity):
    return reverse('entity_create', args=[module, entity])


def _list_url(module, entity):
    return reverse('entity_list', args=[module, entity])


def _hotel_overview(today):
    rooms = Room.objects.count()
    available = Room.objects.filter(operational_status='AVAILABLE').count()
    maintenance = Room.objects.filter(operational_status='MAINTENANCE').count()
    out_of_service = Room.objects.filter(operational_status='OUT_OF_SERVICE').count()
    active_reservations = Reservation.objects.filter(status__in=['CONFIRMED', 'CHECKED_IN']).count()
    occupied_rooms = Reservation.objects.filter(
        status__in=['CONFIRMED', 'CHECKED_IN'], check_in__lte=today, check_out__gt=today
    ).values('room_id').distinct().count()
    occupancy_rate = round(occupied_rooms / rooms * 100) if rooms else 0
    arrivals = Reservation.objects.select_related('customer', 'room').filter(
        check_in=today).exclude(status='CANCELLED').order_by('customer__last_name')
    departures = Reservation.objects.select_related('customer', 'room').filter(
        check_out=today).exclude(status='CANCELLED').order_by('customer__last_name')
    upcoming = Reservation.objects.select_related('customer', 'room').filter(
        check_in__gte=today, check_in__lte=today + timedelta(days=14)
    ).exclude(status__in=['CANCELLED', 'CHECKED_OUT']).order_by('check_in')[:6]
    pending_tasks = HousekeepingTask.objects.filter(status__in=['PENDING', 'IN_PROGRESS']).count()
    tasks = HousekeepingTask.objects.select_related('room', 'assigned_to').filter(
        status__in=['PENDING', 'IN_PROGRESS']).order_by('scheduled_date')[:6]
    stays = Stay.objects.filter(status='ACTIVE').count()
    rates = RoomRate.objects.select_related('room_type').filter(active=True).order_by('price')[:6]

    highlights = [
        {'label': 'Chambres', 'value': rooms, 'tone': 'blue', 'icon': 'bed',
         'meta': f'{available} disponibles · {occupancy_rate}% d’occupation'},
        {'label': 'Réservations', 'value': active_reservations, 'tone': 'green', 'icon': 'reservations',
         'meta': f'{arrivals.count()} arrivée(s) · {departures.count()} départ(s) aujourd’hui'},
        {'label': 'Séjours', 'value': stays, 'tone': 'orange', 'icon': 'frontdesk',
         'meta': 'séjours actifs en cours'},
        {'label': 'Housekeeping', 'value': pending_tasks, 'tone': 'danger' if pending_tasks else 'dark',
         'icon': 'housekeeping', 'meta': 'tâches à traiter'},
    ]
    movement_rows = [
        _item(f'Arrivée · {r.customer}', f'Ch. {r.room} · {r.check_in:%d/%m/%Y}',
              _detail_url('hotel', 'reservation', r.pk), r.status, r.get_status_display())
        for r in arrivals[:4]
    ] + [
        _item(f'Départ · {r.customer}', f'Ch. {r.room} · {r.check_out:%d/%m/%Y}',
              _detail_url('hotel', 'reservation', r.pk), r.status, r.get_status_display())
        for r in departures[:4]
    ]
    panels = [
        _panel('Occupation & disponibilité', 'Vue temps réel des chambres et de leur état.',
               [_stat('Disponibles', available, f'sur {rooms} chambres', 'green'),
                _stat('Occupées', occupied_rooms, f'{occupancy_rate}% d’occupation', 'blue'),
                _stat('Maintenance', maintenance, 'à préparer', 'warning' if maintenance else ''),
                _stat('Hors service', out_of_service, 'à remettre en service', 'danger' if out_of_service else '')],
               kind='stats', eyebrow='Hôtel'),
        _panel('Arrivées & départs', 'Les mouvements à accueillir et à libérer aujourd’hui.',
               movement_rows, eyebrow='Aujourd’hui', empty='Aucun mouvement prévu aujourd’hui.'),
        _panel('Réservations à venir', 'Les prochaines arrivées sur 14 jours.',
               [_item(f'{r.customer} · Ch. {r.room}', f'{r.check_in:%d/%m} → {r.check_out:%d/%m}',
                      _detail_url('hotel', 'reservation', r.pk), r.status, r.get_status_display())
                for r in upcoming], eyebrow='Planning', empty='Aucune réservation à venir.'),
        _panel('Housekeeping & maintenance', 'Tâches de l’équipe et interventions planifiées.',
               [_item(f'Ch. {t.room} · {t.get_task_type_display()}',
                      f'{t.scheduled_date:%d/%m/%Y} · {t.assigned_to or "Non assigné"}',
                      _detail_url('hotel', 'housekeepingtask', t.pk), t.status, t.get_status_display())
                for t in tasks], eyebrow='Équipe', empty='Aucune tâche en attente.'),
        _panel('Tarifs actifs', 'Grille tarifaire appliquée aux types de chambres.',
               [_item(rate.room_type.name, f'À partir de {_fmt_money(rate.price)}',
                      _detail_url('hotel', 'roomrate', rate.pk), 'ACTIVE', 'Actif')
                for rate in rates], eyebrow='Tarification', empty='Aucun tarif actif.'),
    ]
    components = ['Types de chambre', 'Chambres', 'Tarifs', 'Réservations', 'Séjours', 'Housekeeping']
    quick_actions = [
        {'label': 'Nouvelle réservation', 'meta': 'Créer une demande', 'icon': 'reservations',
         'url': reverse('workspaces:reservation_create')},
        {'label': 'Voir les données', 'meta': 'Toutes les réservations', 'icon': 'reservations',
         'url': _list_url('hotel', 'reservation')},
    ]
    note = ('Les écrans CRUD Hôtel restent accessibles sous chaque carte. '
            'La disponibilité et l’occupation sont recalculées à chaque chargement.')
    return highlights, panels, components, quick_actions, note


def _restaurant_overview(today):
    reservation_labels = {'CONFIRMED': 'Confirmée', 'PENDING': 'En attente',
                          'SEATED': 'Installée', 'CANCELLED': 'Annulée'}
    tables = Table.objects.count()
    available_tables = Table.objects.filter(status='AVAILABLE').count()
    menus = Menu.objects.count()
    items = MenuItem.objects.count()
    available_items = MenuItem.objects.filter(available=True).count()
    open_orders = Order.objects.exclude(status__in=['PAID', 'CANCELLED'])
    orders = open_orders.count()
    reservations = RestaurantReservation.objects.count()
    statuses = {code: Order.objects.filter(status=code).count()
                for code in ['OPEN', 'PREPARING', 'READY', 'SERVED']}
    sources = {code: Order.objects.filter(source=code).count()
               for code in ['DINE_IN', 'TAKEAWAY', 'ROOM_SERVICE']}
    recent_orders = open_orders.select_related('customer', 'table').order_by('-created_at')[:6]
    upcoming = RestaurantReservation.objects.select_related('customer', 'table').filter(
        reservation_at__date__gte=today).order_by('reservation_at')[:6]

    highlights = [
        {'label': 'Tables', 'value': tables, 'tone': 'blue', 'icon': 'table',
         'meta': f'{available_tables} disponibles'},
        {'label': 'Menus', 'value': menus, 'tone': 'green', 'icon': 'menu',
         'meta': f'{items} plats & boissons'},
        {'label': 'Commandes', 'value': orders, 'tone': 'orange', 'icon': 'orders',
         'meta': f'{statuses["PREPARING"]} en préparation · {statuses["READY"]} prêtes'},
        {'label': 'Réservations de salle', 'value': reservations, 'tone': 'dark', 'icon': 'reservations',
         'meta': 'demandes enregistrées'},
    ]
    panels = [
        _panel('Commandes & statuts cuisine', 'Commandes ouvertes et avancement en cuisine.',
               [_item(f'Commande #{o.pk} · {o.customer or "Sans client"}',
                      f'{o.table or o.get_source_display()} · {_fmt_money(o.total_amount)}',
                      _detail_url('restaurant', 'order', o.pk), o.status, o.get_status_display())
                for o in recent_orders], eyebrow='Service', empty='Aucune commande en cours.'),
        _panel('Menus & plats', 'Catalogue disponible pour le service.',
               [_stat('Menus', menus, 'cartes actives', 'blue'),
                _stat('Plats & boissons', items, 'références', 'green'),
                _stat('Disponibles', available_items, 'prêts à la vente', 'orange'),
                _stat('Indisponibles', items - available_items,
                      'à réapprovisionner', 'danger' if items - available_items else '')],
               kind='stats', eyebrow='Carte'),
        _panel('Tables & réservations', 'Occupation de la salle et prochains services.',
               [_item(f'Table {t.name}', f'{t.capacity} couverts · {t.section or "Salle"}',
                      _detail_url('restaurant', 'table', t.pk), t.status, t.get_status_display())
                for t in Table.objects.order_by('name')[:5]]
               + [_item(f'Réservation · {r.customer}',
                         f'{r.reservation_at:%d/%m %H:%M} · {r.guests} convives',
                         _detail_url('restaurant', 'restaurantreservation', r.pk), r.status,
                         reservation_labels.get(r.status, r.status))
                  for r in upcoming[:4]], eyebrow='Salle', empty='Aucune table configurée.'),
        _panel('Service sur place & takeaway', 'Répartition des commandes par mode de service.',
               [_stat('Sur place', sources['DINE_IN'], 'service en salle', 'blue'),
                _stat('À emporter', sources['TAKEAWAY'], 'commandes takeaway', 'orange'),
                _stat('Room service', sources['ROOM_SERVICE'], 'livraison en chambre', 'green')],
               kind='stats', eyebrow='Modes'),
    ]
    components = ['Tables', 'Menus', 'Plats & boissons', 'Commandes', 'Réservations restaurant']
    quick_actions = [
        {'label': 'Nouvelle commande', 'meta': 'Ouvrir une commande', 'icon': 'orders',
         'url': _create_url('restaurant', 'order')},
        {'label': 'Voir les commandes', 'meta': 'Suivi du service', 'icon': 'orders',
         'url': _list_url('restaurant', 'order')},
    ]
    note = ('Les commandes peuvent être créées sur place, à emporter ou en room service. '
            'Les statuts cuisine sont mis à jour depuis chaque fiche commande.')
    return highlights, panels, components, quick_actions, note


def _bar_overview(today):
    bar_table_labels = {'AVAILABLE': 'Disponible', 'OCCUPIED': 'Occupée',
                        'RESERVED': 'Réservée', 'CLOSED': 'Fermée'}
    drinks = Drink.objects.count()
    available_drinks = Drink.objects.filter(available=True).count()
    categories = DrinkCategory.objects.count()
    tables = BarTable.objects.count()
    available_tables = BarTable.objects.filter(status='AVAILABLE').count()
    orders = BarOrder.objects.exclude(status__in=['PAID', 'CANCELLED']).count()
    statuses = {code: BarOrder.objects.filter(status=code).count()
                for code in ['OPEN', 'PREPARING', 'SERVED']}
    recent_orders = BarOrder.objects.exclude(status__in=['PAID', 'CANCELLED']).select_related(
        'customer', 'table').order_by('-created_at')[:6]
    price_list = Drink.objects.select_related('category').filter(available=True).order_by('-selling_price')[:6]

    highlights = [
        {'label': 'Boissons', 'value': drinks, 'tone': 'blue', 'icon': 'products',
         'meta': f'{available_drinks} disponibles'},
        {'label': 'Catégories', 'value': categories, 'tone': 'green', 'icon': 'menu',
         'meta': 'familles de boissons'},
        {'label': 'Tables', 'value': tables, 'tone': 'orange', 'icon': 'table',
         'meta': f'{available_tables} libres'},
        {'label': 'Commandes bar', 'value': orders, 'tone': 'dark', 'icon': 'orders',
         'meta': f'{statuses["PREPARING"]} en préparation · {statuses["SERVED"]} servies'},
    ]
    panels = [
        _panel('Commandes du bar', 'Commandes ouvertes et statut de service.',
               [_item(f'Commande #{o.pk} · {o.customer or "Sans client"}',
                      f'{o.table or "Comptoir"} · {_fmt_money(o.total_amount)}',
                      _detail_url('bar', 'barorder', o.pk), o.status, o.get_status_display())
                for o in recent_orders], eyebrow='Service', empty='Aucune commande au bar.'),
        _panel('Boissons & catégories', 'Catalogue et disponibilité du bar.',
               [_stat('Boissons', drinks, 'références', 'blue'),
                _stat('Disponibles', available_drinks, 'prêtes à servir', 'green'),
                _stat('Catégories', categories, 'familles', 'orange')],
               kind='stats', eyebrow='Carte'),
        _panel('Tables & capacité', 'Occupation et capacité du bar.',
               [_item(f'Table {t.name}', f'{t.capacity} places',
                      _detail_url('bar', 'bartable', t.pk), t.status,
                      bar_table_labels.get(t.status, t.status))
                for t in BarTable.objects.order_by('name')[:6]], eyebrow='Salle', empty='Aucune table configurée.'),
        _panel('Disponibilité et prix', 'Boissons disponibles triées par prix.',
               [_item(f'{d.name}', f'{d.category.name} · {_fmt_money(d.selling_price)}',
                      _detail_url('bar', 'drink', d.pk), 'ACTIVE', 'Disponible')
                for d in price_list], eyebrow='Tarifs', empty='Aucune boisson disponible.'),
    ]
    components = ['Catégories de boissons', 'Boissons', 'Tables du bar', 'Commandes bar']
    quick_actions = [
        {'label': 'Nouvelle commande bar', 'meta': 'Ouvrir une commande', 'icon': 'orders',
         'url': _create_url('bar', 'barorder')},
        {'label': 'Voir les boissons', 'meta': 'Carte et prix', 'icon': 'products',
         'url': _list_url('bar', 'drink')},
    ]
    note = ('La disponibilité des boissons et l’état des tables du bar sont visibles en temps réel. '
            'Les commandes bar suivent le même cycle de service que le restaurant.')
    return highlights, panels, components, quick_actions, note


def _inventory_overview(today):
    purchase_labels = {'DRAFT': 'Brouillon', 'ORDERED': 'Commandé', 'PARTIAL': 'Partielle',
                       'RECEIVED': 'Reçu', 'CANCELLED': 'Annulée'}
    products = Product.objects.count()
    active_products = Product.objects.filter(active=True).count()
    stocks = Stock.objects.count()
    movements = StockMovement.objects.count()
    suppliers = Supplier.objects.count()
    low_stock = _low_stock_qs()
    low_count = low_stock.count()
    recent_movements = StockMovement.objects.select_related(
        'product', 'location', 'responsible_user').order_by('-date')[:6]
    purchase_orders = PurchaseOrder.objects.select_related('supplier').order_by('-order_date')[:5]
    recipes = Recipe.objects.count()
    ingredients = RecipeIngredient.objects.count()
    pending_po = PurchaseOrder.objects.exclude(status__in=['RECEIVED', 'CANCELLED']).count()

    highlights = [
        {'label': 'Produits', 'value': products, 'tone': 'blue', 'icon': 'products',
         'meta': f'{active_products} actifs'},
        {'label': 'Stocks', 'value': stocks, 'tone': 'green', 'icon': 'inventory',
         'meta': f'{low_count} alerte(s) de seuil'},
        {'label': 'Mouvements', 'value': movements, 'tone': 'orange', 'icon': 'inventory',
         'meta': 'entrées, sorties et ajustements'},
        {'label': 'Fournisseurs', 'value': suppliers, 'tone': 'dark', 'icon': 'team',
         'meta': f'{pending_po} achat(s) en cours'},
    ]
    panels = [
        _panel('Niveaux de stock & seuils', 'Produits sous le seuil minimum ou en rupture.',
               [_item(f'{s.product.name} · {s.location.name}',
                      f'Quantité {s.quantity} / seuil {s.product.minimum_stock}',
                      _detail_url('inventory', 'stock', s.pk), 'LOW', 'À réapprovisionner')
                for s in low_stock[:6]], eyebrow='Vigilance', empty='Tous les stocks sont au-dessus du seuil.'),
        _panel('Mouvements traçables', 'Dernières entrées, sorties et corrections de stock.',
               [_item(f'{m.product.name} · {m.get_movement_type_display()}',
                      f'{m.location.name} · {m.quantity} · {m.date:%d/%m %H:%M}',
                      _detail_url('inventory', 'stockmovement', m.pk), m.movement_type,
                      m.get_movement_type_display())
                for m in recent_movements], eyebrow='Traçabilité', empty='Aucun mouvement enregistré.'),
        _panel('Achats & fournisseurs', 'Partenaires et bons de commande en cours.',
               [_stat('Fournisseurs', suppliers, 'partenaires', 'green'),
                _stat('Bons de commande', PurchaseOrder.objects.count(), 'achats', 'blue'),
                _stat('En cours', pending_po, 'à réceptionner', 'orange')],
               kind='stats', eyebrow='Achats')
        ,
        _panel('Bons de commande récents', 'Commandes fournisseurs à suivre.',
               [_item(f'Bon #{po.pk} · {po.supplier.name}',
                      f'{po.order_date:%d/%m/%Y} · {_fmt_money(po.total_amount)}',
                      _detail_url('inventory', 'purchaseorder', po.pk), po.status,
                      purchase_labels.get(po.status, po.status))
                for po in purchase_orders], eyebrow='Réception', empty='Aucun bon de commande.'),
        _panel('Recettes & ingrédients', 'Fiches techniques et composants.',
               [_stat('Recettes', recipes, 'fiches techniques', 'blue'),
                _stat('Ingrédients', ingredients, 'lignes de recette', 'green')],
               kind='stats', eyebrow='Production'),
    ]
    components = ['Unités de mesure', 'Catégories de produits', 'Produits', 'Stocks',
                  'Mouvements de stock', 'Fournisseurs', 'Bons de commande', 'Recettes']
    quick_actions = [
        {'label': 'Nouveau mouvement de stock', 'meta': 'Entrée, sortie ou ajustement', 'icon': 'inventory',
         'url': _create_url('inventory', 'stockmovement')},
        {'label': 'Voir les stocks', 'meta': 'Niveaux et seuils', 'icon': 'inventory',
         'url': _list_url('inventory', 'stock')},
    ]
    note = ('Chaque mouvement de stock est horodaté et rattaché à un responsable. '
            'Les seuils minimum déclenchent les alertes affichées sur le dashboard.')
    return highlights, panels, components, quick_actions, note


def _finance_overview(today):
    invoices = Invoice.objects.count()
    pending = Invoice.objects.filter(status__in=['ISSUED', 'PARTIAL'])
    payments_total = Payment.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    expenses_total = Expense.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    outstanding = pending.aggregate(total=Sum(F('total_amount') - F('paid_amount')))['total'] or Decimal('0')
    recent_invoices = pending.select_related('customer').order_by('-issued_at')[:6]
    recent_expenses = Expense.objects.select_related('category').order_by('-date')[:5]
    recent_payments = Payment.objects.select_related('invoice', 'method', 'received_by').order_by('-paid_at')[:6]

    highlights = [
        {'label': 'Factures', 'value': invoices, 'tone': 'blue', 'icon': 'invoices',
         'meta': f'{pending.count()} à encaisser'},
        {'label': 'À encaisser', 'value': outstanding, 'tone': 'orange', 'icon': 'payments',
         'meta': 'solde des factures ouvertes', 'money': True},
        {'label': 'Encaissé', 'value': payments_total, 'tone': 'green', 'icon': 'payments',
         'meta': 'paiements enregistrés', 'money': True},
        {'label': 'Dépenses', 'value': expenses_total, 'tone': 'danger', 'icon': 'payments',
         'meta': 'sorties enregistrées', 'money': True},
    ]
    panels = [
        _panel('Factures & encaissements', 'Factures en attente et solde restant.',
               [_item(f'Facture {inv.number} · {inv.customer}',
                      f'Solde {_fmt_money(inv.balance)} · émise le {inv.issued_at:%d/%m/%Y}',
                      _detail_url('finance', 'invoice', inv.pk), inv.status, inv.get_status_display())
                for inv in recent_invoices], eyebrow='Recouvrement', empty='Aucune facture en attente.'),
        _panel('Montants à encaisser', 'Suivi des règlements et soldes ouverts.',
               [_stat('Factures émises', Invoice.objects.filter(status='ISSUED').count(), 'à encaisser', 'blue'),
                _stat('Paiements partiels', Invoice.objects.filter(status='PARTIAL').count(), 'soldes ouverts', 'orange'),
                _stat('Encaissé (cumul)', payments_total, 'paiements', 'green', money=True),
                _stat('Reste à encaisser', outstanding, 'sur factures ouvertes', 'danger', money=True)],
               kind='stats', eyebrow='Trésorerie'),
        _panel('Dépenses & catégories', 'Dernières sorties de caisse et leur nature.',
               [_item(e.description, f'{e.category.name} · {_fmt_money(e.amount)} · {e.date:%d/%m/%Y}',
                      _detail_url('finance', 'expense', e.pk))
                for e in recent_expenses], eyebrow='Dépenses', empty='Aucune dépense enregistrée.'),
        _panel('Derniers encaissements', 'Paiements reçus récemment.',
               [_item(f'{p.invoice.number} · {p.invoice.customer}', f'{p.method.name} · {_fmt_money(p.amount)}',
                      _detail_url('finance', 'payment', p.pk), p.status, 'Encaissé')
                for p in recent_payments], eyebrow='Encaissements', empty='Aucun paiement enregistré.'),
    ]
    components = ['Factures', 'Paiements', 'Dépenses']
    quick_actions = [
        {'label': 'Nouvelle facture', 'meta': 'Créer une facture client', 'icon': 'invoices',
         'url': _create_url('finance', 'invoice')},
        {'label': 'Nouveau paiement', 'meta': 'Encaisser une facture', 'icon': 'payments',
         'url': _create_url('finance', 'payment')},
    ]
    note = ('Les paiements partiels sont suivis sur chaque facture. '
            'Les montants à encaisser correspondent aux soldes des factures émises ou partiellement payées.')
    return highlights, panels, components, quick_actions, note


def _core_overview(today):
    customers = Customer.objects.count()
    users = get_user_model().objects.count()
    groups = Group.objects.count()
    audit_count = AuditLog.objects.count()
    recent_customers = Customer.objects.order_by('-created_at')[:6]
    recent_logs = AuditLog.objects.select_related('user').order_by('-timestamp')[:6]
    group_rows = Group.objects.annotate(member_count=Count('user')).order_by('name')[:8]

    highlights = [
        {'label': 'Clients', 'value': customers, 'tone': 'blue', 'icon': 'guests',
         'meta': 'fiches partagées'},
        {'label': 'Utilisateurs', 'value': users, 'tone': 'green', 'icon': 'team',
         'meta': 'comptes actifs'},
        {'label': 'Groupes', 'value': groups, 'tone': 'orange', 'icon': 'team',
         'meta': 'rôles et permissions'},
        {'label': 'Journal d’audit', 'value': audit_count, 'tone': 'dark', 'icon': 'audit',
         'meta': 'événements tracés'},
    ]
    panels = [
        _panel('Fiches clients partagées', 'Clients récents et coordonnées de contact.',
               [_item(str(c), f'{c.phone} · {c.email or "Sans e-mail"} · {c.address or "Adresse non renseignée"}',
                      _detail_url('core', 'customer', c.pk))
                for c in recent_customers], eyebrow='Clients', empty='Aucun client enregistré.'),
        _panel('Utilisateurs & groupes', 'Comptes et rôles de l’équipe.',
               [_stat('Utilisateurs', users, 'comptes', 'green'),
                _stat('Groupes', groups, 'rôles', 'blue'),
                _stat('Journal d’audit', audit_count, 'événements', 'dark')],
               kind='stats', eyebrow='Équipe'),
        _panel('Groupes & accès', 'Membres rattachés à chaque rôle.',
               [_item(g.name, f'{g.member_count} membre(s)',
                      _list_url('core', 'user'), 'ACTIVE', 'Actif')
                for g in group_rows], eyebrow='Permissions', empty='Aucun groupe configuré.'),
        _panel('Historique des actions', 'Dernières traces enregistrées dans le journal d’audit.',
               [_item(log.action, f'{log.object_type} #{log.object_id} · {log.timestamp:%d/%m %H:%M}',
                      _detail_url('core', 'auditlog', log.pk))
                for log in recent_logs], eyebrow='Audit', empty='Aucune action enregistrée.'),
    ]
    components = ['Fiches clients', 'Utilisateurs', 'Groupes', 'Journal d’audit']
    quick_actions = [
        {'label': 'Nouveau client', 'meta': 'Créer une fiche client', 'icon': 'guests',
         'url': _create_url('core', 'customer')},
        {'label': 'Voir l’équipe', 'meta': 'Utilisateurs et groupes', 'icon': 'team',
         'url': _list_url('core', 'user')},
    ]
    note = ('Les fiches clients sont partagées entre l’hôtel, le restaurant, le bar et la finance. '
            'Les actions sensibles alimentent le journal d’audit.')
    return highlights, panels, components, quick_actions, note


MODULE_OVERVIEWS = {
    'hotel': _hotel_overview,
    'restaurant': _restaurant_overview,
    'bar': _bar_overview,
    'inventory': _inventory_overview,
    'finance': _finance_overview,
    'core': _core_overview,
}


@login_required
def module_home(request, module):
    if module not in MODULES:
        raise Http404('Module introuvable')
    if not user_can_access_module(request.user, module):
        raise PermissionDenied('Vous n’avez pas accès à ce module.')
    roles = set(user_roles(request.user))
    is_hk_only = module == 'hotel' and 'Housekeeper' in roles and not (request.user.is_superuser or bool({'Owner','Receptionist'} & roles))
    if is_hk_only:
        return redirect('workspaces:housekeeping')
    cfg = MODULES[module]
    counts = {}
    for name in cfg['models']:
        try:
            counts[name] = apps.get_model(module, name).objects.count()
        except LookupError:
            counts[name] = 0
    cards = module_cards(module, counts)
    overview = MODULE_OVERVIEWS[module](timezone.localdate())
    highlights, panels, components, quick_actions, note = overview
    order_model = {'restaurant': Order, 'bar': BarOrder}.get(module)
    if order_model is not None and not _can_compose_order(request.user, order_model):
        order_card = next(card for card in cards if card['name'] == order_model.__name__)
        quick_actions = [action for action in quick_actions if action['url'] != order_card['create_url']]
        order_card['create_url'] = ''
    for card in cards:
        if card['name'] in {'AuditLog', 'Stay', 'Reservation'}:
            card['create_url'] = ''
    return render(request, 'module_home.html', {
        'module': module,
        'config': cfg,
        'cards': cards,
        'total': sum(counts.values()),
        'highlights': highlights,
        'panels': panels,
        'components': components,
        'quick_actions': quick_actions,
        'usage_note': note,
        'modules': MODULES,
    })


# ---------------------------------------------------------------------------
# Generic CRUD
# ---------------------------------------------------------------------------

ORDER_EDITORS = {Order: 'service', BarOrder: 'bar'}
POSTED_RECORDS = {Payment, StockMovement, Stock}
NO_CREATE_MODELS = {AuditLog, BookingRequest, Stay}
READ_ONLY_MODELS = {AuditLog, BookingRequest}
POSTING_TITLES = {Payment: 'Encaisser un paiement', StockMovement: 'Enregistrer un mouvement de stock'}
CHILD_LINE_MODELS = {
    ('restaurant', 'orderitem'): (OrderItem, 'order', 'order'),
    ('bar', 'barorderitem'): (BarOrderItem, 'barorder', 'order'),
    ('finance', 'invoiceitem'): (InvoiceItem, 'invoice', 'invoice'),
    ('inventory', 'purchaseorderitem'): (PurchaseOrderItem, 'purchaseorder', 'purchase_order'),
    ('inventory', 'recipeingredient'): (RecipeIngredient, 'recipe', 'recipe'),
}
LEGACY_ORDER_LINES = CHILD_LINE_MODELS


def _can_compose_order(user, model):
    roles = {'Waiter', 'Owner', 'Receptionist' if model is Order else 'Bartender'}
    return user.is_superuser or bool(roles.intersection(user_roles(user)))


def _order_line_redirect(module, entity, pk=None):
    entry = LEGACY_ORDER_LINES.get((module, entity.lower()))
    if entry:
        model, parent, attr = entry
        if pk is not None:
            line = get_object_or_404(model, pk=pk)
            return redirect('entity_detail', module, parent, getattr(line, f'{attr}_id'))
        return redirect('entity_list', module, parent)


def _is_posted_record(obj):
    return type(obj) in POSTED_RECORDS


def _track_record_fields(obj):
    for name in ('created_by', 'updated_by', 'responsible_user', 'received_by', 'opening_user'):
        if hasattr(obj, f'{name}_id'):
            yield name


def _save_generic_record(form, user, previous=None):
    obj = form.save(commit=False)
    if isinstance(obj, Payment):
        return register_payment(obj.invoice, obj.amount, obj.method, user, reference=obj.reference)
    if isinstance(obj, StockMovement):
        return move_stock(
            product=obj.product, location=obj.location, quantity=obj.quantity,
            movement_type=obj.movement_type, user=user, reference=obj.reference,
        )

    is_create = previous is None
    if hasattr(obj, 'created_by_id') and obj.created_by_id is None:
        obj.created_by = user
    if hasattr(obj, 'updated_by_id'):
        obj.updated_by = user
    for name in ('responsible_user', 'received_by', 'opening_user'):
        if hasattr(obj, f'{name}_id') and getattr(obj, f'{name}_id') is None:
            setattr(obj, name, user)
    obj.save()
    form.save_m2m()

    details = {'by': str(user)}
    if previous is not None:
        changed = []
        for field in form.changed_data:
            before = previous.get(field)
            after = getattr(obj, field, None)
            if hasattr(after, 'pk'):
                after = str(after)
            changed.append({'field': field, 'before': str(before) if before is not None else '', 'after': str(after) if after is not None else ''})
        details['changed'] = changed
    log_action(
        user,
        f"{'Création' if is_create else 'Modification'} {model_label(obj.__class__.__name__)}",
        obj,
        details=details,
    )
    return obj


@login_required
def entity_list(request, module, entity):
    _ensure_module_access(request, module, entity)
    legacy = _order_line_redirect(module, entity)
    if legacy:
        return legacy
    model = model_for(module, entity)
    fields = _visible_fields(model)
    qs = model.objects.all()
    if model is Customer:
        qs = qs.filter(is_walk_in=False)

    query = request.GET.get('q', '').strip()
    if query:
        conditions = Q()
        for field in model._meta.fields:
            if isinstance(field, (models.CharField, models.TextField, models.EmailField)):
                conditions |= Q(**{f'{field.name}__icontains': query})
        if conditions:
            qs = qs.filter(conditions)

    ordering = model._meta.ordering or ['-pk']
    qs = qs.order_by(*ordering)

    from django.core.paginator import Paginator
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    rows = [
        {'object': obj, 'cells': _record_cells(obj, fields), 'posted_record': _is_posted_record(obj)}
        for obj in page_obj
    ]

    order_print_kind = 'bar' if model is BarOrder else ('restaurant' if model is Order else '')
    return render(request, 'entity_list.html', {
        'module': module,
        'config': MODULES[module],
        'entity': entity,
        'model': model,
        'label': model_label(model.__name__),
        'fields': fields,
        'rows': rows,
        'page_obj': page_obj,
        'query': query,
        'total_count': paginator.count,
        'managed_order': model in ORDER_EDITORS,
        'posting_title': POSTING_TITLES.get(model),
        'stock_balance': model is Stock,
        'can_compose_order': model in ORDER_EDITORS and _can_compose_order(request.user, model),
        'can_create': model not in NO_CREATE_MODELS and model is not Reservation and (model not in ORDER_EDITORS or _can_compose_order(request.user, model)),
        'printable_document': 'invoice' if model is Invoice else ('receipt' if model is Payment else ''),
        'order_print_kind': order_print_kind,
        'modules': MODULES,
    })


@login_required
def entity_detail(request, module, entity, pk):
    _ensure_module_access(request, module, entity)
    legacy = _order_line_redirect(module, entity, pk)
    if legacy:
        return legacy
    model = model_for(module, entity)
    obj = get_object_or_404(model, pk=pk)
    if model in ORDER_EDITORS:
        bar = model is BarOrder
        invoice = find_bar_invoice(obj) if bar else find_order_invoice(obj)
        roles = set(user_roles(request.user))
        can_collect = request.user.is_superuser or bool({'Cashier', 'Owner', 'Receptionist', 'Waiter', 'Bartender', 'Chef', 'Comptable'} & roles)
        stay_reservation = None
        if not invoice and obj.status == 'SERVED' and obj.customer_id:
            stay_reservation = active_stay_reservation_for_customer(obj.customer)
        return render(request, 'workspaces/order_detail.html', {
            'order': obj, 'bar_order': bar, 'module': module, 'entity': entity,
            'order_lines': obj.items.select_related('drink' if bar else 'menu_item'),
            'invoice': invoice,
            'can_compose_order': _can_compose_order(request.user, model),
            'can_collect': can_collect,
            'stay_reservation': stay_reservation,
        })
    fields = _visible_fields(model)
    cells = _record_cells(obj, fields)
    can_collect_payment = False
    related_payments = None
    invoice_source = ''
    related_invoice = None
    detail_lines = None
    booking_actions = None
    source_booking_requests = None
    if isinstance(obj, Invoice):
        can_collect_payment = obj.is_payable and (
            request.user.is_superuser or bool({'Cashier', 'Owner', 'Receptionist', 'Waiter', 'Bartender', 'Chef', 'Comptable'} & set(user_roles(request.user)))
        )
        related_payments = obj.payments.select_related('method', 'received_by').order_by('-paid_at')
        invoice_source = (obj.notes or '').splitlines()[0] if obj.notes else ''
        detail_lines = {
            'title': 'Lignes de facture',
            'empty': 'Aucune ligne sur cette facture.',
            'headers': ['Désignation', 'Quantité', 'Prix unitaire', 'Taxe', 'Total', 'Source'],
            'rows': [{
                'cells': [(item.description, False), (item.quantity, False),
                          (item.unit_price, True), (item.tax, True),
                          (item.subtotal, True), (item.source_service or '—', False)],
            } for item in obj.items.all().order_by('pk')],
        }
    elif isinstance(obj, PurchaseOrder):
        detail_lines = {
            'title': 'Lignes du bon de commande',
            'empty': 'Aucune ligne sur ce bon de commande.',
            'headers': ['Produit', 'Quantité', 'Coût unitaire', 'Total'],
            'rows': [{
                'cells': [(item.product, False), (item.quantity, False),
                          (item.unit_cost, True), (item.quantity * item.unit_cost, True)],
            } for item in obj.items.select_related('product').order_by('pk')],
        }
    elif isinstance(obj, Recipe):
        detail_lines = {
            'title': 'Ingrédients',
            'empty': 'Aucun ingrédient renseigné.',
            'headers': ['Produit', 'Quantité', 'Unité'],
            'rows': [{
                'cells': [(item.product, False), (item.quantity, False), (item.unit, False)],
            } for item in obj.ingredients.select_related('product', 'unit').order_by('pk')],
        }
    elif isinstance(obj, BookingRequest):
        conflicting = Reservation.objects.filter(
            status__in=['CONFIRMED', 'CHECKED_IN'],
            check_in__lt=obj.check_out, check_out__gt=obj.check_in,
        ).values_list('room_id', flat=True)
        suggested_rooms = list(
            Room.objects.filter(room_type=obj.room_type, operational_status='AVAILABLE')
            .exclude(pk__in=conflicting).select_related('room_type').order_by('number')
        )
        matched_customer = None
        email = (obj.email or '').strip()
        phone = (obj.phone or '').strip()
        if email:
            matched_customer = Customer.objects.filter(is_walk_in=False, email__iexact=email).first()
        if not matched_customer and phone:
            matched_customer = Customer.objects.filter(is_walk_in=False, phone=phone).first()
        booking_actions = {
            'pending': obj.handled_at is None and not obj.reservation_id,
            'handled': obj.handled_at is not None and not obj.reservation_id,
            'converted': obj.reservation_id is not None,
            'suggested_rooms': suggested_rooms,
            'matched_customer': matched_customer,
        }
    elif isinstance(obj, Reservation):
        source_booking_requests = list(obj.source_booking_requests.select_related('room_type').order_by('-created_at'))
        reservation_actions = _reservation_actions(request, obj)
    if isinstance(obj, Payment):
        related_invoice = obj.invoice
    created_by = getattr(obj, 'created_by', None)
    updated_by = getattr(obj, 'updated_by', None)
    can_reset_password = isinstance(obj, get_user_model()) and (request.user.is_superuser or bool({'Owner'} & set(user_roles(request.user))))
    return render(request, 'entity_detail.html', {
        'module': module,
        'config': MODULES[module],
        'entity': entity,
        'model': model,
        'label': model_label(model.__name__),
        'object': obj,
        'posted_record': _is_posted_record(obj),
        'read_only_record': type(obj) in READ_ONLY_MODELS,
        'cells': cells,
        'icon': model_icon(model.__name__),
        'printable_document': 'invoice' if isinstance(obj, Invoice) else ('receipt' if isinstance(obj, Payment) else ''),
        'can_collect_payment': can_collect_payment,
        'related_payments': related_payments,
        'invoice_source': invoice_source,
        'related_invoice': related_invoice,
        'detail_lines': detail_lines,
        'booking_actions': booking_actions,
        'source_booking_requests': source_booking_requests,
        'reservation_actions': locals().get('reservation_actions'),
        'created_by': created_by,
        'updated_by': updated_by,
        'can_reset_password': can_reset_password,
        'modules': MODULES,
    })


def _reservation_actions(request, reservation):
    roles = set(user_roles(request.user))
    can_manage = request.user.is_superuser or bool({'Receptionist', 'Owner'} & roles)
    can_collect = request.user.is_superuser or bool({'Cashier', 'Owner', 'Receptionist', 'Waiter', 'Bartender', 'Chef', 'Comptable'} & roles)
    invoice = find_reservation_invoice(reservation)
    stay = Stay.objects.filter(reservation=reservation).order_by('-actual_check_in', '-pk').first()
    has_unpaid = bool(invoice and invoice.balance > 0)
    return {
        'can_manage': can_manage,
        'can_collect': can_collect,
        'invoice': invoice,
        'stay': stay,
        'editable': reservation.status in ('DRAFT', 'CONFIRMED'),
        'can_check_in': reservation.status == 'CONFIRMED',
        'can_prepare_checkout': reservation.status in ('CONFIRMED', 'CHECKED_IN'),
        'can_collect_payment': reservation.status in ('CONFIRMED', 'CHECKED_IN') and can_collect,
        'can_check_out': reservation.status == 'CHECKED_IN' and invoice is not None and not has_unpaid,
        'can_cancel': reservation.status in ('DRAFT', 'CONFIRMED'),
    }


@login_required
def entity_create(request, module, entity):
    _ensure_module_access(request, module, entity)
    legacy = _order_line_redirect(module, entity)
    if legacy:
        return legacy
    model = model_for(module, entity)
    if model in NO_CREATE_MODELS:
        messages.error(request, 'Cet enregistrement ne peut pas être créé manuellement.')
        return redirect('entity_list', module, entity)
    if model is Stock:
        return redirect('entity_create', module, 'stockmovement')
    if model is Reservation:
        if not (request.user.is_superuser or bool({'Receptionist', 'Owner'} & set(user_roles(request.user)))):
            raise PermissionDenied
        url = reverse('workspaces:reservation_create')
        if 'room' in request.GET:
            url += '?' + urlencode({'room': request.GET['room']})
        return redirect(url)
    if model in ORDER_EDITORS:
        if not _can_compose_order(request.user, model):
            raise PermissionDenied
        url = reverse(f'workspaces:{ORDER_EDITORS[model]}_order_create')
        if 'table' in request.GET:
            url += '?' + urlencode({'table': request.GET['table']})
        return redirect(url)
    Form = build_form(model)
    form = Form(request.POST, request.FILES) if request.method == 'POST' else Form()
    if model is Payment:
        form.fields['method'].queryset = form.fields['method'].queryset.filter(active=True)
        form.fields['invoice'].queryset = form.fields['invoice'].queryset.filter(
            status__in=Invoice.PAYABLE_STATUSES, total_amount__gt=F('paid_amount'),
        )
    if request.method == 'POST' and form.is_valid():
        try:
            obj = _save_generic_record(form, request.user)
        except ValueError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, f'{model_label(model.__name__)} créé avec succès.')
            return redirect('entity_detail', module=module, entity=entity, pk=obj.pk)
    return render(request, 'entity_form.html', {
        'module': module,
        'config': MODULES[module],
        'entity': entity,
        'label': model_label(model.__name__),
        'form': form,
        'object': None,
        'posting_title': POSTING_TITLES.get(model),
        'modules': MODULES,
    })


@login_required
def entity_edit(request, module, entity, pk):
    _ensure_module_access(request, module, entity)
    legacy = _order_line_redirect(module, entity, pk)
    if legacy:
        return legacy
    model = model_for(module, entity)
    if model in ORDER_EDITORS:
        if not _can_compose_order(request.user, model):
            raise PermissionDenied
        return redirect(f'workspaces:{ORDER_EDITORS[model]}_order_edit', pk=pk)
    obj = get_object_or_404(model, pk=pk)
    if _is_posted_record(obj) or type(obj) in READ_ONLY_MODELS:
        return redirect('entity_detail', module, entity, pk)
    Form = build_form(model)
    if request.method == 'POST':
        previous = {f.name: getattr(obj, f.name) for f in obj._meta.fields}
        form = Form(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            try:
                _save_generic_record(form, request.user, previous=previous)
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, f'{model_label(model.__name__)} mis à jour.')
                return redirect('entity_detail', module=module, entity=entity, pk=obj.pk)
    else:
        form = Form(instance=obj)
    return render(request, 'entity_form.html', {
        'module': module,
        'config': MODULES[module],
        'entity': entity,
        'label': model_label(model.__name__),
        'form': form,
        'object': obj,
        'modules': MODULES,
    })


@login_required
def entity_delete(request, module, entity, pk):
    _ensure_module_access(request, module, entity)
    legacy = _order_line_redirect(module, entity, pk)
    if legacy:
        return legacy
    model = model_for(module, entity)
    if model in ORDER_EDITORS:
        return redirect('entity_detail', module, entity, pk)
    obj = get_object_or_404(model, pk=pk)
    if _is_posted_record(obj) or type(obj) in READ_ONLY_MODELS:
        return redirect('entity_detail', module, entity, pk)
    if request.method == 'POST':
        try:
            log_action(request.user, f'Suppression {model_label(model.__name__)}', obj,
                       details={'by': str(request.user), 'object': str(obj)})
            obj.delete()
            messages.success(request, f'{model_label(model.__name__)} supprimé.')
            return redirect('entity_list', module=module, entity=entity)
        except Exception as exc:  # protected records
            messages.error(request, f'Impossible de supprimer cet élément : {exc}')
    return render(request, 'entity_confirm_delete.html', {
        'module': module,
        'config': MODULES[module],
        'entity': entity,
        'label': model_label(model.__name__),
        'object': obj,
        'modules': MODULES,
    })


@login_required
def entity_reset_password(request, module, entity, pk):
    _ensure_module_access(request, module, entity)
    model = model_for(module, entity)
    User = get_user_model()
    if model is not User:
        raise Http404
    if not (request.user.is_superuser or bool({'Owner'} & set(user_roles(request.user)))):
        raise PermissionDenied('Seul un administrateur ou gérant peut réinitialiser un mot de passe.')
    target = get_object_or_404(User, pk=pk)
    form = SetPasswordForm(target, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        log_action(request.user, 'Réinitialisation mot de passe', target,
                   details={'target': str(target), 'by': str(request.user)})
        messages.success(request, f'Mot de passe réinitialisé pour {target}.')
        return redirect('entity_detail', module=module, entity=entity, pk=target.pk)
    return render(request, 'entity_password_reset.html', {
        'module': module,
        'config': MODULES[module],
        'entity': entity,
        'label': model_label(model.__name__),
        'object': target,
        'form': form,
        'modules': MODULES,
    })


# ---------------------------------------------------------------------------
# Global search
# ---------------------------------------------------------------------------

@login_required
def search(request):
    query = request.GET.get('q', '').strip()
    groups = []
    if query:
        def add_group(title, icon, items):
            if items:
                groups.append({'title': title, 'icon': icon, 'items': items})

        allowed = set(accessible_modules(request.user))

        if 'core' in allowed:
            customer_q = (Q(first_name__icontains=query) | Q(last_name__icontains=query)
                          | Q(email__icontains=query) | Q(phone__icontains=query))
            add_group('Clients', 'guests', [
                {
                    'label': str(c),
                    'meta': f'{c.phone} · {c.email}' if c.email else c.phone,
                    'url': f'/module/core/customer/{c.pk}/',
                }
                for c in Customer.objects.filter(customer_q)[:8]
            ])

        if 'hotel' in allowed:
            reservation_q = (Q(customer__first_name__icontains=query)
                             | Q(customer__last_name__icontains=query)
                             | Q(room__number__icontains=query))
            add_group('Réservations', 'reservations', [
                {
                    'label': f'Réservation #{r.pk} · {r.customer}',
                    'meta': f'Chambre {r.room} · {r.check_in:%d/%m/%Y} → {r.check_out:%d/%m/%Y}',
                    'url': f'/module/hotel/reservation/{r.pk}/',
                }
                for r in Reservation.objects.select_related('customer', 'room').filter(reservation_q)[:8]
            ])

            room_q = Q(number__icontains=query) | Q(room_type__name__icontains=query)
            add_group('Chambres', 'bed', [
                {
                    'label': f'Chambre {room.number}',
                    'meta': f'{room.room_type.name} · étage {room.floor} · {room.get_operational_status_display()}',
                    'url': f'/module/hotel/room/{room.pk}/',
                }
                for room in Room.objects.select_related('room_type').filter(room_q)[:8]
            ])

        if 'finance' in allowed:
            invoice_q = (Q(number__icontains=query) | Q(customer__first_name__icontains=query)
                         | Q(customer__last_name__icontains=query))
            add_group('Factures', 'invoices', [
                {
                    'label': f'Facture {inv.number}',
                    'meta': f'{inv.customer} · {inv.get_status_display()}',
                    'url': f'/module/finance/invoice/{inv.pk}/',
                }
                for inv in Invoice.objects.select_related('customer').filter(invoice_q)[:8]
            ])

        if 'inventory' in allowed:
            product_q = Q(name__icontains=query) | Q(sku__icontains=query)
            add_group('Produits', 'products', [
                {
                    'label': p.name,
                    'meta': f'Réf. {p.sku}',
                    'url': f'/module/inventory/product/{p.pk}/',
                }
                for p in Product.objects.filter(product_q)[:8]
            ])

        menu_items = []
        if 'restaurant' in allowed:
            menu_items += [
                {
                    'label': item.name,
                    'meta': f'Restaurant · {item.category or "Menu"} · {item.selling_price} F',
                    'url': f'/module/restaurant/menuitem/{item.pk}/',
                }
                for item in MenuItem.objects.filter(name__icontains=query)[:6]
            ]
        if 'bar' in allowed:
            menu_items += [
                {
                    'label': drink.name,
                    'meta': f'Bar · {drink.category.name} · {drink.selling_price} F',
                    'url': f'/module/bar/drink/{drink.pk}/',
                }
                for drink in Drink.objects.select_related('category').filter(name__icontains=query)[:6]
            ]
        add_group('Menu & bar', 'menu', menu_items)

    return render(request, 'search_results.html', {
        'query': query,
        'groups': groups,
        'result_count': sum(len(group['items']) for group in groups),
        'nav_sections': build_nav(request.user),
        'modules': MODULES,
    })
