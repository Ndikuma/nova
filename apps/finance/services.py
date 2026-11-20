from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Invoice, Payment


@transaction.atomic
def record_payment(*, invoice, amount, method, user, reference=''):
    try:
        amount = Payment._meta.get_field('amount').clean(amount, None)
    except ValidationError as exc:
        raise ValueError('Montant de paiement invalide.') from exc

    current = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if current.status not in Invoice.PAYABLE_STATUSES:
        raise ValueError('Seule une facture émise ou partiellement payée peut être encaissée.')
    if amount <= 0 or amount > current.balance:
        raise ValueError('Le montant doit être positif et ne peut pas dépasser le solde.')
    if not method.active:
        raise ValueError('Ce moyen de paiement est désactivé.')

    payment = Payment.objects.create(
        invoice=current, amount=amount, method=method, received_by=user, reference=reference,
    )
    current.paid_amount += amount
    current.status = 'PAID' if current.balance == 0 else 'PARTIAL'
    current.save(update_fields=['paid_amount', 'status'])

    invoice.paid_amount = current.paid_amount
    invoice.status = current.status
    return payment
