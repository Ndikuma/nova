from decimal import Decimal
import json

from django import forms
from django.db.models import Q

from apps.bar.models import BarTable
from apps.core.models import Customer
from apps.finance.models import PaymentMethod
from apps.hotel.models import Reservation, Room, RoomRate
from apps.inventory.models import Product
from apps.restaurant.models import Order, Table


def _style(field, css='text-input'):
    widget = field.widget
    widget.attrs['class'] = (widget.attrs.get('class', '') + ' ' + css).strip()
    return field


def _date(field):
    field.widget = forms.DateInput(attrs={'type': 'date'})
    return _style(field)


class ReservationForm(forms.ModelForm):
    CUSTOMER_MODES = (
        ('existing', 'Client existant'),
        ('new', 'Nouveau client'),
    )
    customer_mode = forms.ChoiceField(
        choices=CUSTOMER_MODES, label='Client', required=False,
        widget=forms.RadioSelect(attrs={'data-customer-mode': ''}),
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.filter(is_walk_in=False),
        required=False,
        empty_label='Sélectionner un client',
        label='Client existant',
    )
    first_name = forms.CharField(max_length=80, required=False, label='Prénom')
    last_name = forms.CharField(max_length=80, required=False, label='Nom')
    phone = forms.CharField(max_length=30, required=False, label='Téléphone', widget=forms.TextInput(attrs={'type': 'tel'}))
    email = forms.EmailField(required=False, label='E-mail')
    identity_number = forms.CharField(max_length=80, required=False, label="Numéro de pièce d’identité")
    nationality = forms.CharField(max_length=80, required=False, label='Nationalité (facultatif)')

    class Meta:
        model = Reservation
        fields = (
            'customer_mode', 'customer', 'first_name', 'last_name', 'phone', 'email',
            'identity_number', 'nationality',
            'room', 'check_in', 'check_out', 'adults', 'children',
            'status', 'estimated_total', 'contact_information', 'notes',
        )
        widgets = {
            'check_in': forms.DateInput(attrs={'type': 'date'}),
            'check_out': forms.DateInput(attrs={'type': 'date'}),
        }

    customer_fields = ('first_name', 'last_name', 'phone', 'email', 'identity_number', 'nationality')

    def _suggested_total(self, room, check_in, check_out):
        if not (room and check_in and check_out):
            return None
        try:
            nights = (check_out - check_in).days
        except Exception:
            return None
        if nights <= 0:
            return None
        rate = (RoomRate.objects.filter(
            room_type_id=room.room_type_id, active=True, start_date__lte=check_in,
        ).filter(Q(end_date__isnull=True) | Q(end_date__gte=check_in))
            .order_by('-start_date', '-pk').values_list('price', flat=True).first())
        if rate is None:
            rate = (RoomRate.objects.filter(room_type_id=room.room_type_id, active=True)
                    .order_by('-start_date', '-pk').values_list('price', flat=True).first())
        if rate is None:
            return None
        return (rate * nights).quantize(Decimal('0.01'))

    def _build_room_rates(self):
        rates = {}
        qs = self.fields['room'].queryset.select_related('room_type')
        type_ids = [r.room_type_id for r in qs]
        latest = {}
        for rr in RoomRate.objects.filter(room_type_id__in=type_ids, active=True).order_by('room_type_id', '-start_date', '-pk'):
            latest.setdefault(rr.room_type_id, rr.price)
        for room in qs:
            price = latest.get(room.room_type_id)
            rates[str(room.pk)] = str(price) if price is not None else ''
        return rates

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].queryset = Customer.objects.filter(is_walk_in=False)
        self.fields['status'].choices = [
            ('DRAFT', 'Brouillon'),
            ('CONFIRMED', 'Confirmée'),
        ]
        self.fields['estimated_total'].required = False
        self.fields['estimated_total'].help_text = 'Calculé automatiquement selon la chambre et les nuits (modifiable selon la situation).'
        self.fields['estimated_total'].widget.attrs['data-estimated-total'] = '1'

        if self.is_bound:
            data = self.data.copy()
            mode = data.get('customer_mode')
            if mode == 'existing':
                for name in self.customer_fields:
                    data.pop(name, None)
            elif mode == 'new':
                data.pop('customer', None)
            if not mode:
                data['customer_mode'] = (
                    'existing' if data.get('customer') or getattr(self.instance, 'customer_id', None) else 'new'
                ) if any(data.get(name) for name in self.customer_fields) or getattr(self.instance, 'customer_id', None) else 'existing'
                # better: prefer existing if customer chosen else new if names provided else existing
                if data.get('customer') or getattr(self.instance, 'customer_id', None):
                    data['customer_mode'] = 'existing'
                elif any(data.get(name) for name in self.customer_fields):
                    data['customer_mode'] = 'new'
                else:
                    data['customer_mode'] = data.get('customer_mode') or 'existing'
            self.data = data
        else:
            self.initial.setdefault('customer_mode', 'existing' if (self.initial.get('customer') or getattr(self.instance, 'customer_id', None)) else 'existing')

        self.fields['room'].widget.attrs['data-room-select'] = '1'
        self.fields['check_in'].widget.attrs['data-stay-date'] = 'checkin'
        self.fields['check_out'].widget.attrs['data-stay-date'] = 'checkout'
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.RadioSelect):
                continue
            if isinstance(field.widget, forms.Select):
                _style(field, 'select-input')
            elif isinstance(field.widget, forms.Textarea):
                _style(field, 'textarea-input')
            else:
                _style(field, 'text-input')
        self.room_rates_json = json.dumps(self._build_room_rates())

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get('customer_mode') or 'existing'
        if mode == 'existing':
            if not cleaned.get('customer') and 'customer' not in self.errors:
                self.add_error('customer', 'Sélectionnez un client existant ou créez-en un nouveau.')
            for name in self.customer_fields:
                cleaned[name] = ''
        elif mode == 'new':
            if cleaned.get('customer'):
                self.add_error('customer', 'Choisissez un client existant ou renseignez un nouveau client.')
            for name in ('first_name', 'last_name'):
                if not cleaned.get(name) and name not in self.errors:
                    self.add_error(name, 'Renseignez ce champ pour créer le client.')
        room = cleaned.get('room') or getattr(self.instance, 'room', None)
        check_in = cleaned.get('check_in') or getattr(self.instance, 'check_in', None)
        check_out = cleaned.get('check_out') or getattr(self.instance, 'check_out', None)
        total = cleaned.get('estimated_total')
        if total in (None, '', Decimal('0'), Decimal('0.00'), 0):
            suggested = self._suggested_total(room, check_in, check_out)
            if suggested is not None:
                cleaned['estimated_total'] = suggested
        if cleaned.get('estimated_total') in (None, ''):
            cleaned['estimated_total'] = Decimal('0')
        return cleaned

    def save(self, commit=True):
        reservation = super().save(commit=False)
        if self.cleaned_data.get('customer_mode') == 'new':
            reservation.customer = Customer.objects.create(
                **{name: self.cleaned_data.get(name) or '' for name in self.customer_fields}
            )
        if commit:
            reservation.save()
            self.save_m2m()
        return reservation


class OrderCustomerForm(forms.Form):
    CUSTOMER_MODES = (
        ('walk_in', 'De passage'),
        ('existing', 'Client existant'),
        ('new', 'Nouveau client'),
    )
    customer_mode = forms.ChoiceField(
        choices=CUSTOMER_MODES, label='Type de client', required=False,
        widget=forms.RadioSelect(attrs={'data-customer-mode': ''}),
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.filter(is_walk_in=False),
        required=False,
        empty_label='Sélectionner un client',
        label='Client',
    )
    first_name = forms.CharField(max_length=80, required=False, label='Prénom')
    last_name = forms.CharField(max_length=80, required=False, label='Nom')
    phone = forms.CharField(max_length=30, required=False, label='Téléphone (facultatif)', widget=forms.TextInput(attrs={'type': 'tel'}))
    email = forms.EmailField(required=False, label='E-mail (facultatif)')
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}), label='Note de service')
    customer_fields = ('first_name', 'last_name', 'phone', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound:
            data = self.data.copy()
            mode = data.get('customer_mode')
            if mode in ('walk_in', 'existing'):
                for name in self.customer_fields:
                    data.pop(name, None)
            if mode in ('walk_in', 'new'):
                data.pop('customer', None)
            if not mode:
                data['customer_mode'] = (
                    'new' if any(data.get(name) for name in self.customer_fields)
                    else 'existing' if data.get('customer') else 'walk_in'
                )
            self.data = data
        else:
            self.initial.setdefault('customer_mode', 'existing' if self.initial.get('customer') else 'walk_in')

        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                _style(field, 'select-input')
            elif isinstance(field.widget, forms.Textarea):
                _style(field, 'textarea-input')
            elif not isinstance(field.widget, forms.RadioSelect):
                _style(field)

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get('customer_mode')
        if mode == 'existing' and not cleaned.get('customer') and 'customer' not in self.errors:
            self.add_error('customer', 'Sélectionnez un client.')
        if mode == 'new':
            if cleaned.get('customer'):
                self.add_error('customer', 'Choisissez un client existant ou renseignez un nouveau client.')
            for name in ('first_name', 'last_name'):
                if not cleaned.get(name) and name not in self.errors:
                    self.add_error(name, 'Renseignez ce champ pour créer le client.')
        return cleaned

    def save_customer(self):
        if self.cleaned_data['customer_mode'] == 'new':
            return Customer.objects.create(**{name: self.cleaned_data[name] for name in self.customer_fields})
        return self.cleaned_data['customer']


class WaiterOrderForm(OrderCustomerForm):
    table = forms.ModelChoiceField(
        queryset=Table.objects.filter(active=True).exclude(status='CLOSED').order_by('section', 'name'),
        required=False,
        empty_label='Aucune table / à emporter',
        label='Table',
    )
    source = forms.ChoiceField(choices=Order.SOURCE, initial='DINE_IN', label='Mode de service')

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('source') == 'DINE_IN' and not cleaned.get('table') and 'table' not in self.errors:
            self.add_error('table', 'Sélectionnez une table pour un service sur place.')
        return cleaned


class BarOrderForm(OrderCustomerForm):
    table = forms.ModelChoiceField(
        queryset=BarTable.objects.filter(active=True).exclude(status='CLOSED').order_by('name'),
        required=False,
        empty_label='Comptoir / aucune table',
        label='Table ou comptoir',
    )


class AttachCustomerForm(forms.Form):
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.filter(is_walk_in=False),
        label='Client',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields['customer'], 'select-input')


class PaymentForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=0.01, label='Montant à encaisser',
    )
    method = forms.ModelChoiceField(
        queryset=PaymentMethod.objects.filter(active=True).order_by('name'),
        label='Moyen de paiement',
    )
    reference = forms.CharField(
        required=False, max_length=120, label='Référence / transaction',
        help_text='Référence Mobile Money, carte ou virement (facultatif).',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                _style(field, 'select-input')
            else:
                _style(field, 'text-input')


class RestockForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(active=True).order_by('name'),
        label='Produit',
    )
    note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={'rows': 2}),
        label='Besoin / quantité souhaitée',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields['product'], 'select-input')
        _style(self.fields['note'], 'textarea-input')
