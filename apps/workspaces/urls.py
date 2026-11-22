from django.urls import path

from . import views

app_name = 'workspaces'

urlpatterns = [
    path('', views.workspace_home, name='home'),
    path('superadmin/', views.superadmin_workspace, name='superadmin'),
    path('owner/', views.owner_workspace, name='owner'),

    path('reception/', views.reception_workspace, name='reception'),
    path('reception/rooms/<int:pk>/', views.reception_room_detail, name='reception_room_detail'),
    path('reception/booking-requests/<int:pk>/resolve/', views.resolve_booking_request, name='resolve_booking_request'),
    path('reception/booking-requests/<int:pk>/reopen/', views.reopen_booking_request, name='reopen_booking_request'),
    path('reception/reservations/new/', views.reservation_create, name='reservation_create'),
    path('reception/reservations/<int:pk>/edit/', views.reservation_edit, name='reservation_edit'),
    path('reception/reservations/<int:pk>/check-in/', views.reservation_check_in,
         name='reservation_check_in'),
    path('reception/reservations/<int:pk>/prepare-checkout/', views.reservation_prepare_checkout,
         name='reservation_prepare_checkout'),
    path('reception/reservations/<int:pk>/check-out/', views.reservation_check_out,
         name='reservation_check_out'),
    path('reception/reservations/<int:pk>/cancel/', views.reservation_cancel,
         name='reservation_cancel'),
    path('reception/housekeeping/<int:pk>/status/', views.housekeeping_status,
         name='housekeeping_status'),

    path('kitchen/', views.kitchen_workspace, name='kitchen'),
    path('kitchen/restock/', views.kitchen_restock, name='kitchen_restock'),
    path('kitchen/menu/<int:pk>/toggle/', views.menu_item_toggle, name='menu_item_toggle'),

    path('service/', views.waiter_workspace, name='service'),
    path('service/tables/<int:pk>/', views.service_table_detail, name='service_table_detail'),
    path('service/orders/new/', views.service_order_create, name='service_order_create'),
    path('service/orders/<int:pk>/edit/', views.service_order_create, name='service_order_edit'),
    path('service/orders/<int:pk>/action/<str:action>/', views.restaurant_order_action,
         name='service_order_action'),
    path('service/orders/<int:pk>/attach-customer/', views.service_attach_customer,
         name='service_attach_customer'),
    path('service/orders/<int:pk>/bill/', views.service_request_bill, name='service_request_bill'),
    path('service/orders/<int:pk>/charge-room/', views.service_charge_room, name='service_charge_room'),

    path('bar/', views.bartender_workspace, name='bar'),
    path('bar/tables/<int:pk>/', views.bar_table_detail, name='bar_table_detail'),
    path('bar/orders/new/', views.bar_order_create, name='bar_order_create'),
    path('bar/orders/<int:pk>/edit/', views.bar_order_create, name='bar_order_edit'),
    path('bar/orders/<int:pk>/action/<str:action>/', views.bar_order_action,
         name='bar_order_action'),
    path('bar/orders/<int:pk>/attach-customer/', views.bar_attach_customer,
         name='bar_attach_customer'),
    path('bar/orders/<int:pk>/bill/', views.bar_request_bill, name='bar_request_bill'),
    path('bar/orders/<int:pk>/charge-room/', views.bar_charge_room, name='bar_charge_room'),
    path('bar/restock/', views.bar_restock, name='bar_restock'),

    path('cashier/', views.cashier_workspace, name='cashier'),
    path('cashier/invoices/<int:pk>/pay/', views.payment_create, name='payment_create'),
    path('cashier/orders/<int:pk>/invoice/', views.cashier_prepare_order_invoice,
         name='cashier_prepare_order_invoice'),
    path('cashier/bar-orders/<int:pk>/invoice/', views.cashier_prepare_bar_invoice,
         name='cashier_prepare_bar_invoice'),
    path('cashier/payments/<int:pk>/receipt/', views.payment_receipt, name='payment_receipt'),
    path('finance/balance/', views.finance_balance, name='finance_balance'),
]
