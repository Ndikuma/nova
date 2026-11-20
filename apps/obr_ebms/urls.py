from django.urls import path

from . import views

app_name = 'obr_ebms'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('configuration/', views.configuration, name='configuration'),
    path('products/', views.products, name='products'),
    path('products/<int:product_id>/', views.product_mapping, name='product_mapping'),
    path('invoices/', views.invoices, name='invoices'),
    path('invoices/<int:pk>/', views.invoice_detail, name='invoice_detail'),
    path('invoices/<int:pk>/action/<str:action>/', views.invoice_action, name='invoice_action'),
    path('stock/', views.stock_movements, name='stock'),
    path('stock/<int:pk>/', views.stock_movement_detail, name='stock_detail'),
    path('stock/<int:pk>/action/<str:action>/', views.stock_action, name='stock_action'),
    path('logs/', views.logs, name='logs'),
    path('tin-check/', views.tin_check, name='tin_check'),
    path('connection/<str:action>/', views.connection, name='connection'),
]
