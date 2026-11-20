from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.obr_ebms.models import (
    EBMSConfiguration, EBMSInvoice, EBMSStockMovement, SyncStatus,
)
from apps.obr_ebms.services import send_invoice, send_stock_movement


class Command(BaseCommand):
    help = 'Relance les envois OBR eBMS en attente ou en échec.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        config = EBMSConfiguration.objects.filter(pk=1, enabled=True).first()
        if not config:
            self.stdout.write(self.style.WARNING('OBR eBMS désactivé ou non configuré.'))
            return

        retryable = Q(status__in=[SyncStatus.PENDING, SyncStatus.FAILED])
        sent_invoices = sent_stock = 0

        if config.auto_submit_invoices:
            for record in EBMSInvoice.objects.filter(
                retryable, attempt_count__lt=config.max_attempts,
            )[:options['limit']]:
                record = send_invoice(record)
                sent_invoices += record.status == SyncStatus.SENT

        if config.auto_submit_stock:
            for record in EBMSStockMovement.objects.filter(
                retryable, attempt_count__lt=config.max_attempts,
            )[:options['limit']]:
                record = send_stock_movement(record)
                sent_stock += record.status == SyncStatus.SENT

        self.stdout.write(self.style.SUCCESS(
            f'Factures envoyées : {sent_invoices} · mouvements envoyés : {sent_stock}'
        ))
