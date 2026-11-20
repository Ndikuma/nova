# NOVA Hospitality

Application de gestion hôtelière et de restauration basée sur **Django** (templates), SQLite et une interface de console par rôles : réception, cuisine, service/bar, caisse, inventaire, finance, rapports et vitrine publique.

## Démarrage rapide

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 manage.py migrate
python3 manage.py seed_demo
python3 manage.py runserver
```

- Application : http://127.0.0.1:8000/
- Connexion équipe : http://127.0.0.1:8000/login/

> `seed_demo` est idempotent et initialise les groupes, comptes et données de démonstration.

## Comptes de démonstration

| Rôle | Identifiant | Mot de passe |
|---|---|---|
| Super administrateur | `Superadmin` | `Super@Nova2026` |
| Gérant | `Owner` | `Owner@Nova2026` |
| Chef de cuisine | `Chef` | `Chef@Nova2026` |
| Réceptionniste | `Receptionist` | `Reception@Nova2026` |
| Serveur | `Waiter` | `Serveur@Nova2026` |
| Caissier | `Cashier` | `Caissier@Nova2026` |
| Barman | `Bartender` | `Barman@Nova2026` |

Modifiez ces comptes/mots de passe avant toute utilisation réelle.

## Fonctionnalités principales

- **Hôtel** : chambres, tarifs, réservations, demandes web, arrivées/départs, facturation séjour et ménage
- **Restaurant & bar** : tables, menus/boissons, commandes (prise en charge unifiée côté service), préparation et suivi
- **Caisse & finance** : facturation, encaissements (total/partiel) avec suivi des montants à encaisser/encaissés, dépenses, reçus/tickets
- **Bilan financier** : analyse par période (Hôtel/Restaurant/Bar, dépenses, solde net) pour Superadmin/Gérant
- **Inventaire** : produits, stocks, mouvements, fournisseurs, achats et recettes
- **Rapports & documents** : états filtrables (PDF/CSV), impressions facture/reçu/commande (dont tickets POS)
- **Administration** : espaces par rôle, console CRUD, journal d’audit, intégration OBR eBMS (activation selon établissement)
- **Site public** : vitrine (chambres, menu, bar) et demandes de réservation

## Documentation

- **Guide d’utilisation (par rôle)** : [`docs/GUIDE_UTILISATION.md`](docs/GUIDE_UTILISATION.md)
- Audit des flux : [`docs/WORKFLOW_AUDIT.md`](docs/WORKFLOW_AUDIT.md)

## Commandes utiles

```bash
python3 manage.py check
python3 manage.py test
python3 manage.py migrate
python3 manage.py seed_demo
```

### Réinitialisation (base vierge)

```bash
rm -f db.sqlite3
python3 manage.py migrate
python3 manage.py seed_demo
```
