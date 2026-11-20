"""Client et services OBR eBMS adaptés à NOVA Hospitality.

La logique métier reprend l’implémentation de référence du projet Pharmacy,
mais elle est reliée aux modèles de ce projet : ``finance.Invoice``,
``finance.InvoiceItem`` et ``inventory.StockMovement``.
"""

import json
import logging
import re
import time
from decimal import Decimal, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.core.models import CompanyProfile
from apps.finance.models import Invoice
from .endpoints import (
    OBREndpoints, OBRMovementType, OBRCurrency, OBRInvoiceType,
    OBRTaxpayerType, OBRFiscalCenter, get_endpoint_url,
)
from .models import (
    EBMSConfiguration, EBMSInvoice, EBMSInvoiceItem, EBMSProductMapping,
    EBMSStockMovement, OBRSyncLog, SyncStatus,
)

logger = logging.getLogger(__name__)


class OBRClientError(Exception):
    """Erreur de communication avec OBR eBMS."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def company_feature_enabled():
    try:
        return CompanyProfile.load().obr_ebms_enabled
    except Exception:
        return False


def get_configuration():
    return EBMSConfiguration.load()


def _decimal(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)


def _decimal_string(value):
    return str(_decimal(value)) if value is not None else '0'


def _safe_payload(payload):
    safe = dict(payload or {})
    safe.pop('password', None)
    return safe


def _format_datetime(value):
    if not value:
        return timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    return timezone.localtime(value).strftime('%Y-%m-%d %H:%M:%S')


def _format_datetime_signature(value):
    if not value:
        return timezone.localtime(timezone.now()).strftime('%Y%m%d%H%M%S')
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    return timezone.localtime(value).strftime('%Y%m%d%H%M%S')


def _customer_name(invoice):
    customer = invoice.customer
    if not customer:
        return get_configuration().default_customer_name or 'Client comptoir'
    return f'{customer.first_name} {customer.last_name}'.strip()


def _service_key(invoice_item):
    return (invoice_item.source_service or '').strip().lower()


def _service_item_code(config, invoice_item):
    key = _service_key(invoice_item)
    if 'hôtel' in key or 'hotel' in key:
        return config.hotel_item_code
    if 'restaurant' in key:
        return config.restaurant_item_code
    if 'bar' in key:
        return config.bar_item_code
    if 'inventaire' in key or 'inventory' in key or 'stock' in key:
        return config.inventory_item_code
    return config.default_item_code


def _product_mapping_for_item(invoice_item):
    """Find an inventory product mapping by the invoice line description."""
    description = (invoice_item.description or '').strip()
    if not description:
        return None
    return EBMSProductMapping.objects.select_related('product').filter(
        product__name__iexact=description,
    ).first()


def _item_fiscal_values(config, invoice_item):
    mapping = _product_mapping_for_item(invoice_item)
    quantity = _decimal(invoice_item.quantity)
    gross = _decimal(quantity * invoice_item.unit_price)
    tax = _decimal(invoice_item.tax)

    if mapping:
        item_code = mapping.item_code or _service_item_code(config, invoice_item) or config.default_item_code
        designation = mapping.item_designation or mapping.product.name
        unit = mapping.measurement_unit or config.default_measurement_unit or 'PCE'
        vat_rate = mapping.vat_rate
        ct_rate = mapping.consumption_tax_rate
        tl_rate = mapping.tourism_levy_rate
        tsce_rate = mapping.special_tax_rate
        other_rate = mapping.other_tax_rate
        eligibility = mapping.eligibility
    else:
        item_code = _service_item_code(config, invoice_item) or config.default_item_code
        designation = invoice_item.description
        unit = config.default_measurement_unit or 'PCE'
        vat_rate = config.default_vat_rate
        ct_rate = config.default_consumption_tax_rate
        tl_rate = config.default_tourism_levy_rate
        tsce_rate = config.default_special_tax_rate
        other_rate = config.default_other_tax_rate
        eligibility = EBMSProductMapping.Eligibility.REQUIRED

    if tax > 0:
        vat = tax
    elif vat_rate:
        vat = _decimal(gross * vat_rate / (Decimal('100') + vat_rate))
    else:
        vat = Decimal('0')

    consumption_tax = _decimal(gross * ct_rate / Decimal('100')) if ct_rate else Decimal('0')
    tourism_levy = _decimal(gross * tl_rate / Decimal('100')) if tl_rate else Decimal('0')
    special_tax = _decimal(gross * tsce_rate / Decimal('100')) if tsce_rate else Decimal('0')
    other_tax = _decimal(gross * other_rate / Decimal('100')) if other_rate else Decimal('0')

    if not item_code:
        item_code = re.sub(r'[^A-Za-z0-9._-]+', '-', designation or 'ARTICLE')[:30] or 'ARTICLE'

    return {
        'designation': (designation or 'Article')[:500],
        'quantity': quantity,
        'item_price': _decimal(invoice_item.unit_price),
        'gross': gross,
        'vat': vat,
        'consumption_tax': consumption_tax,
        'tourism_levy': tourism_levy,
        'special_tax': special_tax,
        'other_tax': other_tax,
        'price_without_vat': gross - vat,
        'price_with_vat': gross,
        'total_amount': gross,
        'item_code': item_code,
        'measurement_unit': unit,
        'eligibility': eligibility,
    }


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

class OBRClient:
    def __init__(self, configuration=None, user=None):
        self.configuration = configuration or get_configuration()
        self.user = user
        if not company_feature_enabled():
            raise OBRClientError("Le module OBR eBMS n’est pas activé pour cet établissement.")
        if not self.configuration.enabled:
            raise OBRClientError('La transmission OBR eBMS est désactivée.')
        if not self.configuration.username or not self.configuration.password:
            raise OBRClientError('Identifiant ou mot de passe OBR manquant.')
        self.password = self.configuration.password
        self.base_url = self.configuration.base_url.rstrip('/') + '/'

    def _log(self, action, reference, request_payload, response, success, error, started):
        OBRSyncLog.objects.create(
            action=action,
            reference=reference,
            success=success,
            request_payload=_safe_payload(request_payload),
            response_payload=response,
            error_message=error,
            duration_ms=int((time.monotonic() - started) * 1000),
            performed_by=self.user,
        )

    def _request(self, url, payload, headers=None):
        request_headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if headers:
            request_headers.update(headers)
        request = Request(
            url, data=json.dumps(payload).encode('utf-8'),
            headers=request_headers, method='POST',
        )
        try:
            with urlopen(request, timeout=self.configuration.request_timeout_seconds) as result:
                raw = result.read().decode('utf-8')
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            body = exc.read().decode('utf-8', errors='replace')
            if exc.code in (401, 403):
                self._clear_token()
            raise OBRClientError(f'HTTP {exc.code}: {body[:500]}') from exc
        except URLError as exc:
            raise OBRClientError(str(exc.reason)) from exc
        except json.JSONDecodeError as exc:
            raise OBRClientError(f'Réponse JSON invalide d’OBR : {exc}') from exc

    def _token_key(self):
        return f'obr-ebms-token-{self.configuration.pk}-{self.configuration.username}'

    def _clear_token(self):
        cache.delete(self._token_key())

    def _login(self):
        payload = {'username': self.configuration.username, 'password': self.password}
        started = time.monotonic()
        response = None
        error = ''
        success = False
        try:
            response = self._request(
                get_endpoint_url(self.base_url, OBREndpoints.LOGIN), payload,
            )
            token = response.get('result', {}).get('token')
            if not token:
                raise OBRClientError('La connexion OBR n’a pas renvoyé de jeton.')
            success = True
            cache.set(self._token_key(), token, 55 * 60)
            return token
        except Exception as exc:
            error = str(exc)
            if isinstance(exc, OBRClientError):
                raise
            raise OBRClientError(f'Connexion OBR échouée : {exc}') from exc
        finally:
            self._log(OBRSyncLog.Action.LOGIN, '', payload, response, success, error, started)

    def _token(self):
        token = cache.get(self._token_key())
        if token:
            return token
        try:
            return self._login()
        except OBRClientError:
            self._clear_token()
            return self._login()

    def post(self, path, payload, action, reference='', max_retries=2):
        started = time.monotonic()
        response = None
        error = ''
        success = False
        try:
            token = self._token()
            response = self._request(
                get_endpoint_url(self.base_url, path), payload,
                {'Authorization': f'Bearer {token}'},
            )
            success = True
            return response
        except OBRClientError as exc:
            error = str(exc)
            if ('HTTP 401' in error or 'HTTP 403' in error) and max_retries > 0:
                self._clear_token()
                return self.post(path, payload, action, reference, max_retries - 1)
            raise
        except Exception as exc:
            error = str(exc)
            raise OBRClientError(f'OBR {action} échoué : {exc}') from exc
        finally:
            self._log(action, reference, payload, response, success, error, started)


# ---------------------------------------------------------------------------
# Invoice preparation / sending
# ---------------------------------------------------------------------------

def validate_invoice(invoice):
    errors = []
    config = get_configuration()
    if not company_feature_enabled():
        errors.append("Le module OBR eBMS n’est pas activé pour cet établissement.")
    elif not config.enabled:
        errors.append('La configuration OBR eBMS n’est pas activée.')
    if invoice.status == 'VOID':
        errors.append('Une facture annulée ne peut pas être fiscalisée.')
    if invoice.total_amount <= 0:
        errors.append('Le total de la facture doit être positif.')
    return errors


@transaction.atomic
def prepare_invoice(invoice, user=None):
    config = get_configuration()
    invoice = Invoice.objects.select_related('customer').get(pk=invoice.pk)
    defaults = {
        'invoice_number': invoice.number,
        'invoice_identifier': f'{invoice.number}-{invoice.pk}',
        'invoice_date': invoice.issued_at,
        'customer_name': _customer_name(invoice),
        'customer_tin': getattr(invoice.customer, 'tax_id', '') or '',
        'customer_address': getattr(invoice.customer, 'address', '') or '',
        'currency': 'BIF',
    }
    record, created = EBMSInvoice.objects.get_or_create(invoice=invoice, defaults=defaults)
    if not created and record.status in {SyncStatus.SENT, SyncStatus.CANCELLED}:
        return record

    errors = validate_invoice(invoice)
    record.validation_errors = errors
    record.status = SyncStatus.BLOCKED if errors else SyncStatus.PENDING
    record.save(update_fields=['validation_errors', 'status', 'updated_at'])

    if record.status not in {SyncStatus.SENT, SyncStatus.CANCELLED}:
        record.items.all().delete()
        skipped = 0
        for invoice_item in invoice.items.all():
            values = _item_fiscal_values(config, invoice_item)
            if values['eligibility'] == EBMSProductMapping.Eligibility.EXCLUDED:
                skipped += 1
                continue
            EBMSInvoiceItem.objects.create(
                invoice=record,
                invoice_item=invoice_item,
                designation=values['designation'],
                quantity=values['quantity'],
                item_price=values['item_price'],
                consumption_tax=values['consumption_tax'],
                tourism_levy=values['tourism_levy'],
                special_tax=values['special_tax'],
                other_tax=values['other_tax'],
                price_without_vat=values['price_without_vat'],
                vat=values['vat'],
                price_with_vat=values['price_with_vat'],
                total_amount=values['total_amount'],
                item_code=values['item_code'],
                measurement_unit=values['measurement_unit'],
            )
        if not errors and not record.items.exists():
            record.status = SyncStatus.NOT_REQUIRED
            record.save(update_fields=['status', 'updated_at'])

    record.request_payload = build_invoice_payload(record)
    record.save(update_fields=['request_payload', 'updated_at'])
    return record


def build_invoice_payload(record):
    config = get_configuration()
    invoice_date = record.invoice_date or timezone.now()
    tp_tin = config.taxpayer_tin or ''
    username = config.username or ''
    date_signature = _format_datetime_signature(invoice_date)
    invoice_number = record.invoice_number or ''
    identifier = f'{tp_tin}/{username}/{date_signature}/{invoice_number}'

    items = []
    for item in record.items.all():
        items.append({
            'item_designation': item.designation,
            'item_quantity': str(item.quantity),
            'item_price': _decimal_string(item.item_price),
            'item_ct': _decimal_string(item.consumption_tax),
            'item_tl': _decimal_string(item.tourism_levy),
            'item_tsce_tax': _decimal_string(item.special_tax),
            'item_ott_tax': _decimal_string(item.other_tax),
            'item_price_nvat': _decimal_string(item.price_without_vat),
            'vat': _decimal_string(item.vat),
            'item_price_wvat': _decimal_string(item.price_with_vat),
            'item_total_amount': _decimal_string(item.total_amount),
            'item_code': item.item_code,
            'item_measurement_unit': item.measurement_unit or '',
            'invoice_type': record.invoice_type or '',
        })

    return {
        'invoice_number': record.invoice_number,
        'invoice_type': record.invoice_type or OBRInvoiceType.NORMAL,
        'invoice_date': _format_datetime(invoice_date),
        'invoice_signature': identifier,
        'invoice_signature_date': _format_datetime(invoice_date),
        'tp_type': config.taxpayer_type or OBRTaxpayerType.INDIVIDUAL,
        'tp_name': config.taxpayer_name or '',
        'tp_TIN': tp_tin,
        'tp_trade_number': config.trade_number or '',
        'tp_postal_number': '',
        'tp_phone_number': config.phone_number or '',
        'tp_address_province': config.address or '',
        'tp_address_commune': '',
        'tp_address_quartier': '',
        'tp_address_avenue': '',
        'tp_address_rue': '',
        'tp_address_number': '',
        'vat_taxpayer': '1' if config.vat_taxpayer else '0',
        'ct_taxpayer': '1' if config.consumption_taxpayer else '0',
        'tl_taxpayer': '1' if config.tourism_levy_taxpayer else '0',
        'tp_fiscal_center': config.fiscal_center or OBRFiscalCenter.DGC,
        'tp_activity_sector': config.activity_sector or '',
        'tp_legal_form': config.legal_form or '',
        'payment_type': 1,
        'customer_name': record.customer_name,
        'customer_TIN': record.customer_tin,
        'customer_address': record.customer_address,
        'vat_customer_payer': '1' if record.vat_customer else '0',
        'cancelled_invoice_ref': record.cancelled_invoice_reference or '',
        'invoice_ref': record.invoice_reference or '',
        'cn_motif': record.credit_note_reason or '',
        'invoice_identifier': identifier,
        'invoice_items': items,
    }


@transaction.atomic
def send_invoice(record, user=None):
    record = EBMSInvoice.objects.select_for_update().get(pk=record.pk)
    if record.status in {SyncStatus.SENT, SyncStatus.CANCELLED, SyncStatus.NOT_REQUIRED}:
        raise ValidationError('Cette facture ne peut pas être envoyée dans son état actuel.')

    record = prepare_invoice(record.invoice, user)
    if record.validation_errors:
        raise ValidationError(record.validation_errors)

    config = get_configuration()
    if record.attempt_count >= config.max_attempts:
        raise ValidationError('Nombre maximal de tentatives atteint.')

    record.attempt_count += 1
    record.last_attempt = timezone.now()
    record.status = SyncStatus.PROCESSING
    record.save(update_fields=['attempt_count', 'last_attempt', 'status', 'updated_at'])

    try:
        client = OBRClient(config, user)
        response = client.post(
            OBREndpoints.ADD_INVOICE, record.request_payload,
            OBRSyncLog.Action.ADD_INVOICE, record.invoice_identifier,
        )
        result = response.get('result', {})
        if response.get('success') is False:
            raise OBRClientError(response.get('msg', 'Erreur OBR inconnue.'))
        record.response_payload = response
        record.status = SyncStatus.SENT
        record.error_message = ''
        record.obr_registered_number = result.get('invoice_registered_number', '')
        record.electronic_signature = response.get('electronic_signature', '')
        registered_date = result.get('invoice_registered_date', '')
        record.obr_registered_date = parse_datetime(registered_date) if registered_date else timezone.now()
        record.sent_at = timezone.now()
    except OBRClientError as exc:
        record.status = SyncStatus.FAILED
        record.error_message = str(exc)
        logger.error('Envoi facture OBR échoué : %s', exc)
    except Exception as exc:
        record.status = SyncStatus.FAILED
        record.error_message = f'Erreur inattendue : {exc}'
        logger.exception('Envoi facture OBR inattendu : %s', exc)

    record.save()
    return record


def repair_invoice(record, user=None):
    return prepare_invoice(record.invoice, user)


@transaction.atomic
def cancel_invoice(record, motif, user=None):
    if record.status != SyncStatus.SENT:
        raise ValidationError('Seule une facture déjà envoyée peut être annulée.')
    motif = (motif or '').strip()
    if not motif:
        raise ValidationError('Le motif d’annulation est obligatoire.')

    config = get_configuration()
    payload = {'invoice_identifier': record.invoice_identifier, 'cn_motif': motif}
    try:
        response = OBRClient(config, user).post(
            OBREndpoints.CANCEL_INVOICE, payload,
            OBRSyncLog.Action.CANCEL_INVOICE, record.invoice_identifier,
        )
    except OBRClientError:
        raise

    record.status = SyncStatus.CANCELLED
    record.cancelled_at = timezone.now()
    record.response_payload = response
    record.credit_note_reason = motif
    record.save(update_fields=[
        'status', 'cancelled_at', 'response_payload', 'credit_note_reason', 'updated_at',
    ])
    return record


def check_tin(tin, user=None):
    tin = (tin or '').strip()
    if not tin:
        raise ValidationError('Le NIF/TIN est obligatoire.')
    return OBRClient(get_configuration(), user).post(
        OBREndpoints.CHECK_TIN, {'tp_TIN': tin},
        OBRSyncLog.Action.CHECK_TIN, tin,
    )


def get_invoice(invoice_identifier, user=None):
    if not invoice_identifier:
        raise ValidationError('L’identifiant de facture est obligatoire.')
    return OBRClient(get_configuration(), user).post(
        OBREndpoints.GET_INVOICE,
        {'invoice_identifier': invoice_identifier},
        OBRSyncLog.Action.GET_INVOICE, invoice_identifier,
    )


def test_connection(user=None):
    client = OBRClient(get_configuration(), user)
    token = client._token()
    return {'success': bool(token), 'message': 'Connexion OBR réussie.' if token else 'Jeton absent.'}


def refresh_token(user=None):
    client = OBRClient(get_configuration(), user)
    client._clear_token()
    return {'success': bool(client._token())}


# ---------------------------------------------------------------------------
# Stock movements
# ---------------------------------------------------------------------------

MOVEMENT_MAP = {
    'PURCHASE': OBRMovementType.ENTRY_NORMAL,
    'SALE': OBRMovementType.EXIT_NORMAL,
    'CONSUMPTION': OBRMovementType.EXIT_NORMAL,
    'ADJUSTMENT': OBRMovementType.ENTRY_ADJUSTMENT,
    'TRANSFER_IN': OBRMovementType.ENTRY_TRANSFER,
    'TRANSFER_OUT': OBRMovementType.EXIT_TRANSFER,
    'RETURN': OBRMovementType.ENTRY_RETURN,
}


def _movement_type(movement):
    if movement.quantity < 0:
        return OBRMovementType.EXIT_NORMAL
    return MOVEMENT_MAP.get(movement.movement_type, OBRMovementType.ENTRY_OTHER)


@transaction.atomic
def prepare_stock_movement(movement, user=None):
    config = get_configuration()
    product = movement.product
    mapping = EBMSProductMapping.objects.filter(product=product).first()
    errors = []
    if mapping is None:
        errors.append(f'{product}: aucune classification eBMS configurée.')
    elif not mapping.ready:
        errors.append(f'{product}: classification eBMS incomplète.')

    if errors:
        status = SyncStatus.BLOCKED
    elif mapping and mapping.eligibility == EBMSProductMapping.Eligibility.EXCLUDED:
        status = SyncStatus.NOT_REQUIRED
    else:
        status = SyncStatus.PENDING

    record, _ = EBMSStockMovement.objects.update_or_create(
        stock_movement=movement,
        defaults={
            'movement_type': _movement_type(movement),
            'movement_date': movement.date,
            'description': f'{movement.get_movement_type_display()} — {movement.location}',
            'invoice_reference': movement.reference[:40],
            'status': status,
            'validation_errors': errors,
        },
    )

    if status == SyncStatus.PENDING:
        item_code = (mapping.item_code if mapping else '') or config.inventory_item_code
        designation = (
            (mapping.item_designation if mapping else '')
            or product.name
        )
        if not item_code:
            item_code = re.sub(r'[^A-Za-z0-9._-]+', '-', product.sku or product.name)[:30]
        record.request_payload = {
            'system_or_device_id': config.username or 'admin',
            'item_code': item_code,
            'item_designation': designation,
            'item_quantity': str(abs(movement.quantity)),
            'item_measurement_unit': (
                (mapping.measurement_unit if mapping else '')
                or config.default_measurement_unit
                or 'PCE'
            ),
            'item_cost_price': _decimal_string(getattr(product, 'unit_cost', 0)),
            'item_cost_price_currency': OBRCurrency.BIF,
            'item_movement_type': record.movement_type,
            'item_movement_invoice_ref': movement.reference or f'MOV-{movement.pk}',
            'item_movement_description': record.description,
            'item_movement_date': _format_datetime(movement.date),
        }
        record.save(update_fields=['request_payload', 'updated_at'])

    return record


@transaction.atomic
def send_stock_movement(record, user=None):
    record = EBMSStockMovement.objects.select_for_update().get(pk=record.pk)
    if record.validation_errors:
        raise ValidationError(record.validation_errors)
    if record.status in {SyncStatus.SENT, SyncStatus.NOT_REQUIRED}:
        raise ValidationError('Ce mouvement ne peut pas être envoyé.')

    config = get_configuration()
    if record.attempt_count >= config.max_attempts:
        raise ValidationError('Nombre maximal de tentatives atteint.')
    if not record.request_payload:
        record = prepare_stock_movement(record.stock_movement, user)

    record.attempt_count += 1
    record.last_attempt = timezone.now()
    record.status = SyncStatus.PROCESSING
    record.save(update_fields=['attempt_count', 'last_attempt', 'status', 'updated_at'])

    try:
        response = OBRClient(config, user).post(
            OBREndpoints.ADD_STOCK_MOVEMENT, record.request_payload,
            OBRSyncLog.Action.ADD_STOCK, str(record.stock_movement_id),
        )
        if response and response.get('success') is False:
            raise OBRClientError(response.get('msg', 'Erreur OBR inconnue.'))
        record.response_payload = response
        record.status = SyncStatus.SENT
        record.sent_at = timezone.now()
        record.error_message = ''
    except OBRClientError as exc:
        message = str(exc)
        if '409' in message or 'deja ete enregistre' in message:
            record.status = SyncStatus.SENT
            record.error_message = 'Déjà enregistré dans OBR (409).'
            record.response_payload = {'error': message}
        else:
            record.status = SyncStatus.FAILED
            record.error_message = message
    except Exception as exc:
        record.status = SyncStatus.FAILED
        record.error_message = f'Erreur inattendue : {exc}'

    record.save()
    return record
