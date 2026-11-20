from django.db.models import Q
from django.utils import timezone

from apps.inventory.models import RecipeIngredient

from .models import MenuItem


def available_dishes():
    today = timezone.localdate()
    return MenuItem.objects.filter(available=True, menu__active=True).filter(
        Q(menu__available_from__isnull=True) | Q(menu__available_from__lte=today),
        Q(menu__available_until__isnull=True) | Q(menu__available_until__gte=today),
    ).order_by('category', 'name', 'pk')


def with_ingredients(items):
    items = list(items)
    recipe_ids = set()
    for item in items:
        names = (line.strip() for line in item.public_ingredients.splitlines())
        item.ingredient_names = list(dict.fromkeys(name for name in names if name))
        if not item.ingredient_names and item.recipe_id is not None:
            recipe_ids.add(item.recipe_id)

    ingredients = {}
    for recipe_id, name in RecipeIngredient.objects.filter(
        recipe_id__in=recipe_ids, recipe__active=True,
    ).order_by('product__name').values_list('recipe_id', 'product__name').distinct():
        ingredients.setdefault(recipe_id, []).append(name)
    for item in items:
        if not item.ingredient_names:
            item.ingredient_names = ingredients.get(item.recipe_id, [])
    return items
