from django.utils import timezone

from .models import CompanyProfile
from .navigation import MODULES, build_nav, primary_workspace, user_role_label


def _load_company():
    try:
        return CompanyProfile.load()
    except Exception:
        return CompanyProfile(
            name='Nova Hospitality',
            short_name='NOVA',
            initials='N',
            tagline='Hospitality suite',
            description='Réception, chambres, restaurant, bar, inventaire et finances dans un seul espace.',
            currency='BIF',
            currency_symbol='FBu',
        )


def navigation(request):
    """Inject the sidebar structure and a few console-wide values."""
    path = request.path or ''
    current_module = None
    for key in MODULES:
        if path.startswith(f'/module/{key}/'):
            current_module = key
            break
    company = _load_company()
    return {
        'company': company,
        'nav_sections': build_nav(getattr(request, 'user', None)),
        'current_module': current_module,
        'today': timezone.localdate(),
        'user_role': user_role_label(getattr(request, 'user', None)),
        'workspace_entry': primary_workspace(getattr(request, 'user', None)),
        'workspace_active': path.startswith('/workspace/'),
        'can_view_reports': bool(getattr(request.user, 'is_authenticated', False)),
        'can_manage_ebms': _can_manage_ebms(getattr(request, 'user', None), company),
        'obr_ebms_feature_enabled': bool(getattr(company, 'obr_ebms_enabled', False)),
    }


def _can_manage_ebms(user, company=None):
    if not getattr(user, 'is_authenticated', False):
        return False
    if company is not None and not getattr(company, 'obr_ebms_enabled', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return bool(set(user.groups.values_list('name', flat=True)).intersection({'Superadmin', 'Owner'}))
