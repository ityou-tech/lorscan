// 3D page-flipping binder — vanilla JS, no dependencies.
//
// Each .binder-book has N pages; only one is .is-active at a time. Clicking
// the prev/next buttons (or pressing ← / →  while a binder is focused)
// advances the active page. The CSS handles the actual flip animation via
// transform: rotateY() with a perspective on the parent.
//
// We avoid framework lifecycle stuff because every binder is a standalone
// stateful widget — the simplest implementation is one event listener at
// document level that walks up to find the closest .binder-book.

(function () {
  'use strict';

  function pages(book) {
    return book.querySelectorAll('.binder-page');
  }

  function setActive(book, idx) {
    const all = pages(book);
    if (all.length === 0) return;
    const clamped = Math.max(0, Math.min(idx, all.length - 1));
    all.forEach((p, i) => {
      const isActive = i === clamped;
      const wasBefore = parseInt(p.dataset.pageIndex, 10) < clamped;
      p.classList.toggle('is-active', isActive);
      p.classList.toggle('is-before', !isActive && wasBefore);
      p.classList.toggle('is-after', !isActive && !wasBefore);
      p.setAttribute('aria-hidden', isActive ? 'false' : 'true');
    });
    const indicator = book.querySelector('[data-flip-current]');
    if (indicator) {
      const next = String(clamped + 1);
      // Indicator is an <input type="number"> so the user can type-to-jump;
      // fall back to textContent for any future non-input variant.
      if ('value' in indicator) indicator.value = next;
      else indicator.textContent = next;
    }
    const total = all.length;
    const prev = book.querySelector('[data-flip="prev"]');
    const next = book.querySelector('[data-flip="next"]');
    if (prev) prev.disabled = clamped === 0;
    if (next) next.disabled = clamped === total - 1;
    book.dataset.activePage = String(clamped);
  }

  function getActive(book) {
    return parseInt(book.dataset.activePage || '0', 10);
  }

  // Initialize each book on first paint so the disabled state of the
  // prev button is correct (we start at page 0 = no prev).
  function initBooks(root) {
    root.querySelectorAll('.binder-book').forEach((book) => {
      setActive(book, 0);
    });
  }

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-flip]');
    if (!btn) return;
    const book = btn.closest('.binder-book');
    if (!book) return;
    e.preventDefault();
    const dir = btn.dataset.flip;
    const cur = getActive(book);
    setActive(book, dir === 'next' ? cur + 1 : cur - 1);
  });

  // Type-to-jump: the [data-flip-current] indicator is an <input type=number>.
  // Commit on `change` (which fires on Enter and on blur) so the user can
  // tab out, click out, or press Enter — all jump to the typed page.
  document.addEventListener('change', (e) => {
    const input = e.target.closest?.('[data-flip-current]');
    if (!input) return;
    const book = input.closest('.binder-book');
    if (!book) return;
    const total = pages(book).length;
    const n = parseInt(input.value, 10);
    if (Number.isNaN(n)) {
      input.value = String(getActive(book) + 1);
      return;
    }
    setActive(book, Math.max(0, Math.min(n - 1, total - 1)));
  });

  // Pressing Enter inside the input commits and blurs (so the focus
  // returns to the document and arrow-key flipping works again).
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    const input = e.target.closest?.('[data-flip-current]');
    if (!input) return;
    e.preventDefault();
    input.blur();
  });

  // Keyboard navigation: when a binder is focused (or its pages container),
  // ← / → flip pages. Open the binder by hitting Enter/Space on its summary.
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    // Don't hijack typing inside form elements.
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'select' || tag === 'textarea') return;
    const book = e.target.closest('.binder-book');
    if (!book) return;
    const cur = getActive(book);
    setActive(book, e.key === 'ArrowRight' ? cur + 1 : cur - 1);
    e.preventDefault();
  });

  // Wheel: a horizontal scroll over the page area also flips. Most users
  // won't discover this, but it feels right when it happens.
  document.addEventListener('wheel', (e) => {
    if (Math.abs(e.deltaX) < 30 || Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return;
    const book = e.target.closest('.binder-book');
    if (!book) return;
    const cur = getActive(book);
    setActive(book, e.deltaX > 0 ? cur + 1 : cur - 1);
  }, { passive: true });

  // ---------- state preservation across POST/redirect/GET ----------
  //
  // Quantity/+Add forms POST to the server which 303s back to /collection.
  // By default that resets scroll to top, closes every binder
  // back to its server-default state, and forgets which page the user was
  // on. Stash the relevant state into sessionStorage on submit and restore
  // it after reload — feels like an in-place update without any XHR.

  const SS_SCROLL = 'lorscan:scrollY';
  const SS_OPEN_BINDERS = 'lorscan:openBinders';
  const SS_ACTIVE_PAGES = 'lorscan:activePages';

  function captureUiState() {
    sessionStorage.setItem(SS_SCROLL, String(window.scrollY));
    const openIds = [...document.querySelectorAll('.binder[open]')]
      .map((b) => b.id)
      .filter(Boolean);
    sessionStorage.setItem(SS_OPEN_BINDERS, JSON.stringify(openIds));
    const activePages = {};
    document.querySelectorAll('.binder-book').forEach((book) => {
      const id = book.dataset.binder;
      if (id) activePages[id] = getActive(book);
    });
    sessionStorage.setItem(SS_ACTIVE_PAGES, JSON.stringify(activePages));
  }

  function restoreUiState() {
    // Only override server-rendered state when sessionStorage has a value —
    // an empty list means "I saved no binders open", but a missing key
    // means "this is a fresh visit, leave the server defaults alone".
    const savedOpen = sessionStorage.getItem(SS_OPEN_BINDERS);
    if (savedOpen !== null) {
      try {
        const ids = JSON.parse(savedOpen);
        document.querySelectorAll('.binder').forEach((b) => {
          // Programmatic toggling fires the `toggle` event asynchronously.
          // Tag the binder so the toggle handler knows this open came from
          // state restore, not user click — and skips the auto-scroll
          // that would otherwise fight with the saved scrollY restore.
          if (ids.includes(b.id) && !b.open) b.dataset.suppressFocus = '1';
          b.open = ids.includes(b.id);
        });
      } catch (e) { /* ignore */ }
    }

    const savedPages = sessionStorage.getItem(SS_ACTIVE_PAGES);
    if (savedPages !== null) {
      try {
        const pages = JSON.parse(savedPages);
        Object.entries(pages).forEach(([id, idx]) => {
          const book = document.querySelector(`.binder-book[data-binder="${CSS.escape(id)}"]`);
          if (book) setActive(book, idx);
        });
      } catch (e) { /* ignore */ }
    }

    const y = sessionStorage.getItem(SS_SCROLL);
    if (y !== null) {
      requestAnimationFrame(() => {
        window.scrollTo({ top: parseInt(y, 10), behavior: 'instant' });
      });
    } else {
      // Fresh visit (no saved scroll): focus whichever binder rendered open
      // so the 3×3 grid sits inside the viewport instead of below the fold.
      const firstOpen = document.querySelector('.binder[open]');
      if (firstOpen) {
        requestAnimationFrame(() => scrollBinderIntoFocus(firstOpen, 'instant'));
      }
    }

    // One-shot: clear so navigations from the topbar don't restore stale state.
    sessionStorage.removeItem(SS_SCROLL);
    sessionStorage.removeItem(SS_OPEN_BINDERS);
    sessionStorage.removeItem(SS_ACTIVE_PAGES);
  }

  // Capture state right before any in-page mutation form submits — qty
  // controls and the missing-pocket "+ Add" button.
  document.addEventListener('submit', (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (
      form.matches('.qty-form, .pocket-add-form, .cell-correct-form, .pocket-controls form')
    ) {
      captureUiState();
    }
  }, true);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      initBooks(document);
      restoreUiState();
    });
  } else {
    initBooks(document);
    restoreUiState();
  }

  // ---------- click-to-enlarge card lightbox ----------
  //
  // Clicking a card image inside a binder pocket pops it open at full
  // size in a lightbox overlay. Works on /collection and /scan/{id}
  // (anywhere a `.pocket-art img` or `.binder-card-art` is rendered).
  // The lightbox is created lazily on first click — keeps the base
  // markup clean.

  function ensureLightbox() {
    let lb = document.getElementById('card-lightbox');
    if (lb) return lb;
    lb = document.createElement('div');
    lb.id = 'card-lightbox';
    lb.className = 'card-lightbox';
    lb.hidden = true;
    lb.innerHTML = `
      <button type="button" class="card-lightbox-close" aria-label="Close">×</button>
      <img class="card-lightbox-img" alt="">
      <div class="card-lightbox-caption"></div>
    `;
    document.body.appendChild(lb);
    lb.addEventListener('click', (e) => {
      // Click on the backdrop (lightbox itself) or the close button shuts it.
      if (e.target === lb || e.target.classList.contains('card-lightbox-close')) {
        closeLightbox();
      }
    });
    return lb;
  }

  function openLightbox(src, caption) {
    const lb = ensureLightbox();
    lb.querySelector('.card-lightbox-img').src = src;
    lb.querySelector('.card-lightbox-caption').textContent = caption || '';
    lb.hidden = false;
    requestAnimationFrame(() => lb.classList.add('is-open'));
    document.body.classList.add('lightbox-open');
  }

  function closeLightbox() {
    const lb = document.getElementById('card-lightbox');
    if (!lb) return;
    lb.classList.remove('is-open');
    document.body.classList.remove('lightbox-open');
    setTimeout(() => { lb.hidden = true; }, 180);
  }

  document.addEventListener('click', (e) => {
    // Match either the binder-page pocket art or the scan-detail card art.
    const img = e.target.closest('.pocket-art img, .binder-card-art');
    if (!img) return;
    // Ignore if the click is actually on a button overlaid on the art
    // (e.g. the per-cell rescan icon).
    if (e.target.closest('button, a')) return;
    e.preventDefault();
    const pocket = img.closest('.pocket, .binder-cell');
    const id = pocket?.querySelector('.pocket-id')?.textContent.trim() || '';
    const name = pocket?.querySelector('.pocket-name, .binder-card-info strong')?.textContent.trim() || '';
    const sub = pocket?.querySelector('.pocket-sub, .binder-card-info .subtitle')?.textContent.trim() || '';
    const caption = [id, name, sub].filter(Boolean).join(' · ');
    openLightbox(img.src, caption);
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeLightbox();
  });

  // ---------- want-list copy-to-clipboard ----------
  //
  // Page-level [data-copy-cm-all] dumps every `.pocket--missing` across all
  // binders in Cardmarket Mass-Import format (`1x Name - Subtitle (V.N) (Set
  // Name)`). Per-binder [data-cm-trigger] opens a scope dropdown whose items
  // (`[data-copy-cm-binder]` + `[data-cm-scope]`) copy a filtered slice of
  // that one set. Reads DOM directly — no separate data layer.
  //
  // Cardmarket caps a single wantlist at ~150 entries; the user splits
  // across multiple wantlists by hand if needed.

  const CARDMARKET_WANTS_URL =
    'https://www.cardmarket.com/en/Lorcana/Wants';

  // V.N comes from data-cm-version, card type from data-card-type (both set
  // server-side in collection.py). Scope filtering: `standard` = ≤ 204,
  // `specials` = enchanted + iconic, anything else = no filter.
  function formatBinderCardmarket(binderEl, scope) {
    let missing = Array.from(binderEl.querySelectorAll('.pocket--missing'));
    if (scope === 'standard') {
      missing = missing.filter((p) => p.dataset.cardType === 'standard');
    } else if (scope === 'specials') {
      missing = missing.filter((p) => p.dataset.cardType !== 'standard');
    }
    if (missing.length === 0) return null;
    const setName = binderEl
      .querySelector(':scope > summary .binder-name')
      ?.textContent.trim() || '';
    const setSuffix = setName ? ` (${setName})` : '';
    const lines = [];
    missing.forEach((p) => {
      const cardName = p.querySelector('.pocket-name')?.textContent.trim() || '';
      const sub = p.querySelector('.pocket-sub')?.textContent.trim();
      const full = sub ? `${cardName} - ${sub}` : cardName;
      if (!full) return;
      const v = p.dataset.cmVersion;
      const versionSuffix = v ? ` (V.${v})` : '';
      lines.push(`1x ${full}${versionSuffix}${setSuffix}`);
    });
    return { text: lines.join('\n'), count: lines.length };
  }

  function copyText(text) {
    if (!text) return Promise.resolve(false);
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(() => true, () => false);
    }
    return Promise.resolve(copyTextSync(text));
  }

  // execCommand fallback for insecure contexts where navigator.clipboard
  // is unavailable (e.g. plain http:// over LAN).
  function copyTextSync(text) {
    if (!text) return false;
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'absolute';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (_) { /* ignore */ }
    document.body.removeChild(ta);
    return ok;
  }

  function flashToast(msg) {
    showToast({ text: msg, durationMs: 1600 });
  }

  // Toast supports a clickable element built with DOM APIs (no innerHTML,
  // no manual escaping).
  function showToast({ text, node, durationMs }) {
    const toast = document.getElementById('copy-toast');
    if (!toast) return;
    toast.replaceChildren(node || document.createTextNode(text || ''));
    toast.hidden = false;
    toast.classList.add('is-visible');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
      toast.classList.remove('is-visible');
      setTimeout(() => { toast.hidden = true; }, 220);
    }, durationMs || 1600);
  }

  function buildCardmarketToast(sourceLabel, count) {
    // Two stacked lines: the "copied" confirmation, then a one-step recipe
    // ending in a clickable "Cardmarket Wants" link the user opens manually.
    const wrap = document.createElement('div');
    wrap.className = 'copy-toast-body';

    const line1 = document.createElement('div');
    line1.textContent = `Copied ${count} cards from ${sourceLabel}`;
    wrap.appendChild(line1);

    const line2 = document.createElement('div');
    line2.className = 'copy-toast-hint';
    line2.appendChild(document.createTextNode('Paste at '));
    const a = document.createElement('a');
    a.href = CARDMARKET_WANTS_URL;
    a.target = '_blank';
    a.rel = 'noopener';
    a.textContent = 'Cardmarket → Wants';
    line2.appendChild(a);
    line2.appendChild(document.createTextNode(' → + Add Deck List'));
    wrap.appendChild(line2);

    return wrap;
  }

  // Tracks whether any Cardmarket dropdown is currently open, so the
  // document-level click handler can skip the close-everything sweep when
  // there's nothing to close.
  let anyMenuOpen = false;

  function closeAllCardmarketMenus() {
    if (!anyMenuOpen) return;
    document.querySelectorAll('[data-cm-menu]').forEach((m) => {
      m.hidden = true;
      m.style.top = '';
      m.style.left = '';
      m.style.right = '';
    });
    document.querySelectorAll('[data-cm-trigger][aria-expanded="true"]').forEach((t) => {
      t.setAttribute('aria-expanded', 'false');
    });
    anyMenuOpen = false;
  }

  // Right-align the menu under its trigger using `right` (rather than `left`)
  // so we don't need the menu's own width — which would require it visible
  // first to measure. `documentElement.clientWidth` excludes the vertical
  // scrollbar, matching the initial containing block that `position: fixed`
  // resolves against; using `window.innerWidth` would offset the menu by
  // the scrollbar width.
  function positionCardmarketMenu(trigger, menu) {
    const rect = trigger.getBoundingClientRect();
    menu.style.top = `${rect.bottom + 4}px`;
    menu.style.right = `${document.documentElement.clientWidth - rect.right}px`;
    menu.style.left = 'auto';
  }

  // Scrolling/resizing while open would let the (fixed-position) menu drift
  // away from its (flow-positioned) trigger — cheaper to close than to track.
  window.addEventListener('scroll', closeAllCardmarketMenus, { passive: true });
  window.addEventListener('resize', closeAllCardmarketMenus, { passive: true });

  // capture:true so we fire before the click bubbles to <summary> and toggles
  // the <details>. stopPropagation here suppresses that activation.
  document.addEventListener('click', (e) => {
    const allBtn = e.target.closest('[data-copy-cm-all]');
    const cmTrigger = e.target.closest('[data-cm-trigger]');
    const cmItem = e.target.closest('[data-copy-cm-binder]');

    // Outside-click closes any open dropdown. Skip when the click is on a
    // trigger or inside a menu — those have their own paths.
    if (!cmTrigger && !cmItem) {
      closeAllCardmarketMenus();
    }

    if (!allBtn && !cmTrigger && !cmItem) return;
    e.preventDefault();
    e.stopPropagation();

    if (cmTrigger) {
      const code = cmTrigger.dataset.cmTrigger;
      const menu = document.querySelector(`[data-cm-menu="${CSS.escape(code)}"]`);
      const wasOpen = menu && !menu.hidden;
      closeAllCardmarketMenus();
      if (menu && !wasOpen) {
        positionCardmarketMenu(cmTrigger, menu);
        menu.hidden = false;
        cmTrigger.setAttribute('aria-expanded', 'true');
        anyMenuOpen = true;
      }
      return;
    }

    if (cmItem) {
      const code = cmItem.dataset.copyCmBinder;
      const scope = cmItem.dataset.cmScope || 'all';
      const binder = document.getElementById(code);
      const result = binder ? formatBinderCardmarket(binder, scope) : null;
      closeAllCardmarketMenus();
      if (!result) return flashToast('Nothing to copy');
      copyText(result.text).then((ok) => {
        if (!ok) return flashToast('Copy failed');
        const setLabel = binder.querySelector('.binder-name')?.textContent.trim()
          || code;
        showToast({ node: buildCardmarketToast(setLabel, result.count), durationMs: 6000 });
      });
      return;
    }

    const blocks = [];
    let total = 0;
    let setCount = 0;
    document.querySelectorAll('.binder').forEach((b) => {
      const result = formatBinderCardmarket(b);
      if (result) {
        blocks.push(result.text);
        total += result.count;
        setCount += 1;
      }
    });
    if (blocks.length === 0) return flashToast('Nothing to copy');

    copyText(blocks.join('\n')).then((ok) => {
      if (!ok) return flashToast('Copy failed');
      const label = `${setCount} ${setCount === 1 ? 'set' : 'sets'}`;
      showToast({ node: buildCardmarketToast(label, total), durationMs: 6000 });
    });
  }, true);

  // Escape key closes any open Cardmarket dropdown.
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeAllCardmarketMenus();
  });

  // Scroll a freshly-opened binder into focus. We deliberately don't call
  // `initBooks(e.target)` here even though it might seem natural — toggle
  // events are async, so by the time this fires `restoreUiState` has
  // already called setActive(book, savedPage). Re-running initBooks would
  // clobber that with page 0. The pages were laid out on first paint by
  // `initBooks(document)`, so there's nothing to re-init.
  document.addEventListener('toggle', (e) => {
    if (!(e.target instanceof HTMLDetailsElement)) return;
    if (!e.target.classList.contains('binder')) return;
    if (!e.target.open) return;
    // Skip auto-scroll if this open was triggered by restoreUiState —
    // the saved scrollY has already (or is about to) put us back where
    // the user was.
    if (e.target.dataset.suppressFocus === '1') {
      delete e.target.dataset.suppressFocus;
      return;
    }
    scrollBinderIntoFocus(e.target, 'smooth');
  }, true);

  // Scroll the open binder's summary to just below the topbar so the
  // 3×3 page grid sits in the viewport instead of below the fold.
  function scrollBinderIntoFocus(binder, behavior) {
    const summary = binder.querySelector(':scope > summary');
    if (!summary) return;
    const topbar = document.querySelector('.topbar');
    const headroom = topbar ? topbar.offsetHeight : 0;
    const targetY = window.scrollY + summary.getBoundingClientRect().top - headroom - 8;
    window.scrollTo({ top: Math.max(0, targetY), behavior: behavior || 'auto' });
  }

})();
