from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.models import CompanyProfile
from apps.finance.models import Invoice
from apps.inventory.models import Product, StockMovement
from .forms import (
    CancelInvoiceForm, EBMSConfigurationForm, EBMSProductMappingForm, TINCheckForm,
)
from .models import (
    EBMSConfiguration, EBMSInvoice, EBMSProductMapping, EBMSStockMovement,
    OBRSyncLog, SyncStatus,
)
from .services import (
    cancel_invoice, check_tin, prepare_invoice, prepare_stock_movement,
    refresh_token, send_invoice, send_stock_movement, test_connection,
    OBRClientError,
)

READ_ROLES = {'Superadmin', 'Owner', 'Cashier', 'Chef'}
WRITE_ROLES = {'Superadmin', 'Owner'}


def _groups(user):
    return set(user.groups.values_list('name', flat=True))


def _has_role(user, roles):
    return user.is_superuser or bool(_groups(user).intersection(roles))


def _company_feature_enabled():
    try:
        return CompanyProfile.load().obr_ebms_enabled
    except Exception:
        return False


def ebms_access(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            if not _company_feature_enabled():
                raise PermissionDenied("Le module OBR eBMS n’est pas activé pour cet établissement.")
            if not _has_role(request.user, set(roles)):
                raise PermissionDenied('Accès OBR eBMS non autorisé pour votre rôle.')
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


def _config():
    return EBMSConfiguration.load()


@ebms_access(*READ_ROLES)
def dashboard(request):
    config = _config()
    invoice_counts = dict(
        EBMSInvoice.objects.values_list('status').annotate(total=Count('id'))
    )
    movement_counts = dict(
        EBMSStockMovement.objects.values_list('status').annotate(total=Count('id'))
    )
    products = Product.objects.filter(active=True)
    mapped = EBMSProductMapping.objects.filter(product__active=True)
    ready_count = sum(1 for mapping in mapped.select_related('product') if mapping.ready)
    tax_collected = (
        Invoice.objects.filter(status__in=['ISSUED', 'PARTIAL', 'PAID'])
        .aggregate(total=Sum('total_amount'))['total'] or 0
    )

    return render(request, 'obr_ebms/dashboard.html', {
        'config': config,
        'company_profile': CompanyProfile.load(),
        'can_configure': _has_role(request.user, WRITE_ROLES),
        'invoice_counts': invoice_counts,
        'movement_counts': movement_counts,
        'products_total': products.count(),
        'mapped_count': mapped.count(),
        'ready_count': ready_count,
        'products_to_review': max(products.count() - ready_count, 0),
        'pending_invoices': invoice_counts.get(SyncStatus.PENDING, 0),
        'failed_invoices': invoice_counts.get(SyncStatus.FAILED, 0),
        'pending_stock': movement_counts.get(SyncStatus.PENDING, 0),
        'failed_stock': movement_counts.get(SyncStatus.FAILED, 0),
        'tax_collected': tax_collected,
        'recent_invoices': EBMSInvoice.objects.select_related('invoice').order_by('-created_at')[:8],
        'recent_logs': OBRSyncLog.objects.select_related('performed_by')[:8],
    })


@ebms_access(*WRITE_ROLES)
def configuration(request):
    config = _config()
    form = EBMSConfigurationForm(request.POST or None, instance=config)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Configuration OBR eBMS enregistrée.')
        return redirect('obr_ebms:dashboard')
    return render(request, 'obr_ebms/configuration.html', {
        'form': form, 'config': config, 'company_profile': CompanyProfile.load(),
    })


@ebms_access(*READ_ROLES)
def products(request):
    query = request.GET.get('q', '').strip()
    eligibility = request.GET.get('eligibility', '').strip()
    queryset = Product.objects.filter(active=True).select_related('category')
    if query:
        queryset = queryset.filter(Q(name__icontains=query) | Q(sku__icontains=query))
    mappings = {mapping.product_id: mapping for mapping in EBMSProductMapping.objects.all()}
    rows = []
    for product in queryset.order_by('name'):
        mapping = mappings.get(product.pk)
        if eligibility and (not mapping or mapping.eligibility != eligibility):
            continue
        rows.append({'product': product, 'mapping': mapping})
    return render(request, 'obr_ebms/products.html', {
        'rows': rows,
        'query': query,
        'eligibility': eligibility,
        'eligibility_choices': EBMSProductMapping.Eligibility.choices,
    })


@ebms_access(*WRITE_ROLES)
def product_mapping(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    mapping = EBMSProductMapping.objects.filter(product=product).first()
    form = EBMSProductMappingForm(request.POST or None, instance=mapping)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        obj.product = product
        form.save(user=request.user)
        messages.success(request, f'Classification eBMS de {product} enregistrée.')
        return redirect('obr_ebms:products')
    return render(request, 'obr_ebms/product_mapping.html', {
        'form': form, 'product': product, 'mapping': mapping,
    })


@ebms_access(*READ_ROLES)
def invoices(request):
    status = request.GET.get('status', '').strip()
    query = request.GET.get('q', '').strip()
    queryset = EBMSInvoice.objects.select_related('invoice', 'invoice__customer')
    if status:
        queryset = queryset.filter(status=status)
    if query:
        queryset = queryset.filter(
            Q(invoice_number__icontains=query)
            | Q(invoice_identifier__icontains=query)
            | Q(customer_name__icontains=query)
        )
    return render(request, 'obr_ebms/invoices.html', {
        'invoices': queryset.order_by('-created_at'),
        'status_filter': status,
        'query': query,
        'status_choices': SyncStatus.choices,
    })


@ebms_access(*READ_ROLES)
def invoice_detail(request, pk):
    record = get_object_or_404(
        EBMSInvoice.objects.select_related('invoice', 'invoice__customer'), pk=pk,
    )
    return render(request, 'obr_ebms/invoice_detail.html', {
        'record': record,
        'cancel_form': CancelInvoiceForm(),
        'can_write': _has_role(request.user, WRITE_ROLES),
    })


@ebms_access(*WRITE_ROLES)
@require_POST
def invoice_action(request, pk, action):
    record = get_object_or_404(EBMSInvoice, pk=pk)
    try:
        if action == 'prepare':
            prepare_invoice(record.invoice, request.user)
            messages.success(request, 'Facture préparée pour OBR eBMS.')
        elif action == 'send':
            send_invoice(record, request.user)
            messages.success(request, 'Facture transmise à OBR.')
        elif action == 'cancel':
            form = CancelInvoiceForm(request.POST)
            if not form.is_valid():
                messages.error(request, 'Indiquez un motif d’annulation.')
                return redirect('obr_ebms:invoice_detail', pk=pk)
            cancel_invoice(record, form.cleaned_data['motif'], request.user)
            messages.success(request, 'Facture annulée auprès d’OBR.')
        elif action == 'repair':
            prepare_invoice(record.invoice, request.user)
            messages.success(request, 'Payload de facture régénéré.')
        else:
            messages.error(request, 'Action inconnue.')
    except (ValidationError, ValueError, OBRClientError) as exc:
        messages.error(request, str(exc))
    return redirect('obr_ebms:invoice_detail', pk=pk)


@ebms_access(*READ_ROLES)
def stock_movements(request):
    status = request.GET.get('status', '').strip()
    queryset = EBMSStockMovement.objects.select_related(
        'stock_movement', 'stock_movement__product', 'stock_movement__location',
    )
    if status:
        queryset = queryset.filter(status=status)
    return render(request, 'obr_ebms/stock.html', {
        'movements': queryset.order_by('-created_at'),
        'status_filter': status,
        'status_choices': SyncStatus.choices,
    })


@ebms_access(*READ_ROLES)
def stock_movement_detail(request, pk):
    record = get_object_or_404(
        EBMSStockMovement.objects.select_related('stock_movement__product'), pk=pk,
    )
    return render(request, 'obr_ebms/stock_detail.html', {
        'record': record,
        'can_write': _has_role(request.user, WRITE_ROLES),
    })


@ebms_access(*WRITE_ROLES)
@require_POST
def stock_action(request, pk, action):
    record = get_object_or_404(EBMSStockMovement, pk=pk)
    try:
        if action == 'prepare':
            prepare_stock_movement(record.stock_movement, request.user)
            messages.success(request, 'Mouvement préparé pour OBR eBMS.')
        elif action == 'send':
            send_stock_movement(record, request.user)
            messages.success(request, 'Mouvement transmis à OBR.')
        else:
            messages.error(request, 'Action inconnue.')
    except (ValidationError, ValueError, OBRClientError) as exc:
        messages.error(request, str(exc))
    return redirect('obr_ebms:stock_detail', pk=pk)


@ebms_access(*READ_ROLES)
def logs(request):
    return render(request, 'obr_ebms/logs.html', {
        'logs': OBRSyncLog.objects.select_related('performed_by')[:200],
    })


@ebms_access(*READ_ROLES)
def tin_check(request):
    result = None
    error = ''
    form = TINCheckForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            result = check_tin(form.cleaned_data['tin'], request.user)
        except (ValidationError, ValueError, OBRClientError) as exc:
            error = str(exc)
    return render(request, 'obr_ebms/tin_check.html', {
        'form': form, 'result': result, 'error': error,
    })


@ebms_access(*WRITE_ROLES)
@require_POST
def connection(request, action):
    try:
        if action == 'test':
            result = test_connection(request.user)
        else:
            result = refresh_token(request.user)
        if result.get('success'):
            messages.success(request, result.get('message', 'Opération réussie.'))
        else:
            messages.warning(request, result.get('message', 'Opération incomplète.'))
    except OBRClientError as exc:
        messages.error(request, str(exc))
    return redirect('obr_ebms:dashboard')
