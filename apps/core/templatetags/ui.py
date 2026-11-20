"""Small presentation helpers shared by the NOVA templates."""
from decimal import Decimal, InvalidOperation

from django import template
from django.conf import settings

register = template.Library()

_GREEN = {'AVAILABLE', 'CONFIRMED', 'CHECKED_IN', 'PAID', 'DONE', 'COMPLETED',
          'ACTIVE', 'READY', 'SERVED', 'SUCCESS', 'SENT', 'GRANTED', 'ONLINE'}
_BLUE = {'OPEN', 'DRAFT', 'ISSUED', 'PREPARING', 'RESERVED', 'OCCUPIED',
         'IN_PROGRESS', 'PENDING', 'LOW', 'ENCODING'}
_ORANGE = {'PARTIAL', 'MAINTENANCE', 'CLEANING', 'CLEAN', 'WARNING',
           'PROCESSING', 'QUEUED', 'SUSPENDED', 'LOW_BATTERY'}
_RED = {'CANCELLED', 'CHECKED_OUT', 'OUT_OF_SERVICE', 'VOID', 'FAILED',
        'CLOSED', 'BLOCKED', 'REVOKED', 'EXPIRED', 'DENIED', 'LOST', 'FAULT',
        'OFFLINE', 'TAMPER'}


@register.filter
def badge_class(value):
    """Map a status/kind code to a status-badge class string."""
    if value is None:
        return 'status-badge status-neutral'
    code = str(value).strip().upper().replace(' ', '_')
    if code in _GREEN:
        return 'status-badge status-success'
    if code in _BLUE:
        return 'status-badge status-pill blue'
    if code in _ORANGE:
        return 'status-badge status-warning'
    if code in _RED:
        return 'status-badge status-danger'
    return 'status-badge status-neutral'


@register.filter
def field_label(name):
    """French label for a model field name."""
    from apps.core.navigation import field_label as label_for_field
    return label_for_field(name)


@register.filter
def money(value):
    """Format a number as a grouped amount using the configured currency."""
    if value in (None, ''):
        return '—'
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    whole = f'{amount:,.0f}'.replace(',', ' ')
    symbol = ''
    try:
        from apps.core.models import CompanyProfile
        company = CompanyProfile.load()
        symbol = company.currency_symbol or company.currency or ''
    except Exception:
        symbol = ''
    if not symbol:
        symbol = (
            getattr(settings, 'NOVA_CURRENCY_SYMBOL', '')
            or getattr(settings, 'NOVA_CURRENCY', '')
            or ''
        )
    return f'{whole} {symbol}'.strip()


@register.filter
def initials(value):
    if not value:
        return '?'
    parts = str(value).strip().split()
    if not parts:
        return '?'
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[-1][:1]).upper()


@register.filter
def get_item(mapping, key):
    """Dictionary lookup that works with dynamic keys in templates."""
    if hasattr(mapping, 'get'):
        return mapping.get(key)
    return None


@register.filter
def field_value(obj, field_name):
    """Return a display-friendly value for a model instance attribute."""
    try:
        value = getattr(obj, field_name)
    except (AttributeError, TypeError):
        return '—'
    if value is None or value == '':
        return '—'
    display = getattr(obj, f'get_{field_name}_display', None)
    if callable(display):
        try:
            return display()
        except Exception:
            pass
    return value
