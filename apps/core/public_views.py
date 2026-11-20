import re
from datetime import timedelta

from django import forms
from django.contrib import messages
from django.db.models import Exists, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_http_methods, require_safe

from apps.bar.models import Drink
from apps.hotel.models import BookingRequest, Reservation, Room, RoomRate, RoomType
from apps.restaurant.catalog import available_dishes, with_ingredients


class StaySearchForm(forms.Form):
    check_in = forms.DateField(label='Arrivée', widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    check_out = forms.DateField(label='Départ', widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    adults = forms.IntegerField(label='Voyageurs', min_value=1, max_value=2_147_483_647)

    def clean(self):
        data = super().clean()
        check_in = data.get('check_in')
        check_out = data.get('check_out')
        if check_in and check_in < timezone.localdate():
            self.add_error('check_in', 'Choisissez une date à partir d’aujourd’hui.')
        if check_in and check_out and check_out <= check_in:
            self.add_error('check_out', 'Le départ doit être postérieur à l’arrivée.')
        return data


class PublicBookingForm(forms.ModelForm):
    contact_method = forms.ChoiceField(
        label='Comment souhaitez-vous être contacté ?', required=False,
        choices=BookingRequest.ContactMethod.choices, initial=BookingRequest.ContactMethod.EMAIL,
        widget=forms.Select(attrs={'data-booking-channel': ''}),
    )

    class Meta:
        model = BookingRequest
        fields = ('guest_name', 'contact_method', 'email', 'phone')
        widgets = {
            'guest_name': forms.TextInput(attrs={'autocomplete': 'name'}),
            'email': forms.EmailInput(attrs={'autocomplete': 'email'}),
            'phone': forms.TextInput(attrs={'type': 'tel', 'autocomplete': 'tel'}),
        }
        help_texts = {'phone': 'Pour WhatsApp, indiquez aussi l’indicatif du pays, comme +257.'}

    def clean_contact_method(self):
        return self.cleaned_data['contact_method'] or BookingRequest.ContactMethod.EMAIL

    def clean(self):
        data = super().clean()
        channel = data.get('contact_method')
        if channel == BookingRequest.ContactMethod.EMAIL:
            if not data.get('email') and 'email' not in self.errors:
                self.add_error('email', 'Saisissez votre adresse e-mail.')
            data['phone'] = ''
        elif channel in (BookingRequest.ContactMethod.PHONE, BookingRequest.ContactMethod.WHATSAPP):
            number = re.sub(r'[\s().-]+', '', data.get('phone', ''))
            if number.startswith('00'):
                number = '+' + number[2:]
            if channel == BookingRequest.ContactMethod.WHATSAPP and not re.fullmatch(r'\+[1-9][0-9]{5,14}', number):
                self.add_error('phone', 'Saisissez votre numéro WhatsApp au format international, avec l’indicatif (+257, par exemple).')
            elif not re.fullmatch(r'(?:\+[1-9][0-9]{5,14}|[0-9]{6,15})', number):
                self.add_error('phone', 'Saisissez un numéro de téléphone valide.')
            else:
                data['phone'] = number
            data['email'] = ''
        return data


def _stay_search(request):
    today = timezone.localdate()
    defaults = {'check_in': today, 'check_out': today + timedelta(days=1), 'adults': 1}
    params = {field: request.GET[field] for field in defaults if field in request.GET}
    form = StaySearchForm(params or None, initial=defaults)
    form.fields['check_in'].widget.attrs['min'] = today.isoformat()
    form.fields['check_out'].widget.attrs['min'] = (today + timedelta(days=1)).isoformat()
    if not form.is_bound:
        return form, defaults
    return form, form.cleaned_data if form.is_valid() else None


def _room_types(stay):
    room_types = RoomType.objects.filter(active=True).order_by('name', 'pk')
    if stay is None:
        return room_types

    check_in, check_out = stay['check_in'], stay['check_out']
    conflicts = Reservation.objects.filter(
        room_id=OuterRef('pk'), status__in=['CONFIRMED', 'CHECKED_IN'],
        check_in__lt=check_out, check_out__gt=check_in,
    )
    available_rooms = Room.objects.filter(
        room_type_id=OuterRef('pk'), operational_status='AVAILABLE',
    ).filter(~Exists(conflicts))
    arrival_rates = RoomRate.objects.filter(
        room_type_id=OuterRef('pk'), active=True, start_date__lte=check_in,
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=check_in)).order_by('-start_date', '-pk')
    return room_types.annotate(
        is_available=Exists(available_rooms),
        nightly_rate=Subquery(arrival_rates.values('price')[:1]),
    )


def _drinks():
    return Drink.objects.filter(available=True, category__active=True).select_related('category').order_by(
        'category__name', 'category_id', 'name', 'pk',
    )


def public_home(request):
    form, stay = _stay_search(request)
    return render(request, 'public/home.html', {
        'search_form': form,
        'stay': stay,
        'room_types': _room_types(stay),
        'featured_dishes': with_ingredients(available_dishes()[:3]),
        'featured_drinks': with_ingredients(_drinks()[:3]),
    })


@require_http_methods(['GET', 'HEAD', 'POST'])
def public_room(request, pk):
    form, stay = _stay_search(request)
    room_type = get_object_or_404(_room_types(stay), pk=pk)
    can_request = stay and room_type.is_available and stay['adults'] <= room_type.max_capacity
    stay_query = urlencode(stay) if stay else ''
    booking_form = PublicBookingForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if not can_request:
            messages.error(request, 'Ce séjour n’est plus disponible. Choisissez d’autres dates ou une autre chambre.', extra_tags='web-booking')
        elif booking_form.is_valid():
            details = booking_form.cleaned_data
            BookingRequest.objects.get_or_create(
                room_type=room_type, handled_at=None, contact_method=details['contact_method'],
                email=details['email'], phone=details['phone'],
                **stay, defaults={'guest_name': details['guest_name']},
            )
            messages.success(request, 'Demande reçue. La réception vous contactera par le moyen choisi pour confirmer votre séjour.', extra_tags='web-booking')
            return redirect(f'{reverse("public_room", args=[room_type.pk])}?{stay_query}#demande')
    return render(request, 'public/room.html', {
        'search_form': form,
        'stay': stay,
        'stay_query': stay_query,
        'room_type': room_type,
        'booking_form': booking_form,
        'can_request': can_request,
    })


@require_safe
def public_about(request):
    return render(request, 'public/about.html')


def public_menu(request):
    return render(request, 'public/menu.html', {'items': with_ingredients(available_dishes())})


def public_bar(request):
    return render(request, 'public/bar.html', {'drinks': with_ingredients(_drinks())})
