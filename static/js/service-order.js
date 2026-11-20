const orderForm = document.querySelector('[data-waiter-order]');

if (orderForm) {
  const search = orderForm.querySelector('[data-item-search]');
  const selected = orderForm.querySelector('[data-show-selected]');
  const noResults = orderForm.querySelector('[data-no-results]');
  const summary = orderForm.querySelector('[data-order-summary]');
  const mobileReview = orderForm.querySelector('[data-mobile-review]');
  const review = orderForm.querySelector('[data-order-review]');
  const cartLines = review.querySelector('[data-cart-lines]');
  const emptyCart = review.querySelector('[data-cart-empty]');
  const cartLine = review.querySelector('[data-cart-line]');
  const totalOutput = review.querySelector('[data-order-total]');
  const groups = [...orderForm.querySelectorAll('[data-menu-group]')];
  const normalize = text => text.toLocaleLowerCase('fr').normalize('NFD').replace(/\p{Diacritic}/gu, '');
  const rows = [...orderForm.querySelectorAll('[data-menu-item]')].map(element => ({
    element,
    input: element.querySelector('[data-quantity]'),
    note: element.querySelector('.waiter-line-note'),
    buttons: [...element.querySelectorAll('[data-quantity-step]')],
    priceInCents: Math.round(Number(element.dataset.price) * 100),
    searchableText: normalize(element.dataset.search),
  }));
  const number = new Intl.NumberFormat('fr', { maximumFractionDigits: 2 });
  const currency = orderForm.dataset.currency;
  let submitting = false;

  function formatAmount(cents) {
    return [number.format(cents / 100), currency].filter(Boolean).join(' ');
  }

  function revealItem(event, row) {
    event.preventDefault();
    if (search) search.value = '';
    selected?.setAttribute('aria-pressed', 'false');
    update();
    row.input.focus();
  }

  function renderCart(entries, cents) {
    const lines = entries.map(([row, quantity]) => {
      const entry = cartLine.content.cloneNode(true);
      const link = entry.querySelector('[data-cart-edit]');
      link.href = '#' + row.element.id;
      link.textContent = `${number.format(quantity)} × ${row.element.dataset.itemName}`;
      link.addEventListener('click', event => revealItem(event, row));
      entry.querySelector('[data-cart-price]').textContent = row.element.dataset.orderable === 'true'
        ? formatAmount(quantity * row.priceInCents) : 'Indisponible';
      return entry;
    });
    cartLines.replaceChildren(...lines);
    cartLines.hidden = !lines.length;
    emptyCart.hidden = Boolean(lines.length);
    const total = formatAmount(cents);
    if (totalOutput.textContent !== total) totalOutput.textContent = total;
  }

  function update() {
    const words = normalize(search?.value.trim() || '').split(/\s+/);
    const onlySelected = selected?.getAttribute('aria-pressed') === 'true';
    let count = 0;
    let cents = 0;
    let hasResults = false;
    const entries = [];

    for (const row of rows) {
      const quantity = Number(row.input.value);
      if (row.input.validity.valid && quantity > 0) {
        count += quantity;
        if (row.element.dataset.orderable === 'true') cents += quantity * row.priceInCents;
        entries.push([row, quantity]);
      }
      row.element.classList.toggle('has-quantity', quantity > 0);
      if (row.note) row.note.hidden = quantity <= 0 && !row.note.querySelector('input').value;
      const matches = words.every(word => row.searchableText.includes(word));
      row.element.hidden = !matches || (onlySelected && quantity <= 0);
      hasResults ||= !row.element.hidden;
    }
    for (const group of groups) {
      group.hidden = !group.querySelector('[data-menu-item]:not([hidden])');
    }
    noResults.hidden = hasResults || rows.length === 0;
    summary.textContent = `${number.format(count)} article${count > 1 ? 's' : ''} · ${formatAmount(cents)}`;
    renderCart(entries, cents);
  }

  const customerModes = orderForm.querySelectorAll('[data-customer-mode]');
  const customerPanels = orderForm.querySelectorAll('[data-customer-panel]');

  function updateCustomerFields() {
    const mode = orderForm.querySelector('[data-customer-mode]:checked')?.value || 'walk_in';
    for (const panel of customerPanels) {
      const active = panel.dataset.customerPanel === mode;
      panel.hidden = !active;
      for (const field of panel.querySelectorAll('input, select')) field.disabled = !active;
    }
  }

  for (const radio of customerModes) radio.addEventListener('change', updateCustomerFields);

  for (const row of rows) {
    for (const button of row.buttons) {
      button.hidden = false;
      button.addEventListener('click', () => {
        const quantity = Number(row.input.value);
        const limit = Number(row.input.max) || 99;
        const next = Math.max(0, Math.min(limit, Math.trunc(quantity + Number(button.dataset.quantityStep))));
        row.input.value = next || '';
        if (!next && selected?.getAttribute('aria-pressed') === 'true') {
          selected.focus();
        }
        update();
      });
    }
    row.input.addEventListener('input', update);
  }

  if (search && selected) {
    orderForm.querySelector('[data-menu-tools]').hidden = false;
    search.addEventListener('input', update);
    selected.addEventListener('click', () => {
      selected.setAttribute('aria-pressed', selected.getAttribute('aria-pressed') !== 'true');
      update();
    });
    orderForm.addEventListener('invalid', event => {
      if (event.target.matches('[data-quantity]')) {
        search.value = '';
        selected.setAttribute('aria-pressed', 'false');
        update();
      }
    }, true);
  }
  orderForm.addEventListener('submit', event => {
    if (submitting) {
      event.preventDefault();
      return;
    }
    submitting = true;
  });
  window.addEventListener('pageshow', () => {
    submitting = false;
    updateCustomerFields();
    update();
  });

  review.hidden = false;
  mobileReview.hidden = false;
  if ('IntersectionObserver' in window) {
    const visibility = new IntersectionObserver(([entry]) => {
      mobileReview.classList.toggle('review-in-view', entry.isIntersecting);
    });
    visibility.observe(document.getElementById('order-review'));
  }
  orderForm.querySelector('[data-order-errors]')?.focus();
  updateCustomerFields();
  update();
}
