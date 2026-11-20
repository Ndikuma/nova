"""Compatibilité : profil d'établissement chargé depuis le modèle (base de données).

Les informations d'identité sont éditables via l'administration (CompanyProfile).
Ce module ré-exporte le modèle `apps.core.models.CompanyProfile` pour
préserver les imports existants (context processor, rapports, tests).
"""

from .models import CompanyProfile  # noqa: F401

