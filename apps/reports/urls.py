from django.urls import path

from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.report_center, name='center'),
    path('generate/', views.generate, name='generate'),
    path('<int:pk>/download/', views.download, name='download'),
    path('preview/<slug:code>/', views.preview, name='preview'),
    path('preview/<slug:code>/pdf/', views.preview_pdf, name='preview_pdf'),
    path('documents/invoice/<int:pk>/print/', views.invoice_print, name='invoice_print'),
    path('documents/invoice/<int:pk>/pdf/', views.invoice_pdf, name='invoice_pdf'),
    path('documents/receipt/<int:pk>/print/', views.receipt_print, name='receipt_print'),
    path('documents/receipt/<int:pk>/pdf/', views.receipt_pdf, name='receipt_pdf'),
    path('documents/order/<str:kind>/<int:pk>/print/', views.order_print, name='order_print'),
    path('documents/order/<str:kind>/<int:pk>/pdf/', views.order_pdf, name='order_pdf'),
]
