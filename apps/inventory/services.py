from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Stock, StockMovement


OUTGOING_MOVEMENTS = {'SALE', 'CONSUMPTION', 'TRANSFER_OUT'}


@transaction.atomic
def move_stock(*, product, location, quantity, movement_type, user, reference=''):
    if movement_type not in dict(StockMovement.TYPES):
        raise ValueError('Type de mouvement invalide.')
    try:
        quantity = StockMovement._meta.get_field('quantity').clean(quantity, None)
    except ValidationError as exc:
        raise ValueError('Quantité de stock invalide.') from exc

    if quantity == 0 or (quantity < 0 and movement_type != 'ADJUSTMENT'):
        raise ValueError('Saisissez une quantité positive. Un ajustement peut être négatif.')

    stock, _ = Stock.objects.select_for_update().get_or_create(product=product, location=location)
    delta = -quantity if movement_type in OUTGOING_MOVEMENTS else quantity
    new_quantity = stock.quantity + delta
    if new_quantity < 0:
        raise ValueError('Stock insuffisant pour cette opération.')
    try:
        Stock._meta.get_field('quantity').run_validators(new_quantity)
    except ValidationError as exc:
        raise ValueError('Le stock résultant dépasse la quantité maximale.') from exc

    stock.quantity = new_quantity
    stock.save(update_fields=['quantity'])
    return StockMovement.objects.create(
        product=product, location=location, movement_type=movement_type, quantity=quantity,
        reference=reference, responsible_user=user,
    )
