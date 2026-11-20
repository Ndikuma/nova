"""Synchronisation automatique des factures et mouvements de stock vers OBR."""

import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.core.models import CompanyProfile
from apps.finance.models import Invoice
from apps.inventory.models import StockMovement
from .models import EBMSConfiguration, SyncStatus
from .services import prepare_invoice, prepare_stock_movement, send_invoice, send_stock_movement

logger = logging.getLogger(__name__)

_INVOICES_IN_FLIGHT = set()
_MOVEMENTS_IN_FLIGHT = set()


def _company_feature_enabled():
    try:
        return CompanyProfile.load().obr_ebms_enabled
    except Exception:
        return False


def _enabled_config():
    if not _company_feature_enabled():
        return None
    return EBMSConfiguration.objects.filter(pk=1, enabled=True).first()


@receiver(post_save, sender=Invoice)
def auto_prepare_invoice(sender, instance, **kwargs):
    if instance.status not in {'ISSUED', 'PARTIAL', 'PAID'}:
        return
    config = _enabled_config()
    if not config:
        return
    if instance.pk in _INVOICES_IN_FLIGHT:
        return

    def run():
        _INVOICES_IN_FLIGHT.add(instance.pk)
        try:
            record = prepare_invoice(instance)
            if config.auto_submit_invoices and record.status == SyncStatus.PENDING:
                send_invoice(record)
        except Exception as exc:
            logger.warning('Préparation eBMS facture %s impossible : %s', instance.pk, exc)
        finally:
            _INVOICES_IN_FLIGHT.discard(instance.pk)

    transaction.on_commit(run)


@receiver(post_save, sender=StockMovement)
def auto_prepare_stock_movement(sender, instance, created, **kwargs):
    if not created:
        return
    config = _enabled_config()
    if not config:
        return
    if instance.pk in _MOVEMENTS_IN_FLIGHT:
        return

    def run():
        _MOVEMENTS_IN_FLIGHT.add(instance.pk)
        try:
            record = prepare_stock_movement(instance)
            if config.auto_submit_stock and record.status == SyncStatus.PENDING:
                send_stock_movement(record)
        except Exception as exc:
            logger.warning('Préparation eBMS stock %s impossible : %s', instance.pk, exc)
        finally:
            _MOVEMENTS_IN_FLIGHT.discard(instance.pk)

    transaction.on_commit(run)
