from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.bar.models import Drink, DrinkCategory
from apps.hotel.models import BookingRequest, Reservation, Room, RoomRate, RoomType
from apps.inventory.models import Product, ProductCategory, Recipe, RecipeIngredient, UnitOfMeasure
from apps.restaurant.models import Menu, MenuItem

from .models import CompanyProfile, Customer


class CompanyProfileTests(TestCase):
    def test_profile_is_loaded_from_model(self):
        company = CompanyProfile.load()
        company.name = 'Hôtel Test'
        company.short_name = 'HT'
        company.city = 'Gitega'
        company.country = 'Burundi'
        company.address_override = ''
        company.phone = '+257 11 11 11 11'
        company.email = 'contact@example.bi'
        company.website = ''
        company.tagline = 'Bienvenue'
        company.save()

        company = CompanyProfile.load()
        self.assertEqual(company.name, 'Hôtel Test')
        self.assertEqual(company.address, 'Gitega, Burundi')
        self.assertEqual(company.contact_line, '+257 11 11 11 11 · contact@example.bi')
        self.assertEqual(company.theme_color, '#1f4d7a')

    def test_login_and_public_home_use_company_profile(self):
        company = CompanyProfile.load()
        company.name = 'Hôtel Test'
        company.tagline = 'Bienvenue au test'
        company.description = 'Description test publique'
        company.save()

        login = self.client.get(reverse('login'))
        self.assertContains(login, 'Hôtel Test')
        self.assertContains(login, 'Se connecter')
        self.assertNotContains(login, 'Description test publique')
        self.assertNotContains(login, 'Console de gestion')

        home = self.client.get('/')
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, 'Hôtel Test')
        self.assertContains(home, 'Description test publique')

    def test_login_form_shows_errors_and_preserves_the_destination(self):
        get_user_model().objects.create_user(username='reception', password='test-password')
        login_url = reverse('login')
        destination = reverse('public_menu')
        fields = {'username': 'reception', 'password': 'incorrect', 'next': destination}

        invalid = self.client.post(login_url, fields)
        self.assertContains(invalid, 'role="alert"')
        self.assertContains(invalid, f'name="next" value="{destination}"')
        self.assertNotContains(invalid, 'value="incorrect"')

        valid = self.client.post(login_url, fields | {'password': 'test-password'})
        self.assertRedirects(valid, destination)


class PublicSiteTests(TestCase):
    def test_about_uses_public_profile_and_is_linked_from_home(self):
        company = CompanyProfile.load()
        company.public_about = 'Présentation de notre établissement.'
        company.support_email = 'interne@example.bi'
        company.save()
        about_url = reverse('public_about')
        self.assertContains(self.client.get(reverse('public_home')), f'href="{about_url}"')
        about = self.client.get(about_url)
        self.assertContains(about, company.public_about)
        self.assertNotContains(about, company.support_email)

    def test_online_booking_request_reaches_reception_without_blocking_the_room(self):
        room_type = RoomType.objects.create(name='Chambre Jardin')
        room = Room.objects.create(number='101', room_type=room_type)
        today = timezone.localdate()
        query = f'check_in={today}&check_out={today + timedelta(days=1)}&adults=2'
        room_url = f'{reverse("public_room", args=[room_type.pk])}?{query}'
        guest = {'guest_name': 'Camille Client', 'email': 'client@example.bi'}

        self.assertContains(self.client.get(room_url), 'Envoyer ma demande')
        for _ in range(2):
            sent = self.client.post(room_url, guest, follow=True)
            self.assertContains(sent, 'Demande reçue.')
            self.assertNotContains(sent, guest['email'])
        booking = BookingRequest.objects.get()
        self.assertEqual(booking.room_type, room_type)
        self.assertEqual(booking.adults, 2)
        self.assertFalse(Reservation.objects.exists())

        room.operational_status = 'MAINTENANCE'
        room.save(update_fields=['operational_status'])
        unavailable = self.client.post(room_url, guest | {'email': 'other@example.bi'})
        self.assertContains(unavailable, 'Ce séjour n’est plus disponible')
        self.assertEqual(BookingRequest.objects.count(), 1)

        receptionist = get_user_model().objects.create_user(username='reception')
        self.client.force_login(receptionist)
        resolve_url = reverse('workspaces:resolve_booking_request', args=[booking.pk])
        self.assertEqual(self.client.post(resolve_url).status_code, 403)
        receptionist.groups.add(Group.objects.create(name='Receptionist'))
        reception_url = reverse('workspaces:reception')
        self.assertContains(self.client.get(reception_url), guest['guest_name'])
        self.assertEqual(self.client.get(resolve_url).status_code, 405)
        self.assertRedirects(self.client.post(resolve_url), reception_url)
        booking.refresh_from_db()
        self.assertIsNotNone(booking.handled_at)
        self.assertNotContains(self.client.get(reception_url), guest['guest_name'])

    def test_rooms_respect_capacity_status_and_reservation_dates(self):
        check_in = timezone.localdate() + timedelta(days=1)
        check_out = check_in + timedelta(days=1)
        room_type = RoomType.objects.create(name='Chambre Jardin', max_capacity=2)
        room = Room.objects.create(number='101', room_type=room_type)
        Room.objects.create(number='102', room_type=room_type, operational_status='MAINTENANCE')
        RoomRate.objects.create(room_type=room_type, price=42000, start_date=check_in)
        Reservation.objects.create(
            customer=Customer.objects.create(first_name='Camille', last_name='Privé'),
            room=room, check_in=check_in, check_out=check_out, status='CONFIRMED',
            created_by=get_user_model().objects.create_user(username='reception'),
        )
        company = CompanyProfile.load()
        company.email = 'reception@example.bi'
        company.save()
        url = reverse('public_room', args=[room_type.pk])

        response = self.client.get(url, {'check_in': check_in, 'check_out': check_out, 'adults': 2})
        self.assertContains(response, 'Indisponible pour ces dates')
        self.assertNotContains(response, 'Camille')
        self.assertNotContains(response, 'Demander une réservation par e-mail')

        params = {'check_in': check_out, 'check_out': check_out + timedelta(days=1), 'adults': 2}
        response = self.client.get(url, params)
        self.assertContains(response, 'Disponible pour ces dates')
        self.assertContains(response, '42 000')
        self.assertContains(response, 'Demander une réservation par e-mail')
        self.assertContains(self.client.get(url, params | {'adults': 3}), 'Capacité insuffisante')

        response = self.client.get(reverse('public_home'), params | {'check_out': check_out})
        self.assertContains(response, 'Le départ doit être postérieur')
        self.assertNotContains(response, 'Disponible pour ces dates')

        room_type.active = False
        room_type.save()
        self.assertEqual(self.client.get(url, params).status_code, 404)

    def test_booking_accepts_phone_and_whatsapp_without_an_email_address(self):
        room_type = RoomType.objects.create(name='Chambre Terrasse')
        Room.objects.create(number='201', room_type=room_type)
        room_url = reverse('public_room', args=[room_type.pk])
        guest = {'guest_name': 'Camille', 'contact_method': 'whatsapp'}

        invalid = self.client.post(room_url, guest | {'phone': '79 12 34 56'})
        self.assertContains(invalid, 'Saisissez votre numéro WhatsApp au format international')
        self.assertFalse(BookingRequest.objects.exists())

        variants = (
            ('phone', '79 12 34 56', '79123456'),
            ('whatsapp', '+257 (79) 12-34-56', '+25779123456'),
        )
        for channel, submitted, normalized in variants:
            response = self.client.post(room_url, guest | {'contact_method': channel, 'phone': submitted}, follow=True)
            self.assertContains(response, 'La réception vous contactera par le moyen choisi')
            self.assertTrue(BookingRequest.objects.filter(contact_method=channel, phone=normalized, email='').exists())

        company = CompanyProfile.load()
        company.whatsapp_number = '+25771112233'
        company.save(update_fields=['whatsapp_number'])
        self.assertContains(self.client.get(room_url), 'href="https://wa.me/25771112233"')

        staff = get_user_model().objects.create_user(username='reception', is_superuser=True)
        self.client.force_login(staff)
        inbox = self.client.get(reverse('workspaces:reception'))
        self.assertContains(inbox, 'href="tel:79123456"')
        self.assertContains(inbox, 'href="https://wa.me/25779123456"')

    def test_home_and_catalogues_share_public_item_filters(self):
        active_menu = Menu.objects.create(name='Carte principale')
        future_menu = Menu.objects.create(name='Carte future', available_from=timezone.localdate() + timedelta(days=1))
        MenuItem.objects.create(menu=active_menu, name='Plat du jour', selling_price=12000)
        MenuItem.objects.create(menu=future_menu, name='Plat futur', selling_price=12000)
        active_category = DrinkCategory.objects.create(name='Jus')
        inactive_category = DrinkCategory.objects.create(name='Archives', active=False)
        Drink.objects.create(category=active_category, name='Jus de mangue', selling_price=4000)
        Drink.objects.create(category=inactive_category, name='Jus archivé', selling_price=4000)

        for page in ('public_home', 'public_menu'):
            response = self.client.get(reverse(page))
            self.assertContains(response, 'Plat du jour')
            self.assertNotContains(response, 'Plat futur')
        for page in ('public_home', 'public_bar'):
            response = self.client.get(reverse(page))
            self.assertContains(response, 'Jus de mangue')
            self.assertNotContains(response, 'Jus archivé')

    def test_menu_and_bar_publish_only_recipe_ingredient_names(self):
        recipe = Recipe.objects.create(name='Recette interne', instructions='Instructions internes')
        unit = UnitOfMeasure.objects.create(name='Gramme')
        category = ProductCategory.objects.create(name='Épicerie')
        ingredient = Product.objects.create(name='Gingembre', sku='SKU-INTERNE', category=category, unit=unit)
        RecipeIngredient.objects.create(recipe=recipe, product=ingredient, unit=unit, quantity=20)
        menu = Menu.objects.create(name='Carte')
        dish = MenuItem.objects.create(menu=menu, name='Soupe', selling_price=3400, recipe_id=recipe.pk)
        drinks = DrinkCategory.objects.create(name='Jus')
        Drink.objects.create(category=drinks, name='Jus épicé', selling_price=2700, recipe_id=recipe.pk)

        for page in ('public_home', 'public_menu', 'public_bar'):
            response = self.client.get(reverse(page))
            self.assertContains(response, 'Gingembre')
            self.assertNotContains(response, 'Instructions internes')
            self.assertNotContains(response, 'SKU-INTERNE')

        dish.public_ingredients = 'Carottes'
        dish.save(update_fields=['public_ingredients'])
        restaurant = self.client.get(reverse('public_menu'))
        self.assertContains(restaurant, '<li>Carottes</li>')
        self.assertNotContains(restaurant, 'Gingembre')

    def test_catalogue_shows_entered_ingredients_and_skips_empty_ingredient_blocks(self):
        menu = Menu.objects.create(name='Carte')
        MenuItem.objects.create(
            menu=menu, name='Salade', selling_price=3400, description='Une entrée de légumes.',
            serving_size='250 g', image='menu/salade.webp', public_ingredients='  Tomates\n\nCarottes\nTomates',
        )
        MenuItem.objects.create(menu=menu, name='Plat sans fiche', selling_price=3000)
        category = DrinkCategory.objects.create(name='Jus')
        Drink.objects.create(category=category, name='Jus maison', selling_price=1300, serving_size='Verre de 25 cl', public_ingredients='Citron')
        response = self.client.get(reverse('public_menu'))
        self.assertContains(response, '<p class="pub-menu-portion">250 g</p>', count=1)
        self.assertContains(response, 'Une entrée de légumes.')
        self.assertContains(response, 'class="pub-menu-item-photo"', count=1)
        self.assertContains(response, '<li>Tomates</li>', count=1)
        self.assertContains(response, '<li>Carottes</li>', count=1)
        self.assertContains(response, 'Ingrédients renseignés', count=1)
        self.assertNotContains(response, 'Demandez les ingrédients à l’équipe.')
        bar = self.client.get(reverse('public_bar'))
        self.assertContains(bar, '<li>Citron</li>', count=1)
        self.assertContains(bar, '<p class="pub-menu-portion">Verre de 25 cl</p>', count=1)
