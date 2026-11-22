from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.core.forms import StaffLoginForm
from apps.core.public_views import public_about, public_bar, public_home, public_menu, public_room
from apps.core.views import (
    dashboard, entity_create, entity_delete, entity_detail, entity_edit,
    entity_list, entity_reset_password, module_home, search,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('workspace/', include('apps.workspaces.urls')),
    path('reports/', include('apps.reports.urls')),
    path('obr-ebms/', include('apps.obr_ebms.urls')),
    path('', dashboard, name='dashboard'),
    path('home/', public_home, name='public_home'),
    path('about/', public_about, name='public_about'),
    path('rooms/<int:pk>/', public_room, name='public_room'),
    path('menu/', public_menu, name='public_menu'),
    path('bar/', public_bar, name='public_bar'),
    path('login/', auth_views.LoginView.as_view(
        template_name='registration/login.html',
        authentication_form=StaffLoginForm,
        redirect_authenticated_user=True,
    ), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('search/', search, name='search'),
    path('module/<slug:module>/', module_home, name='module_home'),
    path('module/<slug:module>/<slug:entity>/', entity_list, name='entity_list'),
    path('module/<slug:module>/<slug:entity>/new/', entity_create, name='entity_create'),
    path('module/<slug:module>/<slug:entity>/<int:pk>/', entity_detail, name='entity_detail'),
    path('module/<slug:module>/<slug:entity>/<int:pk>/edit/', entity_edit, name='entity_edit'),
    path('module/<slug:module>/<slug:entity>/<int:pk>/delete/', entity_delete, name='entity_delete'),
    path('module/<slug:module>/<slug:entity>/<int:pk>/reset-password/', entity_reset_password, name='entity_reset_password'),
]

# Serve storefront uploads with Django's development server.
if settings.DEBUG:
    for directory in ('company', 'menu', 'drinks'):
        urlpatterns += static(f'{settings.MEDIA_URL}{directory}/', document_root=settings.MEDIA_ROOT / directory)
