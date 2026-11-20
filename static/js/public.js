const stayForm = document.querySelector('[data-stay-search]');

if (stayForm) {
  const arrival = stayForm.elements.check_in;
  const departure = stayForm.elements.check_out;

  function setDepartureMinimum(updateDate) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(arrival.value)) return;
    const nextDay = new Date(`${arrival.value}T00:00:00Z`);
    if (!Number.isFinite(nextDay.getTime())) return;
    nextDay.setUTCDate(nextDay.getUTCDate() + 1);
    const minimum = nextDay.toISOString().split('T')[0];
    if (minimum.length !== 10) return;
    departure.min = minimum;
    if (updateDate && (!departure.value || departure.value < minimum)) {
      departure.value = minimum;
    }
  }

  setDepartureMinimum(false);
  arrival.addEventListener('change', () => setDepartureMinimum(true));
}

const catalog = document.querySelector('[data-catalog]');
const menuSearch = catalog?.querySelector('[data-catalog-search]');

if (menuSearch) {
  const input = menuSearch.querySelector('input');
  const noResults = catalog.querySelector('[data-no-menu-results]');
  const categoryLinks = new Map([...catalog.querySelectorAll('.pub-category-links a')].map(link => [link.hash, link]));
  const normalize = text => text.toLocaleLowerCase('fr').normalize('NFD').replace(/\p{Diacritic}/gu, '');
  const sections = [...catalog.querySelectorAll('[data-category]')].map(section => ({
    section,
    link: categoryLinks.get(`#${section.id}`),
    items: [...section.querySelectorAll('[data-menu-item]')].map(item => ({
      item,
      text: normalize(item.dataset.menuItem),
    })),
  }));

  function filterMenu() {
    const words = normalize(input.value.trim()).split(/\s+/);
    let hasResults = false;
    for (const { section, link, items } of sections) {
      let matchesCategory = false;
      for (const { item, text } of items) {
        const matches = words.every(word => text.includes(word));
        item.hidden = !matches;
        matchesCategory ||= matches;
      }
      section.hidden = !matchesCategory;
      if (link) link.hidden = !matchesCategory;
      hasResults ||= matchesCategory;
    }
    noResults.hidden = hasResults;
  }

  menuSearch.hidden = false;
  input.addEventListener('input', filterMenu);
  window.addEventListener('pageshow', filterMenu);
  filterMenu();
}

const passwordToggle = document.querySelector('[data-password-toggle]');
const passwordField = passwordToggle && document.getElementById(passwordToggle.getAttribute('aria-controls'));

if (passwordField) {
  passwordToggle.hidden = false;
  passwordToggle.addEventListener('click', () => {
    const show = passwordField.type === 'password';
    passwordField.type = show ? 'text' : 'password';
    passwordToggle.textContent = show ? 'Masquer' : 'Afficher';
    passwordToggle.setAttribute('aria-label', show ? 'Masquer le mot de passe' : 'Afficher le mot de passe');
  });
}

const bookingForm = document.querySelector('[data-booking-form]');

if (bookingForm) {
  const channel = bookingForm.querySelector('[data-booking-channel]');
  const contactFields = bookingForm.querySelectorAll('[data-contact-field]');

  function updateContactFields() {
    const activeField = channel.value === 'email' ? 'email' : 'phone';
    for (const field of contactFields) {
      const active = field.dataset.contactField === activeField;
      field.hidden = !active;
      const input = field.querySelector('input');
      input.disabled = !active;
      input.required = active;
    }
  }

  channel.addEventListener('change', updateContactFields);
  window.addEventListener('pageshow', updateContactFields);
  updateContactFields();
}
