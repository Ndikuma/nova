import time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.bar.models import BarOrder
from apps.finance.models import Invoice, Payment
from apps.restaurant.models import Order
from .documents import (
    REPORT_CATALOG, DocumentBrand, generate_report, invoice_totals,
    render_invoice_pdf, render_order_pdf, render_report_pdf, report_data, user_can_run,
)
from .models import GeneratedReport


def _catalog_for(user):
    result = {}
    for code, entry in REPORT_CATALOG.items():
        if user_can_run(user, code):
            result.setdefault(entry['category'], []).append((code, entry))
    return result.items()


@login_required
def report_center(request):
    today = timezone.localdate()
    return render(request, 'reports/center.html', {
        'report_groups': _catalog_for(request.user),
        'history': GeneratedReport.objects.select_related('created_by')[:20],
        'default_date_from': today.replace(day=1).isoformat(),
        'default_date_to': today.isoformat(),
    })


@login_required
@require_POST
def generate(request):
    code = request.POST.get('report_code', '')
    file_format = request.POST.get('file_format', 'pdf')
    params = {
        'date_from': request.POST.get('date_from', ''),
        'date_to': request.POST.get('date_to', ''),
    }
    try:
        run = generate_report(code, params, file_format, request.user)
    except (ValidationError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect('reports:center')
    messages.success(request, f'{run.report_name} généré avec succès.')
    return redirect('reports:download', pk=run.pk)


@login_required
def download(request, pk):
    run = get_object_or_404(GeneratedReport, pk=pk)
    if not (request.user.is_superuser or run.created_by_id == request.user.pk):
        raise Http404
    if run.status != GeneratedReport.Status.COMPLETED or not run.file:
        messages.error(request, 'Ce rapport n’est pas disponible.')
        return redirect('reports:center')
    inline = request.GET.get('inline') == '1' and run.file_format == 'pdf'
    return FileResponse(
        run.file.open('rb'), as_attachment=not inline,
        filename=run.file.name.rsplit('/', 1)[-1],
        content_type='application/pdf' if run.file_format == 'pdf' else 'text/csv',
    )


@login_required
def preview(request, code):
    if not user_can_run(request.user, code):
        raise PermissionDenied('Rapport non autorisé pour votre rôle.')
    try:
        title, headers, rows, start, end = report_data(code, request.GET)
    except ValidationError as exc:
        messages.error(request, str(exc))
        return redirect('reports:center')
    return render(request, 'print/report.html', {
        'brand': DocumentBrand.load(),
        'title': title,
        'headers': headers,
        'rows': rows,
        'start': start,
        'end': end,
        'generated_by': request.user,
        'generated_at': timezone.localtime(),
        'back_url': '/reports/',
        'code': code,
    })


@login_required
def preview_pdf(request, code):
    if not user_can_run(request.user, code):
        raise PermissionDenied('Rapport non autorisé pour votre rôle.')
    try:
        title, headers, rows, start, end = report_data(code, request.GET)
    except ValidationError as exc:
        messages.error(request, str(exc))
        return redirect('reports:center')
    subtitle = f'Période du {start:%d/%m/%Y} au {end:%d/%m/%Y} · {len(rows)} ligne(s)'
    content = render_report_pdf(title, headers, rows, DocumentBrand.load(), subtitle, str(request.user))
    return FileResponse(
        _bytes(content), content_type='application/pdf', as_attachment=False,
        filename=f'{code}-{start}-{end}.pdf',
    )


def _invoice_lines(invoice):
    return [
        {'item': item, 'line_total': item.quantity * item.unit_price}
        for item in invoice.items.all()
    ]


@login_required
def invoice_print(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related('customer').prefetch_related('items', 'payments__method'),
        pk=pk,
    )
    pos_mode = request.GET.get('ticket') in ('1', 'pos', 'true') or request.GET.get('format') == 'pos'
    return render(request, 'print/invoice.html', {
        'brand': DocumentBrand.load(),
        'invoice': invoice,
        'lines': _invoice_lines(invoice),
        'totals': invoice_totals(invoice),
        'payments': invoice.payments.select_related('method', 'received_by').order_by('paid_at'),
        'generated_by': request.user,
        'generated_at': timezone.localtime(),
        'back_url': request.META.get('HTTP_REFERER') or '/reports/',
        'pos_mode': pos_mode,
    })


@login_required
def invoice_pdf(request, pk):
    invoice = get_object_or_404(Invoice.objects.select_related('customer'), pk=pk)
    content = render_invoice_pdf(invoice)
    return FileResponse(
        _bytes(content), content_type='application/pdf', as_attachment=False,
        filename=f'facture-{invoice.number}.pdf',
    )


@login_required
def receipt_print(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related(
            'invoice', 'invoice__customer', 'method', 'received_by',
        ).prefetch_related('invoice__items', 'invoice__payments'), pk=pk,
    )
    pos_mode = request.GET.get('ticket') in ('1', 'pos', 'true') or request.GET.get('format') == 'pos'
    return render(request, 'print/receipt.html', {
        'brand': DocumentBrand.load(),
        'payment': payment,
        'invoice': payment.invoice,
        'lines': _invoice_lines(payment.invoice),
        'totals': invoice_totals(payment.invoice),
        'generated_by': request.user,
        'generated_at': timezone.localtime(),
        'back_url': request.META.get('HTTP_REFERER') or '/reports/',
        'pos_mode': pos_mode,
    })


@login_required
def receipt_pdf(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related(
            'invoice', 'invoice__customer', 'method', 'received_by',
        ), pk=pk,
    )
    content = render_invoice_pdf(payment.invoice, receipt=payment)
    return FileResponse(
        _bytes(content), content_type='application/pdf', as_attachment=False,
        filename=f'recu-{payment.pk}.pdf',
    )


def _order_document(request, kind, pk):
    if kind == 'bar':
        model, prefetch, bar = BarOrder, 'items__drink', True
    elif kind == 'restaurant':
        model, prefetch, bar = Order, 'items__menu_item', False
    else:
        raise Http404
    order = get_object_or_404(
        model.objects.select_related('customer', 'table', 'created_by').prefetch_related(prefetch),
        pk=pk,
    )
    from apps.workspaces.services import find_bar_invoice, find_order_invoice
    invoice = find_bar_invoice(order) if bar else find_order_invoice(order)
    lines = []
    for item in order.items.all():
        product = item.drink if bar else item.menu_item
        lines.append({
            'name': product.name,
            'quantity': item.quantity,
            'unit_price': item.unit_price,
            'subtotal': item.subtotal,
            'notes': getattr(item, 'notes', '') or '',
        })
    pos_mode = request.GET.get('ticket') in ('1', 'pos', 'true') or request.GET.get('format') == 'pos'
    return {
        'brand': DocumentBrand.load(),
        'order': order,
        'kind': kind,
        'bar_order': bar,
        'lines': lines,
        'invoice': invoice,
        'generated_by': request.user,
        'generated_at': timezone.localtime(),
        'back_url': request.META.get('HTTP_REFERER') or '/',
        'pos_mode': pos_mode,
    }


@login_required
def order_print(request, kind, pk):
    return render(request, 'print/order.html', _order_document(request, kind, pk))


@login_required
def order_pdf(request, kind, pk):
    context = _order_document(request, kind, pk)
    content = render_order_pdf(context['order'], kind)
    prefix = 'commande-bar' if kind == 'bar' else 'commande'
    return FileResponse(
        _bytes(content), content_type='application/pdf', as_attachment=False,
        filename=f'{prefix}-{context["order"].pk}.pdf',
    )


def _bytes(content):
    from io import BytesIO
    return BytesIO(content)
