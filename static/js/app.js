/* ==========================================================================
   NOVA Hospitality — console shell behaviour
   Sidebar collapse / mobile drawer, theme toggle, toast auto-dismiss,
   nav-group memory.
   ========================================================================== */
(function () {
  "use strict";

  var shell = document.getElementById("app-shell");
  var COLLAPSE_KEY = "nova.sidebar.collapsed";
  var THEME_KEY = "nova.theme";
  var NAV_KEY = "nova.nav.open";

  // --- Theme --------------------------------------------------------------
  function applyTheme(mode) {
    if (mode === "dark" || mode === "light") {
      document.documentElement.setAttribute("data-theme", mode);
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
  }
  try {
    var savedTheme = localStorage.getItem(THEME_KEY);
    if (savedTheme) applyTheme(savedTheme);
  } catch (err) {}

  var themeToggle = document.querySelector("[data-theme-toggle]");
  if (themeToggle) {
    themeToggle.addEventListener("click", function () {
      var current = document.documentElement.getAttribute("data-theme");
      if (!current) {
        current = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
      }
      var next = current === "dark" ? "light" : "dark";
      applyTheme(next);
      try { localStorage.setItem(THEME_KEY, next); } catch (err) {}
    });
  }

  if (!shell) return;

  var desktopToggle = document.getElementById("sidebar-toggle");
  var mobileToggle = document.getElementById("mobile-toggle");
  var sidebarBrand = shell.querySelector(".sidebar .brand-card");
  var main = shell.querySelector(".main");
  var skipLink = document.querySelector(".skip-link");
  var overlay = document.getElementById("shell-overlay");
  var mobileLayout = window.matchMedia("(max-width: 1080px)");
  var desktopCollapsed = false;

  function syncDesktopToggle() {
    if (!desktopToggle) return;
    var collapsed = shell.classList.contains("collapsed");
    var label = desktopToggle.querySelector(".sidebar-toggle-label");
    desktopToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    desktopToggle.setAttribute("aria-label", collapsed ? "Développer la navigation" : "Réduire la navigation");
    if (label) label.textContent = collapsed ? "Développer" : "Réduire";
  }

  function setDesktopCollapsed(collapsed) {
    desktopCollapsed = collapsed;
    shell.classList.toggle("collapsed", collapsed);
    try { localStorage.setItem(COLLAPSE_KEY, String(collapsed)); } catch (err) {}
    syncDesktopToggle();
  }

  function setMobileOpen(open, returnFocus) {
    var wasOpen = shell.classList.contains("mobile-open");
    shell.classList.toggle("mobile-open", open);
    if (main) main.inert = open;
    if (skipLink) skipLink.inert = open;
    if (mobileToggle) mobileToggle.setAttribute("aria-expanded", String(open));
    if (open && sidebarBrand) sidebarBrand.focus();
    if (!open && wasOpen && returnFocus && mobileToggle) mobileToggle.focus();
  }

  function syncSidebarLayout() {
    setMobileOpen(false, false);
    shell.classList.toggle("collapsed", !mobileLayout.matches && desktopCollapsed);
    syncDesktopToggle();
  }

  try { desktopCollapsed = localStorage.getItem(COLLAPSE_KEY) === "true"; } catch (err) {}
  syncSidebarLayout();
  mobileLayout.addEventListener("change", syncSidebarLayout);

  if (desktopToggle) {
    desktopToggle.addEventListener("click", function () {
      setDesktopCollapsed(!desktopCollapsed);
    });
  }

  if (mobileToggle) {
    mobileToggle.addEventListener("click", function () {
      setMobileOpen(true, false);
    });
  }

  function closeMobile() { setMobileOpen(false, true); }

  if (overlay) overlay.addEventListener("click", closeMobile);

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && shell.classList.contains("mobile-open")) closeMobile();
  });

  // --- Nav groups: expand on click when collapsed, remember open state ----
  var openSet = new Set();
  try { openSet = new Set(JSON.parse(localStorage.getItem(NAV_KEY) || "[]")); } catch (err) {}

  document.querySelectorAll("[data-nav-group]").forEach(function (group, index) {
    var key = (group.querySelector(".nav-text") || {}).textContent || String(index);
    key = key.trim();
    if (openSet.has(key)) group.open = true;

    var summary = group.querySelector("summary");
    if (summary) {
      summary.addEventListener("click", function (e) {
        if (!mobileLayout.matches && desktopCollapsed) {
          e.preventDefault();
          setDesktopCollapsed(false);
        }
      });
    }

    group.addEventListener("toggle", function () {
      if (group.open) openSet.add(key); else openSet.delete(key);
      try { localStorage.setItem(NAV_KEY, JSON.stringify(Array.from(openSet))); } catch (err) {}
    });
  });

  // --- Click-to-copy (.copy-box) --------------------------------------
  document.querySelectorAll(".copy-box").forEach(function (box) {
    box.setAttribute("role", "button");
    box.setAttribute("tabindex", "0");
    box.title = "Cliquer pour copier";
    function copy() {
      var text = (box.textContent || "").trim();
      function done() {
        box.classList.add("is-copied");
        setTimeout(function () { box.classList.remove("is-copied"); }, 1400);
      }
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(done, function () {});
      } else {
        try {
          var r = document.createRange();
          r.selectNodeContents(box);
          var sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(r);
          document.execCommand("copy");
          done();
        } catch (e) {}
      }
    }
    box.addEventListener("click", copy);
    box.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); copy(); }
    });
  });

  // --- Toast / message auto-dismiss -------------------------------------
  document.querySelectorAll(".messages .message").forEach(function (msg) {
    setTimeout(function () {
      msg.style.transition = "opacity .3s ease, transform .3s ease";
      msg.style.opacity = "0";
      msg.style.transform = "translateY(-6px)";
      setTimeout(function () { msg.remove(); }, 320);
    }, 5200);
  });

  // --- Searchable select ------------------------------------------------
  // Progressive enhancement of every <select class="select-input"> in the
  // console forms: keeps the native <select> for submit + validation and
  // lays a type-to-filter combobox over it. Native is left alone below
  // MIN_OPTIONS or when [data-no-enhance] is set.
  enhanceSelects();

  function enhanceSelects() {
    var MIN_OPTIONS = 6;
    document.querySelectorAll("select.select-input").forEach(function (select) {
      if (select.dataset.ssDone || select.disabled) return;
      if (select.hasAttribute("data-no-enhance")) return;
      var opts = Array.prototype.slice.call(select.options);
      if (opts.length < MIN_OPTIONS) return;
      select.dataset.ssDone = "1";

      var multiple = select.multiple;
      var wrap = document.createElement("div");
      wrap.className = "ss" + (multiple ? " ss-multi" : "");
      select.parentNode.insertBefore(wrap, select);
      wrap.appendChild(select);
      select.classList.add("ss-native");
      select.tabIndex = -1;

      var control = document.createElement("button");
      control.type = "button";
      control.className = "ss-control";
      control.setAttribute("aria-haspopup", "listbox");
      control.setAttribute("aria-expanded", "false");

      var panel = document.createElement("div");
      panel.className = "ss-panel";
      panel.hidden = true;
      var search = document.createElement("input");
      search.type = "text";
      search.className = "ss-search";
      search.placeholder = "Filtrer…";
      search.autocomplete = "off";
      var list = document.createElement("div");
      list.className = "ss-list";
      list.setAttribute("role", "listbox");
      panel.appendChild(search);
      panel.appendChild(list);
      wrap.appendChild(control);
      wrap.appendChild(panel);

      var items = opts.map(function (o) {
        var el = document.createElement("div");
        el.className = "ss-opt";
        el.setAttribute("role", "option");
        el.textContent = o.text;
        if (o.disabled) el.classList.add("is-disabled");
        el.addEventListener("click", function () { choose(o); });
        list.appendChild(el);
        return { opt: o, el: el };
      });

      function choose(o) {
        if (o.disabled) return;
        if (multiple) {
          o.selected = !o.selected;
        } else {
          select.value = o.value;
          close();
          control.focus();
        }
        select.dispatchEvent(new Event("change", { bubbles: true }));
        sync();
      }

      function ph(text) {
        var s = document.createElement("span");
        s.className = "ss-ph";
        s.textContent = text;
        return s;
      }

      function sync() {
        if (multiple) {
          var chosen = opts.filter(function (o) { return o.selected && o.value !== ""; });
          control.textContent = "";
          if (!chosen.length) {
            control.appendChild(ph("Sélectionner…"));
          } else {
            chosen.forEach(function (o) {
              var chip = document.createElement("span");
              chip.className = "ss-chip";
              chip.textContent = o.text;
              control.appendChild(chip);
            });
          }
          items.forEach(function (it) { it.el.classList.toggle("is-selected", it.opt.selected); });
        } else {
          var cur = select.options[select.selectedIndex];
          control.textContent = "";
          if (cur && cur.value === "") control.appendChild(ph(cur.text || "Sélectionner…"));
          else control.textContent = cur ? cur.text : "";
          items.forEach(function (it) {
            it.el.classList.toggle("is-selected", it.opt.value === select.value && it.opt.value !== "");
          });
        }
      }

      function filter(q) {
        q = q.trim().toLowerCase();
        var first = null;
        items.forEach(function (it) {
          var hit = it.opt.text.toLowerCase().indexOf(q) !== -1;
          it.el.hidden = !hit;
          it.el.classList.remove("is-active");
          if (hit && !first && !it.opt.disabled) first = it.el;
        });
        if (first) first.classList.add("is-active");
      }

      function open() {
        panel.hidden = false;
        wrap.classList.add("is-open");
        control.setAttribute("aria-expanded", "true");
        search.value = "";
        filter("");
        setTimeout(function () { search.focus(); }, 0);
        document.addEventListener("pointerdown", outside);
      }
      function close() {
        panel.hidden = true;
        wrap.classList.remove("is-open");
        control.setAttribute("aria-expanded", "false");
        document.removeEventListener("pointerdown", outside);
      }
      function outside(e) { if (!wrap.contains(e.target)) close(); }

      control.addEventListener("click", function () {
        wrap.classList.contains("is-open") ? close() : open();
      });
      search.addEventListener("input", function () { filter(search.value); });
      search.addEventListener("keydown", function (e) {
        var vis = items.filter(function (it) { return !it.el.hidden && !it.opt.disabled; });
        var i = vis.findIndex(function (it) { return it.el.classList.contains("is-active"); });
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          if (!vis.length) return;
          if (i >= 0) vis[i].el.classList.remove("is-active");
          i = e.key === "ArrowDown" ? (i + 1) % vis.length : (i - 1 + vis.length) % vis.length;
          vis[i].el.classList.add("is-active");
          vis[i].el.scrollIntoView({ block: "nearest" });
        } else if (e.key === "Enter") {
          e.preventDefault();
          if (i >= 0) choose(vis[i].opt);
        } else if (e.key === "Escape") {
          e.preventDefault();
          close();
          control.focus();
        }
      });

      sync();
    });
  }

  // --- Auto-fill nightly rate from the chosen room's base rate ----------
  // Picking a Room on the "Assign a room" form fills Nightly rate from
  // that room's room type (data-base-rate on the <option>, set by
  // PlatformModelForm._option_attrs). Only fills while the field is still
  // blank/zero — once the person types their own rate, picking a
  // different room won't overwrite it.
  document.addEventListener("input", function (e) {
    if (e.target.name === "nightly_rate") e.target.dataset.userEdited = "1";
  });
  document.addEventListener("change", function (e) {
    var select = e.target;
    if (select.name !== "room" || !select.options) return;
    var opt = select.options[select.selectedIndex];
    var rate = opt && opt.dataset.baseRate;
    if (!rate) return;
    var form = select.closest("form");
    var target = form && form.querySelector('input[name="nightly_rate"]');
    if (!target || target.dataset.userEdited) return;
    if (target.value === "" || Number(target.value) === 0) target.value = rate;
  });

  // --- Kitchen display auto-refresh -------------------------------------
  var kdsBoard = document.querySelector("[data-kds-board]");
  if (kdsBoard) {
    var refreshDelay = 60000;
    var reloadTimer = window.setTimeout(function () {
      if (document.hidden) return;
      var active = document.activeElement;
      if (active && kdsBoard.contains(active) && /INPUT|TEXTAREA|SELECT/.test(active.tagName)) return;
      window.location.reload();
    }, refreshDelay);
    window.addEventListener("beforeunload", function () {
      window.clearTimeout(reloadTimer);
    });
  }
})();
