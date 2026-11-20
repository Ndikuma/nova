from datetime import date
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from apps.core.models import Customer
from .models import RoomType,Room,Reservation
class ReservationTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user(username='reception',password='x'); self.customer=Customer.objects.create(first_name='A',last_name='Client',phone='000'); self.room=Room.objects.create(number='101',room_type=RoomType.objects.create(name='Double'))
    def test_overlap_is_rejected(self):
        Reservation.objects.create(customer=self.customer,room=self.room,check_in=date(2026,1,1),check_out=date(2026,1,4),status='CONFIRMED',created_by=self.user)
        conflict=Reservation(customer=self.customer,room=self.room,check_in=date(2026,1,3),check_out=date(2026,1,5),status='CONFIRMED',created_by=self.user)
        with self.assertRaises(ValidationError): conflict.full_clean()
