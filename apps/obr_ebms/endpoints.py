"""Points d’entrée de l’API OBR eBMS (documentation OBR v0.7)."""


class OBREndpoints:
    LOGIN = 'login/'
    ADD_INVOICE = 'addInvoice/'
    GET_INVOICE = 'getInvoice/'
    CANCEL_INVOICE = 'cancelInvoice/'
    ADD_STOCK_MOVEMENT = 'AddStockMovement/'
    ADD_STOCK_MOVEMENT_IMPORTERS = 'AddStockMovementImporters/'
    GET_DMC_ITEMS = 'getDmcItems'
    CHECK_TIN = 'checkTIN/'


class OBRMovementType:
    ENTRY_NORMAL = 'EN'
    ENTRY_RETURN = 'ER'
    ENTRY_INVENTORY = 'EI'
    ENTRY_ADJUSTMENT = 'EAJ'
    ENTRY_TRANSFER = 'ET'
    ENTRY_OTHER = 'EAU'
    EXIT_NORMAL = 'SN'
    EXIT_LOSS = 'SP'
    EXIT_THEFT = 'SV'
    EXIT_OBSOLETE = 'SD'
    EXIT_DAMAGED = 'SC'
    EXIT_ADJUSTMENT = 'SAJ'
    EXIT_TRANSFER = 'ST'
    EXIT_OTHER = 'SAU'


class OBRCurrency:
    BIF = 'BIF'
    USD = 'USD'
    EUR = 'EUR'


class OBRInvoiceType:
    NORMAL = 'FN'
    CREDIT_NOTE = 'FA'
    DEPOSIT_REFUND = 'RC'
    OFF_INVOICE_DISCOUNT = 'RHF'


class OBRTaxpayerType:
    INDIVIDUAL = '1'
    CORPORATE = '2'


class OBRFiscalCenter:
    DGC = 'DGC'


def get_endpoint_url(base_url, endpoint):
    if not base_url.endswith('/'):
        base_url += '/'
    return base_url + endpoint.lstrip('/')
