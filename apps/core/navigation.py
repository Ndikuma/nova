"""Central navigation configuration for the NOVA console.

Keeps the module/model registry, the French labels shown in the UI and the
icon names used by ``templates/partials/sidebar_icon.html`` in one place so
the sidebar, dashboard and module pages never drift apart.
"""

MODULES = {
    'hotel': {
        'title': 'Hôtel',
        'icon': 'building',
        'description': 'Chambres, réservations, séjours et ménage.',
        'models': ['BookingRequest', 'RoomType', 'Room', 'RoomRate', 'Reservation', 'Stay', 'HousekeepingTask'],
    },
    'restaurant': {
        'title': 'Restaurant',
        'icon': 'restaurant',
        'description': 'Tables, menus, commandes et réservations.',
        'models': ['Table', 'Menu', 'MenuItem', 'Order', 'RestaurantReservation'],
    },
    'bar': {
        'title': 'Bar',
        'icon': 'bar',
        'description': 'Boissons, tables et commandes du bar.',
        'models': ['DrinkCategory', 'Drink', 'BarTable', 'BarOrder'],
    },
    'inventory': {
        'title': 'Inventaire',
        'icon': 'inventory',
        'description': 'Produits, stocks, fournisseurs et recettes.',
        'models': ['UnitOfMeasure', 'ProductCategory', 'Product', 'StockLocation', 'Stock',
                   'StockMovement', 'Supplier', 'PurchaseOrder', 'Recipe'],
    },
    'finance': {
        'title': 'Finance',
        'icon': 'payments',
        'description': 'Factures, paiements, dépenses et caisses.',
        'models': ['Invoice', 'PaymentMethod', 'Payment', 'ExpenseCategory',
                   'Expense', 'Refund'],
    },
    'core': {
        'title': 'Clients & équipe',
        'icon': 'team',
        'description': 'Clients, membres de l’équipe et journal d’audit.',
        'models': ['Customer', 'User', 'AuditLog'],
    },
}

MODEL_LABELS = {
    # Hôtel
    'BookingRequest': 'Demandes de réservation web',
    'RoomType': 'Types de chambre',
    'Room': 'Chambres',
    'RoomRate': 'Tarifs',
    'Reservation': 'Réservations',
    'Stay': 'Séjours',
    'HousekeepingTask': 'Tâches de ménage',
    # Restaurant
    'Table': 'Tables',
    'Menu': 'Menus',
    'MenuItem': 'Plats & boissons',
    'Order': 'Commandes',
    'OrderItem': 'Lignes de commande',
    'RestaurantReservation': 'Réservations restaurant',
    # Bar
    'DrinkCategory': 'Catégories de boissons',
    'Drink': 'Boissons',
    'BarTable': 'Tables du bar',
    'BarOrder': 'Commandes bar',
    'BarOrderItem': 'Lignes de commande bar',
    # Inventaire
    'UnitOfMeasure': 'Unités de mesure',
    'ProductCategory': 'Catégories de produits',
    'Product': 'Produits',
    'StockLocation': 'Emplacements de stock',
    'Stock': 'Stocks',
    'StockMovement': 'Mouvements de stock',
    'Supplier': 'Fournisseurs',
    'PurchaseOrder': 'Bons de commande',
    'PurchaseOrderItem': 'Lignes de bon de commande',
    'Recipe': 'Recettes',
    'RecipeIngredient': 'Ingrédients',
    # Finance
    'Invoice': 'Factures',
    'InvoiceItem': 'Lignes de facture',
    'PaymentMethod': 'Moyens de paiement',
    'Payment': 'Paiements',
    'ExpenseCategory': 'Catégories de dépense',
    'Expense': 'Dépenses',
    'Refund': 'Remboursements',
    # Core
    'Customer': 'Clients',
    'User': 'Équipe',
    'AuditLog': 'Journal d’audit',
}

FIELD_LABELS = {
    'name': 'Nom', 'description': 'Description', 'max_capacity': 'Capacité maximale',
    'amenities': 'Équipements', 'active': 'Actif', 'number': 'Numéro', 'floor': 'Étage',
    'room_type': 'Type de chambre', 'operational_status': 'État opérationnel',
    'price': 'Prix', 'start_date': 'Date de début', 'end_date': 'Date de fin',
    'customer': 'Client', 'room': 'Chambre', 'check_in': 'Arrivée', 'check_out': 'Départ',
    'adults': 'Adultes', 'children': 'Enfants', 'status': 'Statut',
    'estimated_total': 'Total estimé', 'contact_information': 'Contact', 'notes': 'Notes',
    'guest_name': 'Nom du voyageur', 'contact_method': 'Moyen de contact', 'handled_at': 'Traitée le',
    'created_by': 'Créé par', 'created_at': 'Créé le', 'reservation': 'Réservation',
    'actual_check_in': 'Arrivée réelle', 'actual_check_out': 'Départ réel',
    'responsible_receptionist': 'Réceptionniste responsable', 'assigned_to': 'Assigné à',
    'task_type': 'Type de tâche', 'scheduled_date': 'Date planifiée',
    'completion_date': 'Date de fin', 'capacity': 'Capacité', 'section': 'Section',
    'menu': 'Menu', 'menu_item': 'Article', 'category': 'Catégorie',
    'selling_price': 'Prix de vente', 'image': 'Image', 'available': 'Disponible',
    'recipe_id': 'Recette', 'source': 'Source', 'table': 'Table',
    'total_amount': 'Montant total', 'unit_price': 'Prix unitaire', 'quantity': 'Quantité',
    'reservation_at': 'Date de réservation', 'guests': 'Convives', 'drink': 'Boisson',
    'contact': 'Contact', 'email': 'E-mail', 'phone': 'Téléphone', 'address': 'Adresse',
    'tax_information': 'Informations fiscales', 'tax_id': 'N° fiscal',
    'supplier': 'Fournisseur', 'order_date': 'Date de commande',
    'expected_delivery': 'Livraison prévue', 'purchase_order': 'Bon de commande',
    'unit_cost': 'Coût unitaire', 'instructions': 'Instructions', 'unit': 'Unité',
    'product': 'Produit', 'minimum_stock': 'Stock minimum', 'sku': 'Référence',
    'location': 'Emplacement', 'movement_type': 'Type de mouvement',
    'reference': 'Référence', 'date': 'Date', 'responsible_user': 'Responsable',
    'issued_at': 'Émise le', 'paid_amount': 'Montant payé', 'invoice': 'Facture',
    'tax': 'Taxe', 'source_service': 'Service source',
    'source_reference': 'Référence source', 'method': 'Moyen de paiement',
    'paid_at': 'Payé le', 'received_by': 'Reçu par', 'amount': 'Montant',
    'payment_method': 'Moyen de paiement', 'is_cash': 'Paiement en espèces',
    'payment': 'Paiement', 'reason': 'Motif', 'action': 'Action',
    'object_type': 'Type d’objet', 'object_id': 'Identifiant d’objet',
    'timestamp': 'Horodatage', 'details': 'Détails', 'username': 'Identifiant',
    'first_name': 'Prénom', 'last_name': 'Nom', 'employee_id': 'Matricule',
    'job_title': 'Poste', 'avatar': 'Photo', 'is_active': 'Compte actif',
    'is_staff': 'Accès admin', 'is_superuser': 'Super administrateur',
    'last_login': 'Dernière connexion', 'date_joined': 'Inscription',
    'category_id': 'Catégorie', 'unit_id': 'Unité', 'product_id': 'Produit',
    'ingredient': 'Ingrédient', 'ingredients': 'Ingrédients',
}

ROLE_MODULES = {
    'Superadmin': None,
    'Owner': None,
    'Chef': ['restaurant', 'inventory', 'core'],
    'Receptionist': ['hotel', 'restaurant', 'core'],
    'Waiter': ['restaurant', 'bar', 'core'],
    'Bartender': ['bar', 'core'],
    'Cashier': ['finance', 'core'],
}

ROLE_LABELS = {
    'Superadmin': 'Superadmin',
    'Owner': 'Gérant',
    'Chef': 'Chef de cuisine',
    'Receptionist': 'Réceptionniste',
    'Waiter': 'Serveur',
    'Cashier': 'Caissier',
    'Bartender': 'Barman',
}

MODEL_ICONS = {
    'BookingRequest': 'reservations', 'RoomType': 'roomtype', 'Room': 'bed', 'RoomRate': 'payments', 'Reservation': 'reservations',
    'Stay': 'frontdesk', 'HousekeepingTask': 'housekeeping',
    'Table': 'table', 'Menu': 'menu', 'MenuItem': 'products', 'Order': 'orders',
    'OrderItem': 'orders', 'RestaurantReservation': 'reservations',
    'DrinkCategory': 'menu', 'Drink': 'products', 'BarTable': 'table', 'BarOrder': 'orders',
    'BarOrderItem': 'orders',
    'UnitOfMeasure': 'inventory', 'ProductCategory': 'inventory', 'Product': 'products',
    'StockLocation': 'shops', 'Stock': 'inventory', 'StockMovement': 'inventory',
    'Supplier': 'team', 'PurchaseOrder': 'orders', 'PurchaseOrderItem': 'orders',
    'Recipe': 'menu', 'RecipeIngredient': 'products',
    'Invoice': 'invoices', 'InvoiceItem': 'invoices', 'PaymentMethod': 'payments',
    'Payment': 'payments', 'ExpenseCategory': 'payments', 'Expense': 'payments',
    'Refund': 'payments',
    'Customer': 'guests', 'User': 'team', 'AuditLog': 'audit',
}


def model_label(name):
    """Human label for a model class name."""
    if name in MODEL_LABELS:
        return MODEL_LABELS[name]
    return ''.join([' ' + c.lower() if c.isupper() else c for c in name]).strip().capitalize()


def model_icon(name):
    return MODEL_ICONS.get(name, 'dashboard')


def field_label(name, fallback=None):
    """French label for a model field, with a readable fallback."""
    if name in FIELD_LABELS:
        return FIELD_LABELS[name]
    if fallback:
        return str(fallback)
    return name.replace('_', ' ').capitalize()


def user_roles(user):
    if not getattr(user, 'is_authenticated', False):
        return []
    return [group.name for group in user.groups.all()]


def accessible_modules(user=None):
    """Modules visible to a user based on their role groups.

    Superusers and users without any explicit group keep full access so the
    demo/setup experience never locks anyone out by accident.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return list(MODULES)
    if getattr(user, 'is_superuser', False):
        return list(MODULES)
    roles = user_roles(user)
    if not roles:
        return list(MODULES)
    allowed = []
    for role in roles:
        if role in ROLE_MODULES and ROLE_MODULES[role] is None:
            return list(MODULES)
        for module in ROLE_MODULES.get(role, []):
            if module in MODULES and module not in allowed:
                allowed.append(module)
    return allowed


def user_can_access_module(user, module):
    return module in accessible_modules(user)


def user_role_label(user):
    if not getattr(user, 'is_authenticated', False):
        return ''
    if getattr(user, 'is_superuser', False):
        return 'Super administrateur'
    roles = user_roles(user)
    return ' · '.join(ROLE_LABELS.get(role, role) for role in roles) if roles else 'Équipe'


def entity_slug(name):
    return name.lower()


def build_nav(user=None):
    """Return the sidebar sections consumed by ``templates/base.html``."""
    allowed = set(accessible_modules(user))
    sections = []
    for module, cfg in MODULES.items():
        if module not in allowed:
            continue
        items = [
            {
                'label': model_label(name),
                'url': f'/module/{module}/{entity_slug(name)}/',
                'icon': model_icon(name),
            }
            for name in cfg['models']
        ]
        sections.append({
            'key': module,
            'label': cfg['title'],
            'icon': cfg['icon'],
            'url': f'/module/{module}/',
            'items': items,
        })
    return sections


def module_cards(module, counts):
    cfg = MODULES[module]
    cards = []
    for name in cfg['models']:
        cards.append({
            'name': name,
            'label': model_label(name),
            'icon': model_icon(name),
            'count': counts.get(name, 0),
            'url': f'/module/{module}/{entity_slug(name)}/',
            'create_url': f'/module/{module}/{entity_slug(name)}/new/',
        })
    return cards


WORKSPACE_ENTRIES = {
    'Superadmin': {
        'key': 'superadmin',
        'label': 'Administration système',
        'description': 'Supervision globale, utilisateurs et journal d’audit.',
        'url': '/workspace/superadmin/',
        'icon': 'settings',
    },
    'Owner': {
        'key': 'owner',
        'label': 'Gérance · hôtel & restaurant',
        'description': 'Pilotage consolidé et contrôle des opérations des deux activités.',
        'url': '/workspace/owner/',
        'icon': 'analytics',
    },
    'Chef': {
        'key': 'kitchen',
        'label': 'Cuisine · KDS',
        'description': 'Commandes du restaurant, production et stocks cuisine.',
        'url': '/workspace/kitchen/',
        'icon': 'restaurant',
    },
    'Receptionist': {
        'key': 'reception',
        'label': 'Réception',
        'description': 'Réservations, arrivées, départs et ménage.',
        'url': '/workspace/reception/',
        'icon': 'frontdesk',
    },
    'Waiter': {
        'key': 'service',
        'label': 'Service salle & bar',
        'description': 'Tables et commandes du restaurant et du bar, en un seul espace.',
        'url': '/workspace/service/',
        'icon': 'table',
    },
    'Cashier': {
        'key': 'cashier',
        'label': 'Caisse',
        'description': 'Encaissements, factures et montants à suivre.',
        'url': '/workspace/cashier/',
        'icon': 'payments',
    },
    'Bartender': {
        'key': 'bar',
        'label': 'Bar · service',
        'description': 'Comptoir, boissons et commandes du bar.',
        'url': '/workspace/bar/',
        'icon': 'bar',
    },
}

_WORKSPACE_PRIORITY = ('Superadmin', 'Owner', 'Chef', 'Receptionist', 'Waiter', 'Cashier', 'Bartender')


def primary_workspace(user=None):
    """Return the workspace entry matching the user's primary role."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return None
    if getattr(user, 'is_superuser', False):
        return WORKSPACE_ENTRIES['Superadmin']
    roles = set(user_roles(user))
    for role in _WORKSPACE_PRIORITY:
        if role in roles:
            return WORKSPACE_ENTRIES[role]
    return None
