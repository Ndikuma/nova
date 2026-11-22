"""Rapports CSV/PDF et documents imprimables réutilisables."""

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from xml.sax.saxutils import escape

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone

from apps.bar.models import BarOrder, BarOrderItem, Drink
from apps.core.company import CompanyProfile
from apps.core.models import AuditLog, Customer
from apps.finance.models import Expense, Invoice, InvoiceItem, Payment, Refund
from apps.hotel.models import HousekeepingTask, Reservation, Room
from apps.inventory.models import Product, Stock, StockMovement, Supplier
from apps.obr_ebms.models import (
    EBMSInvoice, EBMSInvoiceItem, EBMSProductMapping, EBMSStockMovement,
    OBRSyncLog, SyncStatus,
)
from apps.restaurant.models import Order, OrderItem
from .models import GeneratedReport

ZERO = Decimal('0')


@dataclass(frozen=True)
class DocumentBrand:
    """Adaptateur d'impression autour du profil d'établissement configuré."""

    profile: CompanyProfile

    @classmethod
    def load(cls):
        return cls(CompanyProfile.load())

    @property
    def name(self):
        return self.profile.name

    @property
    def short_name(self):
        return self.profile.short_name

    @property
    def initials(self):
        return self.profile.initials

    @property
    def tagline(self):
        return self.profile.tagline

    @property
    def legal_name(self):
        return self.profile.legal_name

    @property
    def logo_url(self):
        return self.profile.logo_url

    @property
    def address(self):
        return self.profile.address

    @property
    def phone(self):
        return self.profile.phone

    @property
    def phone_secondary(self):
        return self.profile.phone_secondary

    @property
    def email(self):
        return self.profile.email

    @property
    def support_email(self):
        return self.profile.support_email

    @property
    def website(self):
        return self.profile.website

    @property
    def tax_id(self):
        return self.profile.tax_id

    @property
    def trade_number(self):
        return self.profile.trade_number

    @property
    def registration_number(self):
        return self.profile.registration_number

    @property
    def currency(self):
        return self.profile.currency

    @property
    def currency_symbol(self):
        return self.profile.currency_symbol

    @property
    def footer(self):
        return self.profile.document_footer

    @property
    def invoice_footer(self):
        return self.profile.invoice_footer

    @property
    def receipt_footer(self):
        return self.profile.receipt_footer

    @property
    def contact_line(self):
        return self.profile.contact_line

    @property
    def legal_line(self):
        return self.profile.legal_line

    @property
    def bank_line(self):
        return self.profile.bank_line

    @property
    def primary_color(self):
        return self.profile.theme_light['--brand']

    @property
    def on_brand_color(self):
        return self.profile.theme_light['--on-brand']

    @property
    def ink_color(self):
        return self.profile.print_colors['ink']

    @property
    def muted_color(self):
        return self.profile.print_colors['muted']

    @property
    def border_color(self):
        return self.profile.print_colors['border']

    @property
    def soft_color(self):
        return self.profile.print_colors['soft']

    @property
    def print_bg_color(self):
        return self.profile.print_colors['bg']

    @property
    def paper_color(self):
        return self.profile.print_colors['paper']

    @property
    def page_color(self):
        return self.profile.print_colors['page']

    @property
    def cell_color(self):
        return self.profile.print_colors['cell']


MANAGEMENT_ROLES = {'Superadmin', 'Owner'}
ALL_STAFF = {'Superadmin', 'Owner', 'Cashier', 'Chef', 'Receptionist', 'Waiter', 'Bartender'}

REPORT_CATALOG = {
    'invoice-register': {
        'name': 'Registre des factures', 'category': 'Finance',
        'description': 'Factures émises, montants payés et soldes ouverts.', 'roles': MANAGEMENT_ROLES | {'Cashier'},
    },
    'payments': {
        'name': 'Journal des paiements', 'category': 'Finance',
        'description': 'Encaissements par date, moyen de paiement et caissier.', 'roles': MANAGEMENT_ROLES | {'Cashier'},
    },
    'expenses': {
        'name': 'Journal des dépenses', 'category': 'Finance',
        'description': 'Dépenses par catégorie, responsable et référence.', 'roles': MANAGEMENT_ROLES,
    },
    'reservations': {
        'name': 'Registre des réservations', 'category': 'Hôtel',
        'description': 'Arrivées, départs, chambres et statuts des séjours.', 'roles': MANAGEMENT_ROLES | {'Receptionist'},
    },
    'housekeeping': {
        'name': 'Tâches de ménage', 'category': 'Hôtel',
        'description': 'Tâches planifiées, assignations et avancement.', 'roles': MANAGEMENT_ROLES | {'Receptionist'},
    },
    'restaurant-orders': {
        'name': 'Commandes restaurant', 'category': 'Restaurant',
        'description': 'Commandes, tables, montants et statuts de service.', 'roles': MANAGEMENT_ROLES | {'Cashier', 'Waiter', 'Chef'},
    },
    'restaurant-sales': {
        'name': 'Ventes restaurant par plat', 'category': 'Restaurant',
        'description': 'Quantités et chiffre d’affaires par plat.', 'roles': MANAGEMENT_ROLES,
    },
    'bar-orders': {
        'name': 'Commandes bar', 'category': 'Bar',
        'description': 'Commandes, tables, montants et statuts de service.', 'roles': MANAGEMENT_ROLES | {'Cashier', 'Bartender'},
    },
    'bar-sales': {
        'name': 'Ventes bar par boisson', 'category': 'Bar',
        'description': 'Quantités et chiffre d’affaires par boisson.', 'roles': MANAGEMENT_ROLES,
    },
    'stock-levels': {
        'name': 'État des stocks', 'category': 'Inventaire',
        'description': 'Quantités par produit et emplacement, avec alertes de seuil.', 'roles': MANAGEMENT_ROLES | {'Chef', 'Bartender'},
    },
    'stock-movements': {
        'name': 'Mouvements de stock', 'category': 'Inventaire',
        'description': 'Entrées, sorties, ajustements et responsables.', 'roles': MANAGEMENT_ROLES | {'Chef'},
    },
    'room-occupancy': {
        'name': "Rapport d'occupation des chambres", 'category': 'Occupation',
        'description': 'Chambres occupées/disponibles/maintenance et taux d’occupation journalier.', 'roles': MANAGEMENT_ROLES | {'Receptionist'},
    },
    'occupancy-rates': {
        'name': "Taux d'occupation mensuel et annuel", 'category': 'Occupation',
        'description': 'Taux d’occupation agrégés par mois et par année sur la période.', 'roles': MANAGEMENT_ROLES | {'Receptionist'},
    },
    'financial-summary': {
        'name': 'Rapport financier', 'category': 'Finance',
        'description': 'Recettes chambres/restaurant/bar, dépenses, résultat et solde de caisse.', 'roles': MANAGEMENT_ROLES | {'Cashier'},
    },
    'customer-report': {
        'name': 'Rapport des clients', 'category': 'Clients',
        'description': 'Clients, nombre de séjours, fidélité, paiements et dettes.', 'roles': MANAGEMENT_ROLES | {'Receptionist', 'Cashier'},
    },
    'restaurant-stock-report': {
        'name': 'Rapport restaurant et stock', 'category': 'Restaurant & Stock',
        'description': 'Ventes restaurant/bar, consommations, mouvements de stock et inventaire.', 'roles': MANAGEMENT_ROLES | {'Chef'},
    },
    'suppliers': {
        'name': 'Fournisseurs', 'category': 'Inventaire',
        'description': 'Contacts, coordonnées et informations fiscales.', 'roles': MANAGEMENT_ROLES,
    },
    'audit-log': {
        'name': 'Journal d’audit', 'category': 'Système',
        'description': 'Traçabilité des actions sensibles et des utilisateurs.', 'roles': MANAGEMENT_ROLES,
    },
    'ebms-invoices': {
        'name': 'Factures OBR eBMS', 'category': 'OBR eBMS',
        'description': 'Factures fiscales, statuts de synchronisation et numéros OBR.', 'roles': MANAGEMENT_ROLES | {'Cashier'},
    },
    'ebms-stock': {
        'name': 'Mouvements OBR eBMS', 'category': 'OBR eBMS',
        'description': 'Mouvements de stock transmis ou en attente.', 'roles': MANAGEMENT_ROLES,
    },
    'ebms-mapping': {
        'name': 'Classification OBR eBMS', 'category': 'OBR eBMS',
        'description': 'Codes article, unités et taux de taxe par produit.', 'roles': MANAGEMENT_ROLES,
    },
    'ebms-sync-log': {
        'name': 'Journal OBR eBMS', 'category': 'OBR eBMS',
        'description': 'Appels API, durée, succès et messages d’erreur.', 'roles': MANAGEMENT_ROLES,
    },
    'ebms-tax-summary': {
        'name': 'Synthèse fiscale OBR', 'category': 'OBR eBMS',
        'description': 'TVA et autres taxes des factures enregistrées auprès d’OBR.', 'roles': MANAGEMENT_ROLES,
    },
}

MAX_PERIOD_DAYS = 366
MAX_PDF_ROWS = 2500
MAX_EXPORT_ROWS = 50000


def _period(params):
    today = timezone.localdate()
    date_from = params.get('date_from') or ''
    date_to = params.get('date_to') or ''
    try:
        start = date.fromisoformat(date_from) if date_from else today.replace(day=1)
        end = date.fromisoformat(date_to) if date_to else today
    except (TypeError, ValueError) as exc:
        raise ValidationError('La période sélectionnée est invalide.') from exc
    if end < start:
        raise ValidationError('La date de fin doit être postérieure à la date de début.')
    if (end - start).days > MAX_PERIOD_DAYS:
        raise ValidationError(f'La période ne peut pas dépasser {MAX_PERIOD_DAYS} jours.')
    return start, end


def _related(value, fallback='—'):
    return str(value) if value else fallback


def _money(value):
    return value if value is not None else ZERO


def report_data(code, params):
    start, end = _period(params)
    if code not in REPORT_CATALOG:
        raise ValidationError('Rapport inconnu.')

    if code == 'invoice-register':
        qs = Invoice.objects.filter(issued_at__date__range=(start, end)).select_related('customer')
        headers = ['Facture', 'Client', 'Émise le', 'Statut', 'Total', 'Payé', 'Solde', 'Origine']
        rows = [[
            inv.number, str(inv.customer), inv.issued_at.strftime('%d/%m/%Y %H:%M'),
            inv.get_status_display(), inv.total_amount, inv.paid_amount, inv.balance,
            (inv.notes or '').splitlines()[0] if inv.notes else '—',
        ] for inv in qs.order_by('-issued_at')]

    elif code == 'payments':
        qs = Payment.objects.filter(paid_at__date__range=(start, end)).select_related(
            'invoice', 'invoice__customer', 'method', 'received_by',
        )
        headers = ['Date', 'Facture', 'Client', 'Moyen', 'Montant', 'Référence', 'Caissier']
        rows = [[
            timezone.localtime(p.paid_at).strftime('%d/%m/%Y %H:%M'), p.invoice.number,
            str(p.invoice.customer), p.method.name, p.amount, p.reference or '—',
            str(p.received_by),
        ] for p in qs.order_by('-paid_at')]

    elif code == 'expenses':
        qs = Expense.objects.filter(date__range=(start, end)).select_related(
            'category', 'payment_method', 'responsible_user',
        )
        headers = ['Date', 'Catégorie', 'Description', 'Montant', 'Moyen', 'Responsable', 'Référence']
        rows = [[
            e.date.strftime('%d/%m/%Y'), e.category.name, e.description, e.amount,
            e.payment_method.name, str(e.responsible_user), e.reference or '—',
        ] for e in qs.order_by('-date')]

    elif code == 'reservations':
        qs = Reservation.objects.filter(
            check_in__range=(start, end),
        ).select_related('customer', 'room', 'room__room_type')
        headers = ['Client', 'Téléphone', 'Chambre', 'Type', 'Arrivée', 'Départ',
                   'Adultes', 'Enfants', 'Total estimé', 'Statut']
        rows = [[
            str(r.customer), r.customer.phone, r.room.number, r.room.room_type.name,
            r.check_in.strftime('%d/%m/%Y'), r.check_out.strftime('%d/%m/%Y'),
            r.adults, r.children, r.estimated_total, r.get_status_display(),
        ] for r in qs.order_by('-check_in')]

    elif code == 'housekeeping':
        qs = HousekeepingTask.objects.filter(
            scheduled_date__range=(start, end),
        ).select_related('room', 'assigned_to')
        headers = ['Date', 'Chambre', 'Type', 'Assigné à', 'Statut', 'Terminée le', 'Notes']
        rows = [[
            t.scheduled_date.strftime('%d/%m/%Y'), t.room.number, t.get_task_type_display(),
            str(t.assigned_to) if t.assigned_to else '—', t.get_status_display(),
            t.completion_date.strftime('%d/%m/%Y') if t.completion_date else '—',
            t.notes or '—',
        ] for t in qs.order_by('-scheduled_date')]

    elif code == 'restaurant-orders':
        qs = Order.objects.filter(created_at__date__range=(start, end)).select_related(
            'customer', 'table',
        )
        headers = ['Commande', 'Créée le', 'Client', 'Table', 'Source', 'Total', 'Statut']
        rows = [[
            f'#{o.pk}', timezone.localtime(o.created_at).strftime('%d/%m/%Y %H:%M'),
            str(o.customer) if o.customer else 'Sans client',
            str(o.table) if o.table else '—', o.get_source_display(),
            o.total_amount, o.get_status_display(),
        ] for o in qs.order_by('-created_at')]

    elif code == 'restaurant-sales':
        qs = OrderItem.objects.filter(
            order__created_at__date__range=(start, end),
            order__status__in=['SERVED', 'PAID'],
        ).annotate(
            line_total=ExpressionWrapper(
                F('quantity') * F('unit_price'), output_field=DecimalField(max_digits=20, decimal_places=4),
            ),
        ).values('menu_item__name', 'menu_item__category').annotate(
            quantity=Sum('quantity'), revenue=Sum('line_total'),
        ).order_by('-revenue')
        headers = ['Plat', 'Catégorie', 'Quantité', 'Chiffre d’affaires']
        rows = [[x['menu_item__name'], x['menu_item__category'] or '—',
                 x['quantity'], x['revenue'] or 0] for x in qs]

    elif code == 'bar-orders':
        qs = BarOrder.objects.filter(created_at__date__range=(start, end)).select_related(
            'customer', 'table',
        )
        headers = ['Commande', 'Créée le', 'Client', 'Table', 'Total', 'Statut']
        rows = [[
            f'#{o.pk}', timezone.localtime(o.created_at).strftime('%d/%m/%Y %H:%M'),
            str(o.customer) if o.customer else 'Sans client',
            str(o.table) if o.table else 'Comptoir', o.total_amount, o.get_status_display(),
        ] for o in qs.order_by('-created_at')]

    elif code == 'bar-sales':
        qs = BarOrderItem.objects.filter(
            order__created_at__date__range=(start, end),
            order__status__in=['SERVED', 'PAID'],
        ).annotate(
            line_total=ExpressionWrapper(
                F('quantity') * F('unit_price'), output_field=DecimalField(max_digits=20, decimal_places=4),
            ),
        ).values('drink__name', 'drink__category__name').annotate(
            quantity=Sum('quantity'), revenue=Sum('line_total'),
        ).order_by('-revenue')
        headers = ['Boisson', 'Catégorie', 'Quantité', 'Chiffre d’affaires']
        rows = [[x['drink__name'], x['drink__category__name'] or '—',
                 x['quantity'], x['revenue'] or 0] for x in qs]

    elif code == 'stock-levels':
        qs = Stock.objects.select_related('product', 'location').order_by(
            'product__name', 'location__name',
        )
        headers = ['Produit', 'Référence', 'Emplacement', 'Quantité', 'Seuil', 'État', 'Alerte']
        rows = [[
            s.product.name, s.product.sku, s.location.name, s.quantity,
            s.product.minimum_stock,
            'Actif' if s.product.active else 'Inactif',
            'Oui' if s.quantity <= 0 or s.quantity < s.product.minimum_stock else 'Non',
        ] for s in qs]

    elif code == 'stock-movements':
        qs = StockMovement.objects.filter(date__date__range=(start, end)).select_related(
            'product', 'location', 'responsible_user',
        )
        headers = ['Date', 'Produit', 'Emplacement', 'Type', 'Quantité', 'Référence', 'Responsable']
        rows = [[
            timezone.localtime(m.date).strftime('%d/%m/%Y %H:%M'), m.product.name,
            m.location.name, m.get_movement_type_display(), m.quantity,
            m.reference or '—', str(m.responsible_user),
        ] for m in qs.order_by('-date')]

    elif code == 'room-occupancy':
        rooms = list(Room.objects.select_related('room_type').order_by('number'))
        total_rooms = len(rooms)
        headers = ['Date', 'Chambres occupées', 'Chambres disponibles', 'Maintenance / HS', 'Total chambres', "Taux d'occupation (%)"]
        rows = []
        for i in range((end - start).days + 1):
            day = start + timedelta(days=i)
            occupied_room_ids = set(
                Reservation.objects.filter(
                    status__in=['CONFIRMED', 'CHECKED_IN'], check_in__lte=day, check_out__gt=day,
                ).values_list('room_id', flat=True)
            )
            maintenance = sum(1 for r in rooms if r.operational_status in ('MAINTENANCE', 'OUT_OF_SERVICE'))
            occupied = sum(1 for r in rooms if r.pk in occupied_room_ids)
            available = sum(1 for r in rooms if r.pk not in occupied_room_ids and r.operational_status == 'AVAILABLE')
            rate = (occupied / total_rooms * 100) if total_rooms else 0
            rows.append([day.strftime('%d/%m/%Y'), occupied, available, maintenance, total_rooms, f'{rate:.1f}'])

    elif code == 'occupancy-rates':
        rooms = list(Room.objects.select_related('room_type').order_by('number'))
        total_rooms = len(rooms)
        headers = ['Période', 'Type', 'Nuits occupées', 'Nuits disponibles', "Taux d'occupation (%)"]
        rows = []
        # monthly
        cur = start.replace(day=1)
        last_month = end.replace(day=1)
        while cur <= last_month:
            nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
            m_start = max(cur, start)
            m_end = min(nxt - timedelta(days=1), end)
            days = (m_end - m_start).days + 1
            occ = 0
            for i in range(days):
                day = m_start + timedelta(days=i)
                occ += Reservation.objects.filter(
                    status__in=['CONFIRMED', 'CHECKED_IN'], check_in__lte=day, check_out__gt=day,
                ).values('room_id').distinct().count()
            avail = total_rooms * days
            rate = (occ / avail * 100) if avail else 0
            rows.append([cur.strftime('%m/%Y'), 'Mensuel', occ, avail, f'{rate:.1f}'])
            cur = nxt
        # yearly
        for year in range(start.year, end.year + 1):
            y_start = max(date(year, 1, 1), start)
            y_end = min(date(year, 12, 31), end)
            days = (y_end - y_start).days + 1
            occ = 0
            for i in range(days):
                day = y_start + timedelta(days=i)
                occ += Reservation.objects.filter(
                    status__in=['CONFIRMED', 'CHECKED_IN'], check_in__lte=day, check_out__gt=day,
                ).values('room_id').distinct().count()
            avail = total_rooms * days
            rate = (occ / avail * 100) if avail else 0
            rows.append([str(year), 'Annuel', occ, avail, f'{rate:.1f}'])

    elif code == 'financial-summary':
        room_rev = Reservation.objects.filter(created_at__date__range=(start, end)).exclude(status='CANCELLED').aggregate(t=Sum('estimated_total'))['t'] or ZERO
        rest_rev = Order.objects.filter(created_at__date__range=(start, end)).exclude(status='CANCELLED').aggregate(t=Sum('total_amount'))['t'] or ZERO
        bar_rev = BarOrder.objects.filter(created_at__date__range=(start, end)).exclude(status='CANCELLED').aggregate(t=Sum('total_amount'))['t'] or ZERO
        expenses = Expense.objects.filter(date__range=(start, end)).aggregate(t=Sum('amount'))['t'] or ZERO
        cash_balance = Payment.objects.filter(paid_at__date__range=(start, end), method__is_cash=True).aggregate(t=Sum('amount'))['t'] or ZERO
        total_income = room_rev + rest_rev + bar_rev
        profit = total_income - expenses
        headers = ['Indicateur', 'Montant (F)']
        rows = [
            ['Recettes des chambres', room_rev],
            ['Recettes du restaurant', rest_rev],
            ['Recettes du bar', bar_rev],
            ['Total recettes', total_income],
            ['Dépenses', expenses],
            ['Bénéfice / perte', profit],
            ['Solde de caisse (paiements espèces période)', cash_balance],
        ]

    elif code == 'customer-report':
        customers = Customer.objects.filter(is_walk_in=False).order_by('last_name', 'first_name')
        headers = ['Client', 'Téléphone', 'Email', 'Séjours', 'Fidèle', 'Paiements (F)', 'Dettes / solde dû (F)']
        rows = []
        for c in customers:
            stays = Reservation.objects.filter(customer=c, status__in=['CONFIRMED','CHECKED_IN','CHECKED_OUT']).count()
            payments = Payment.objects.filter(invoice__customer=c, paid_at__date__range=(start, end)).aggregate(t=Sum('amount'))['t'] or ZERO
            debt = Invoice.objects.filter(customer=c, status__in=['ISSUED','PARTIAL']).aggregate(t=Sum(F('total_amount') - F('paid_amount')))['t'] or ZERO
            rows.append([str(c), c.phone or '—', c.email or '—', stays, 'Oui' if stays >= 3 else 'Non', payments, debt])

    elif code == 'restaurant-stock-report':
        rest_sales = OrderItem.objects.filter(order__created_at__date__range=(start, end), order__status__in=['SERVED','PAID']).annotate(line=ExpressionWrapper(F('quantity')*F('unit_price'), output_field=DecimalField(max_digits=20,decimal_places=4))).values('menu_item__name').annotate(qty=Sum('quantity'), rev=Sum('line')).order_by('-rev')
        bar_sales = BarOrderItem.objects.filter(order__created_at__date__range=(start, end), order__status__in=['SERVED','PAID']).annotate(line=ExpressionWrapper(F('quantity')*F('unit_price'), output_field=DecimalField(max_digits=20,decimal_places=4))).values('drink__name').annotate(qty=Sum('quantity'), rev=Sum('line')).order_by('-rev')
        movements = StockMovement.objects.filter(date__date__range=(start, end)).select_related('product','location','responsible_user').order_by('-date')
        stocks = Stock.objects.select_related('product','location').order_by('product__name')
        rows = []
        headers = ['Section', 'Détail', 'Quantité', 'Montant / Valeur', 'Info']
        rows.append(['VENTES RESTAURANT', f'Total lignes: {rest_sales.count()}', '', '', ''])
        for r in rest_sales[:100]:
            rows.append(['Restaurant', r['menu_item__name'], r['qty'], r['rev'] or ZERO, 'Vente plat'])
        rows.append(['VENTES BAR', f'Total lignes: {bar_sales.count()}', '', '', ''])
        for r in bar_sales[:100]:
            rows.append(['Bar', r['drink__name'], r['qty'], r['rev'] or ZERO, 'Vente boisson'])
        rows.append(['MOUVEMENTS STOCK', f'Total: {movements.count()}', '', '', ''])
        for m in movements[:150]:
            rows.append(['Stock', m.product.name, m.quantity, m.get_movement_type_display(), f'{m.location.name} · {timezone.localtime(m.date).strftime("%d/%m/%Y")}'])
        rows.append(['INVENTAIRE', f'Total: {stocks.count()}', '', '', ''])
        for s in stocks[:150]:
            alert = 'Alerte seuil' if s.quantity <= 0 or s.quantity < s.product.minimum_stock else 'OK'
            rows.append(['Inventaire', s.product.name, s.quantity, s.location.name, alert])

    elif code == 'suppliers':
        qs = Supplier.objects.all()
        headers = ['Fournisseur', 'Contact', 'E-mail', 'Téléphone', 'Adresse', 'Informations fiscales']
        rows = [[
            s.name, s.contact or '—', s.email or '—', s.phone or '—',
            s.address or '—', s.tax_information or '—',
        ] for s in qs.order_by('name')]

    elif code == 'audit-log':
        qs = AuditLog.objects.filter(timestamp__date__range=(start, end)).select_related('user')
        headers = ['Horodatage', 'Utilisateur', 'Action', 'Objet', 'Identifiant', 'Détails']
        rows = [[
            timezone.localtime(log.timestamp).strftime('%d/%m/%Y %H:%M:%S'),
            str(log.user) if log.user else 'Système', log.action, log.object_type,
            log.object_id, str(log.details or ''),
        ] for log in qs.order_by('-timestamp')]

    elif code == 'ebms-invoices':
        qs = EBMSInvoice.objects.filter(
            invoice_date__date__range=(start, end),
        ).select_related('invoice').prefetch_related('items')
        headers = ['Facture', 'Identifiant', 'Date', 'Type', 'Client', 'Total', 'Statut',
                   'N° OBR', 'Tentatives', 'Erreur']
        rows = [[
            r.invoice_number, r.invoice_identifier,
            timezone.localtime(r.invoice_date).strftime('%d/%m/%Y %H:%M'),
            r.get_invoice_type_display(), r.customer_name, r.total_amount,
            r.get_status_display(), r.obr_registered_number or '—', r.attempt_count,
            r.error_message or '—',
        ] for r in qs.order_by('-invoice_date')]

    elif code == 'ebms-stock':
        qs = EBMSStockMovement.objects.filter(
            movement_date__date__range=(start, end),
        ).select_related('stock_movement', 'stock_movement__product', 'stock_movement__location')
        headers = ['Date', 'Produit', 'Emplacement', 'Type', 'Quantité', 'Statut',
                   'Référence', 'Tentatives', 'Erreur']
        rows = [[
            timezone.localtime(r.movement_date).strftime('%d/%m/%Y %H:%M'),
            r.stock_movement.product.name, r.stock_movement.location.name,
            r.get_movement_type_display(), r.stock_movement.quantity,
            r.get_status_display(), r.invoice_reference or '—', r.attempt_count,
            r.error_message or '—',
        ] for r in qs.order_by('-movement_date')]

    elif code == 'ebms-mapping':
        qs = EBMSProductMapping.objects.select_related('product', 'verified_by')
        headers = ['Produit', 'Référence', 'Éligibilité', 'Code article', 'Désignation',
                   'Unité', 'TVA %', 'Prêt', 'Vérifié par']
        rows = [[
            m.product.name, m.product.sku, m.get_eligibility_display(),
            m.item_code or '—', m.item_designation or '—', m.measurement_unit or '—',
            m.vat_rate, 'Oui' if m.ready else 'Non',
            str(m.verified_by) if m.verified_by else '—',
        ] for m in qs.order_by('product__name')]

    elif code == 'ebms-sync-log':
        qs = OBRSyncLog.objects.filter(created_at__date__range=(start, end)).select_related('performed_by')
        headers = ['Date', 'Action', 'Référence', 'Succès', 'Durée (ms)', 'Utilisateur', 'Erreur']
        rows = [[
            timezone.localtime(log.created_at).strftime('%d/%m/%Y %H:%M:%S'),
            log.get_action_display(), log.reference or '—',
            'Oui' if log.success else 'Non', log.duration_ms,
            str(log.performed_by) if log.performed_by else 'Système',
            log.error_message or '—',
        ] for log in qs.order_by('-created_at')]

    elif code == 'ebms-tax-summary':
        items = EBMSInvoiceItem.objects.filter(
            invoice__invoice_date__date__range=(start, end),
            invoice__status=SyncStatus.SENT,
        )
        grouped = items.values('invoice__invoice_type').annotate(
            invoice_count=Count('invoice', distinct=True), item_count=Count('id'),
            net=Sum('price_without_vat'), vat=Sum('vat'), consumption=Sum('consumption_tax'),
            tourism=Sum('tourism_levy'), special=Sum('special_tax'), other=Sum('other_tax'),
            total=Sum('total_amount'),
        ).order_by('invoice__invoice_type')
        type_labels = dict(EBMSInvoice.Type.choices)
        headers = ['Type', 'Factures', 'Lignes', 'Net HT', 'TVA', 'Taxe consommation',
                   'Levy tourisme', 'Taxe spéciale', 'Autre taxe', 'Total']
        rows = [[
            type_labels.get(g['invoice__invoice_type'], g['invoice__invoice_type']),
            g['invoice_count'], g['item_count'], g['net'] or 0, g['vat'] or 0,
            g['consumption'] or 0, g['tourism'] or 0, g['special'] or 0,
            g['other'] or 0, g['total'] or 0,
        ] for g in grouped]
        totals = items.aggregate(
            invoices=Count('invoice', distinct=True), items=Count('id'),
            net=Sum('price_without_vat'), vat=Sum('vat'), consumption=Sum('consumption_tax'),
            tourism=Sum('tourism_levy'), special=Sum('special_tax'), other=Sum('other_tax'),
            total=Sum('total_amount'),
        )
        if rows:
            rows.append([
                'TOTAL', totals['invoices'] or 0, totals['items'] or 0,
                totals['net'] or 0, totals['vat'] or 0, totals['consumption'] or 0,
                totals['tourism'] or 0, totals['special'] or 0, totals['other'] or 0,
                totals['total'] or 0,
            ])
    else:
        raise ValidationError('Rapport inconnu.')

    return REPORT_CATALOG[code]['name'], headers, rows, start, end


def user_can_run(user, code):
    if code not in REPORT_CATALOG or not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    groups = set(user.groups.values_list('name', flat=True))
    return bool(groups.intersection(REPORT_CATALOG[code]['roles']))


def _text(value):
    if value is None:
        return ''
    if isinstance(value, Decimal):
        return f'{value:.2f}'
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _csv_value(value):
    value = _text(value)
    if value.startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def render_csv(headers, rows, brand, title, subtitle=''):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([brand.name])
    writer.writerow([brand.legal_name])
    writer.writerow([brand.address])
    writer.writerow([brand.contact_line])
    if brand.tax_id:
        writer.writerow([f'NIF/TIN : {brand.tax_id}'])
    writer.writerow([title])
    writer.writerow([subtitle])
    writer.writerow([])
    writer.writerow([_csv_value(value) for value in headers])
    writer.writerows([
        [_csv_value(value) for value in row] for row in rows
    ])
    return b'\xef\xbb\xbf' + output.getvalue().encode('utf-8')


def _reportlab():
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )
    except ImportError as exc:  # pragma: no cover
        raise ValidationError(
            'L’export PDF est indisponible. Installez la dépendance reportlab.'
        ) from exc
    return {
        'colors': colors, 'TA_CENTER': TA_CENTER, 'TA_LEFT': TA_LEFT, 'TA_RIGHT': TA_RIGHT,
        'A4': A4, 'landscape': landscape, 'ParagraphStyle': ParagraphStyle,
        'getSampleStyleSheet': getSampleStyleSheet, 'mm': mm, 'HRFlowable': HRFlowable,
        'Paragraph': Paragraph, 'SimpleDocTemplate': SimpleDocTemplate,
        'Spacer': Spacer, 'Table': Table, 'TableStyle': TableStyle,
    }


def _table_data(Paragraph, style, headers, rows):
    head = [Paragraph(f'<b>{escape(_text(value))}</b>', style) for value in headers]
    body = [[Paragraph(escape(_text(value)), style) for value in row] for row in rows]
    return [head] + body


def _column_widths(headers, rows, available):
    samples = list(zip(*([headers] + rows[:100])))
    weights = []
    for column in samples:
        longest = max((len(_text(value)) for value in column), default=7)
        weights.append(max(6, min(26, longest)))
    total = sum(weights) or 1
    return [available * weight / total for weight in weights]


def render_report_pdf(title, headers, rows, brand, subtitle='', generated_by='', landscape_mode=None):
    rl = _reportlab()
    colors = rl['colors']
    mm = rl['mm']
    Paragraph = rl['Paragraph']
    ParagraphStyle = rl['ParagraphStyle']
    SimpleDocTemplate = rl['SimpleDocTemplate']
    Table = rl['Table']
    TableStyle = rl['TableStyle']
    Spacer = rl['Spacer']
    HRFlowable = rl['HRFlowable']

    if landscape_mode is None:
        landscape_mode = len(headers) > 5
    pagesize = rl['landscape'](rl['A4']) if landscape_mode else rl['A4']
    margin = 14 * mm if landscape_mode else 16 * mm
    output = BytesIO()
    accent = colors.HexColor(brand.primary_color)
    doc = SimpleDocTemplate(
        output, pagesize=pagesize, leftMargin=margin, rightMargin=margin,
        topMargin=34 * mm, bottomMargin=20 * mm, title=title, author=brand.name,
    )

    styles = rl['getSampleStyleSheet']()
    brand_style = ParagraphStyle(
        'brand', parent=styles['Heading1'], fontName='Helvetica-Bold',
        fontSize=17, leading=20, textColor=colors.HexColor(brand.ink_color), spaceAfter=1,
    )
    meta_style = ParagraphStyle(
        'meta', parent=styles['Normal'], fontSize=7.6, leading=10,
        textColor=colors.HexColor(brand.muted_color),
    )
    title_style = ParagraphStyle(
        'title', parent=styles['Heading2'], fontName='Helvetica-Bold',
        fontSize=13, leading=16, textColor=accent, spaceBefore=3 * mm, spaceAfter=1 * mm,
    )
    subtitle_style = ParagraphStyle(
        'subtitle', parent=styles['Normal'], fontSize=7.8, leading=10,
        textColor=colors.HexColor(brand.muted_color), spaceAfter=3 * mm,
    )
    cell_style = ParagraphStyle(
        'cell', parent=styles['Normal'], fontSize=6.6 if landscape_mode else 7.2,
        leading=8.2 if landscape_mode else 9, textColor=colors.HexColor(brand.cell_color),
    )

    story = [
        Paragraph(escape(brand.name), brand_style),
        Paragraph(escape(brand.legal_name), meta_style),
        Paragraph(escape(brand.address), meta_style),
        Paragraph(escape(brand.contact_line), meta_style),
        Paragraph(escape(f'NIF/TIN : {brand.tax_id}') if brand.tax_id else '', meta_style),
        HRFlowable(width='100%', thickness=1.4, color=accent, spaceBefore=3 * mm, spaceAfter=2 * mm),
        Paragraph(escape(title), title_style),
        Paragraph(escape(subtitle), subtitle_style),
    ]

    if rows:
        data = _table_data(Paragraph, cell_style, headers, rows)
        widths = _column_widths(headers, rows, (pagesize[0] - 2 * margin))
        table = Table(data, repeatRows=1, colWidths=widths, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), accent),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor(brand.on_brand_color)),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('GRID', (0, 1), (-1, -1), 0.3, colors.HexColor(brand.border_color)),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor(brand.paper_color), colors.HexColor(brand.soft_color)]),
            ('LEFTPADDING', (0, 0), (-1, -1), 3.5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3.5),
            ('TOPPADDING', (0, 0), (-1, -1), 3.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
        ]))
        story.append(table)
    else:
        story.append(Paragraph(
            'Aucune donnée sur la période sélectionnée.',
            ParagraphStyle('empty', parent=styles['Normal'], alignment=rl['TA_CENTER'],
                           fontSize=9, textColor=colors.HexColor(brand.muted_color), spaceBefore=10 * mm),
        ))

    story += [
        Spacer(1, 5 * mm),
        HRFlowable(width='100%', thickness=0.6, color=colors.HexColor(brand.border_color)),
        Paragraph(escape(brand.footer), meta_style),
    ]

    def page_chrome(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(colors.HexColor(brand.page_color))
        canvas.drawRightString(
            pagesize[0] - margin, 9 * mm, f'Page {canvas.getPageNumber()}',
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=page_chrome, onLaterPages=page_chrome)
    return output.getvalue()


def invoice_totals(invoice):
    subtotal = ZERO
    tax = ZERO
    for item in invoice.items.all():
        subtotal += item.quantity * item.unit_price
        tax += item.tax
    return {'subtotal': subtotal - tax, 'tax': tax, 'total': subtotal}


def render_invoice_pdf(invoice, receipt=None):
    rl = _reportlab()
    colors = rl['colors']
    mm = rl['mm']
    Paragraph = rl['Paragraph']
    ParagraphStyle = rl['ParagraphStyle']
    SimpleDocTemplate = rl['SimpleDocTemplate']
    Table = rl['Table']
    TableStyle = rl['TableStyle']
    Spacer = rl['Spacer']
    HRFlowable = rl['HRFlowable']

    brand = DocumentBrand.load()
    output = BytesIO()
    is_receipt = receipt is not None
    title = f'Reçu #{receipt.pk}' if is_receipt else invoice.number
    doc = SimpleDocTemplate(
        output, pagesize=rl['A4'], leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=34 * mm, bottomMargin=22 * mm, title=title, author=brand.name,
    )
    styles = rl['getSampleStyleSheet']()
    accent = colors.HexColor(brand.primary_color)
    brand_style = ParagraphStyle('brand', parent=styles['Heading1'], fontName='Helvetica-Bold',
                                 fontSize=18, leading=21, textColor=colors.HexColor(brand.ink_color))
    small = ParagraphStyle('small', parent=styles['Normal'], fontSize=8, leading=10.5,
                           textColor=colors.HexColor(brand.muted_color))
    cell = ParagraphStyle('cell', parent=styles['Normal'], fontSize=8, leading=10)

    story = [
        Paragraph(escape(brand.name), brand_style),
        Paragraph(escape(brand.legal_name), small),
        Paragraph(escape(brand.address), small),
        Paragraph(escape(brand.contact_line), small),
        Paragraph(escape(f'NIF/TIN : {brand.tax_id}') if brand.tax_id else '', small),
        HRFlowable(width='100%', thickness=1.4, color=accent, spaceBefore=4 * mm, spaceAfter=4 * mm),
    ]

    if is_receipt:
        paid_at = timezone.localtime(receipt.paid_at).strftime('%d/%m/%Y à %H:%M') if receipt.paid_at else '—'
        label = f'REÇU DE PAIEMENT #{receipt.pk}'
        meta_rows = [
            [Paragraph(f'<b>{label}</b>', cell),
             Paragraph(f'Encaissé le {escape(paid_at)}', cell)],
            [Paragraph(f'Facture : <b>{escape(invoice.number)}</b>', cell),
             Paragraph(f'Moyen : {escape(getattr(receipt.method, "name", "—") or "—")}', cell)],
            [Paragraph(f'Client : <b>{escape(str(invoice.customer))}</b>', cell),
             Paragraph(f'Caissier : {escape(str(getattr(receipt, "received_by", "") or "—"))}', cell)],
            [Paragraph(f'Téléphone : {escape(getattr(invoice.customer, "phone", "") or "—")}', cell),
             Paragraph(f'Référence : {escape(getattr(receipt, "reference", "") or "—")}', cell)],
        ]
    else:
        label = 'FACTURE'
        meta_rows = [
            [Paragraph(f'<b>{label} {escape(invoice.number)}</b>', cell),
             Paragraph(f'Émise le {invoice.issued_at:%d/%m/%Y à %H:%M}', cell)],
            [Paragraph(f'Client : <b>{escape(str(invoice.customer))}</b>', cell),
             Paragraph(f'Téléphone : {escape(getattr(invoice.customer, "phone", "") or "—")}', cell)],
            [Paragraph(f'Statut : {escape(invoice.get_status_display())}', cell),
             Paragraph(f'Solde restant : <b>{invoice.balance:.2f} {escape(brand.currency)}</b>', cell)],
        ]
    meta = Table(meta_rows, colWidths=[(rl['A4'][0] - 36 * mm) * 0.55,
                                       (rl['A4'][0] - 36 * mm) * 0.45])
    meta.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story += [meta, Spacer(1, 4 * mm)]

    headers = ['Désignation', 'Qté', 'P.U.', 'Taxe', 'Total']
    data = [[Paragraph(f'<b>{h}</b>', cell) for h in headers]]
    for item in invoice.items.all():
        data.append([
            Paragraph(escape(item.description), cell),
            Paragraph(escape(_text(item.quantity)), cell),
            Paragraph(f'{item.unit_price:.2f}', cell),
            Paragraph(f'{item.tax:.2f}', cell),
            Paragraph(f'{item.quantity * item.unit_price:.2f}', cell),
        ])
    widths = [(rl['A4'][0] - 36 * mm) * ratio for ratio in (0.52, 0.1, 0.14, 0.12, 0.12)]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), accent),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor(brand.on_brand_color)),
        ('GRID', (0, 1), (-1, -1), 0.3, colors.HexColor(brand.border_color)),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor(brand.paper_color), colors.HexColor(brand.soft_color)]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story += [table, Spacer(1, 4 * mm)]

    totals = invoice_totals(invoice)
    if is_receipt:
        total_data = [
            ['', Paragraph('Total facture', cell), Paragraph(f'{totals["total"]:.2f} {escape(brand.currency)}', cell)],
            ['', Paragraph('Total payé (facture)', cell), Paragraph(f'{invoice.paid_amount:.2f} {escape(brand.currency)}', cell)],
            ['', Paragraph('Solde restant', cell), Paragraph(f'{invoice.balance:.2f} {escape(brand.currency)}', cell)],
            ['', Paragraph('<b>Montant encaissé (ce reçu)</b>', cell), Paragraph(f'<b>{receipt.amount:.2f} {escape(brand.currency)}</b>', cell)],
        ]
    else:
        total_data = [
            ['', Paragraph('Sous-total HT', cell), Paragraph(f'{totals["subtotal"]:.2f}', cell)],
            ['', Paragraph('Taxes', cell), Paragraph(f'{totals["tax"]:.2f}', cell)],
            ['', Paragraph('<b>Total TTC</b>', cell), Paragraph(f'<b>{totals["total"]:.2f}</b>', cell)],
            ['', Paragraph('Montant payé', cell), Paragraph(f'{invoice.paid_amount:.2f}', cell)],
            ['', Paragraph('<b>Solde</b>', cell), Paragraph(f'<b>{invoice.balance:.2f}</b>', cell)],
        ]
    total_widths = [(rl['A4'][0] - 36 * mm) * ratio for ratio in (0.55, 0.25, 0.20)]
    total_table = Table(total_data, colWidths=total_widths, hAlign='RIGHT')
    style_cmds = [
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]
    if is_receipt:
        style_cmds.append(('LINEABOVE', (1, 3), (-1, 3), 0.8, accent))
    else:
        style_cmds.append(('LINEABOVE', (1, 2), (-1, 2), 0.8, accent))
    total_table.setStyle(TableStyle(style_cmds))
    story += [total_table, Spacer(1, 10 * mm)]
    footer_text = brand.receipt_footer if is_receipt else brand.footer
    story += [
        HRFlowable(width='100%', thickness=0.6, color=colors.HexColor(brand.border_color)),
        Paragraph(escape(footer_text), small),
    ]

    doc.build(story)
    return output.getvalue()


def render_order_pdf(order, kind='restaurant'):
    rl = _reportlab()
    colors = rl['colors']
    mm = rl['mm']
    Paragraph = rl['Paragraph']
    ParagraphStyle = rl['ParagraphStyle']
    SimpleDocTemplate = rl['SimpleDocTemplate']
    Table = rl['Table']
    TableStyle = rl['TableStyle']
    Spacer = rl['Spacer']
    HRFlowable = rl['HRFlowable']

    brand = DocumentBrand.load()
    output = BytesIO()
    title = f'Commande #{order.pk}'
    doc = SimpleDocTemplate(
        output, pagesize=rl['A4'], leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=34 * mm, bottomMargin=22 * mm, title=title, author=brand.name,
    )
    styles = rl['getSampleStyleSheet']()
    accent = colors.HexColor(brand.primary_color)
    brand_style = ParagraphStyle('brand', parent=styles['Heading1'], fontName='Helvetica-Bold',
                                 fontSize=18, leading=21, textColor=colors.HexColor(brand.ink_color))
    small = ParagraphStyle('small', parent=styles['Normal'], fontSize=8, leading=10.5,
                           textColor=colors.HexColor(brand.muted_color))
    cell = ParagraphStyle('cell', parent=styles['Normal'], fontSize=8, leading=10)

    bar = kind == 'bar'
    label = 'COMMANDE BAR' if bar else 'COMMANDE RESTAURANT'
    place = str(order.table) if order.table else ('Comptoir' if bar else 'Sans table')
    customer = str(order.customer) if order.customer else 'Client de passage'
    source = '' if bar else getattr(order, 'get_source_display', lambda: '')()
    created = timezone.localtime(order.created_at).strftime('%d/%m/%Y à %H:%M') if order.created_at else '—'

    story = [
        Paragraph(escape(brand.name), brand_style),
        Paragraph(escape(brand.legal_name), small),
        Paragraph(escape(brand.address), small),
        Paragraph(escape(brand.contact_line), small),
        HRFlowable(width='100%', thickness=1.4, color=accent, spaceBefore=4 * mm, spaceAfter=4 * mm),
    ]

    meta_rows = [
        [Paragraph(f'<b>{escape(label)} #{order.pk}</b>', cell),
         Paragraph(f'Créée le {escape(created)}', cell)],
        [Paragraph(f'Client : <b>{escape(customer)}</b>', cell),
         Paragraph(f'Table / lieu : {escape(place)}', cell)],
        [Paragraph(f'Statut : {escape(order.get_status_display())}', cell),
         Paragraph(f'Service : {escape(source)}' if source else '', cell)],
    ]
    meta = Table(meta_rows, colWidths=[(rl['A4'][0] - 36 * mm) * 0.55,
                                       (rl['A4'][0] - 36 * mm) * 0.45])
    meta.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story += [meta, Spacer(1, 4 * mm)]

    headers = ['Article', 'Qté', 'P.U.', 'Total']
    data = [[Paragraph(f'<b>{h}</b>', cell) for h in headers]]
    items = list(order.items.select_related('drink' if bar else 'menu_item').all())
    for item in items:
        name = item.drink.name if bar else item.menu_item.name
        note = getattr(item, 'notes', '') or ''
        desc = name + (f'<br/><font size="7" color="#5b6b7c">{escape(note)}</font>' if note else '')
        data.append([
            Paragraph(desc, cell),
            Paragraph(escape(_text(item.quantity)), cell),
            Paragraph(f'{item.unit_price:.2f}', cell),
            Paragraph(f'{item.subtotal:.2f}', cell),
        ])
    widths = [(rl['A4'][0] - 36 * mm) * ratio for ratio in (0.56, 0.12, 0.16, 0.16)]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), accent),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor(brand.on_brand_color)),
        ('GRID', (0, 1), (-1, -1), 0.3, colors.HexColor(brand.border_color)),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor(brand.paper_color), colors.HexColor(brand.soft_color)]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story += [table, Spacer(1, 4 * mm)]

    total_data = [
        ['', Paragraph('<b>Total commande</b>', cell), Paragraph(f'<b>{order.total_amount:.2f} {escape(brand.currency)}</b>', cell)],
    ]
    total_widths = [(rl['A4'][0] - 36 * mm) * ratio for ratio in (0.55, 0.25, 0.20)]
    total_table = Table(total_data, colWidths=total_widths, hAlign='RIGHT')
    total_table.setStyle(TableStyle([
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('LINEABOVE', (1, 0), (-1, 0), 0.8, accent),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story += [total_table]

    if getattr(order, 'notes', ''):
        story += [Spacer(1, 3 * mm), Paragraph(f'<b>Notes :</b> {escape(order.notes)}', small)]

    from apps.workspaces.services import find_bar_invoice, find_order_invoice
    invoice = find_bar_invoice(order) if bar else find_order_invoice(order)
    if invoice:
        story += [Spacer(1, 2 * mm), Paragraph(
            f'Facture / addition : <b>{escape(invoice.number)}</b> · solde {invoice.balance:.2f} {escape(brand.currency)}',
            small,
        )]

    story += [
        Spacer(1, 8 * mm),
        HRFlowable(width='100%', thickness=0.6, color=colors.HexColor(brand.border_color)),
        Paragraph(escape(brand.footer), small),
    ]
    doc.build(story)
    return output.getvalue()



def generate_report(code, params, file_format, user):
    if code not in REPORT_CATALOG or file_format not in {'csv', 'pdf'}:
        raise ValidationError('Rapport ou format non pris en charge.')
    if not user_can_run(user, code):
        raise ValidationError('Votre rôle ne permet pas de générer ce rapport.')

    brand = DocumentBrand.load()
    run = GeneratedReport.objects.create(
        report_type=code, parameters=params, file_format=file_format,
        status=GeneratedReport.Status.PROCESSING, created_by=user,
    )
    try:
        title, headers, rows, start, end = report_data(code, params)
        limit = MAX_PDF_ROWS if file_format == 'pdf' else MAX_EXPORT_ROWS
        if len(rows) > limit:
            raise ValidationError(
                f'Ce rapport contient {len(rows)} lignes ; la limite est de {limit}.'
            )
        subtitle = (
            f'Période du {start:%d/%m/%Y} au {end:%d/%m/%Y} · '
            f'{len(rows)} ligne(s)'
        )
        if file_format == 'csv':
            content = render_csv(headers, rows, brand, title, subtitle)
        else:
            content = render_report_pdf(
                title, headers, rows, brand, subtitle,
                generated_by=str(user),
            )
        filename = f'{code}-{timezone.now():%Y%m%d-%H%M%S}.{file_format}'
        run.file.save(filename, ContentFile(content), save=False)
        run.status = GeneratedReport.Status.COMPLETED
        run.completed_at = timezone.now()
        run.row_count = len(rows)
        run.file_size = len(content)
        run.error = ''
        run.save()
    except Exception as exc:
        run.status = GeneratedReport.Status.FAILED
        run.error = str(exc)[:2000] or exc.__class__.__name__
        run.save(update_fields=['status', 'error'])
        raise
    return run
