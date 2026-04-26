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
    if (indicator) indicator.textContent = String(clamped + 1);
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
  // Quantity/+Add forms POST to the server which 303s back to /collection
  // or /missing. By default that resets scroll to top, closes every binder
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
  // size in a lightbox overlay. Works on /collection, /missing, and
  // /scan/{id} (anywhere a `.pocket-art img` or `.binder-card-art` is
  // rendered). The lightbox is created lazily on first click — keeps the
  // base markup clean.

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

  // ---------- want-list copy-to-clipboard (/missing only) ----------
  //
  // Two flavors of button:
  //   [data-copy-binder="ROF"]  — copies that one set's missing cards
  //   [data-copy-all]           — copies every missing card across the page
  // Both read the existing `.pocket--missing` DOM (no separate data layer)
  // and assemble plain text suitable for pasting into Discord, trade
  // threads, notes, etc.

  function formatBinder(binderEl) {
    const summary = binderEl.querySelector(':scope > summary');
    const name = summary?.querySelector('.binder-name')?.textContent.trim() || '';
    const code = summary?.querySelector('.binder-set-code')?.textContent.trim() || '';
    const missing = binderEl.querySelectorAll('.pocket--missing');
    if (missing.length === 0) return null;

    const lines = [`${name} (${code}) — ${missing.length} missing`];
    missing.forEach((p) => {
      const id = p.querySelector('.pocket-id')?.textContent.trim() || '';
      const cardName = p.querySelector('.pocket-name')?.textContent.trim() || '';
      const sub = p.querySelector('.pocket-sub')?.textContent.trim();
      const tail = sub ? `${cardName} — ${sub}` : cardName;
      lines.push(`${id.padEnd(8)}${tail}`);
    });
    return lines.join('\n');
  }

  function copyText(text) {
    if (!text) return Promise.resolve(false);
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(() => true, () => false);
    }
    // Fallback for non-secure contexts (http://localhost is secure, so this
    // mostly only fires on plain-IP local networks).
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
    return Promise.resolve(ok);
  }

  function flashToast(msg) {
    const toast = document.getElementById('copy-toast');
    if (!toast) return;
    toast.textContent = msg;
    toast.hidden = false;
    toast.classList.add('is-visible');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
      toast.classList.remove('is-visible');
      setTimeout(() => { toast.hidden = true; }, 220);
    }, 1600);
  }

  // capture:true so we fire before the click bubbles to <summary> and
  // toggles the <details>. stopPropagation here prevents that toggle.
  document.addEventListener('click', (e) => {
    const inline = e.target.closest('[data-copy-binder]');
    const all = e.target.closest('[data-copy-all]');
    if (!inline && !all) return;
    e.preventDefault();
    e.stopPropagation();

    if (inline) {
      const code = inline.dataset.copyBinder;
      const binder = document.getElementById(code);
      const text = binder ? formatBinder(binder) : null;
      if (!text) return flashToast('Nothing to copy');
      return copyText(text).then((ok) =>
        flashToast(ok ? `Copied ${code} want-list` : 'Copy failed')
      );
    }

    // copy-all: walk every binder on the page in display order.
    const blocks = [];
    let total = 0;
    document.querySelectorAll('.binder').forEach((b) => {
      const block = formatBinder(b);
      if (block) {
        blocks.push(block);
        total += b.querySelectorAll('.pocket--missing').length;
      }
    });
    if (blocks.length === 0) return flashToast('Nothing to copy');
    const header = `Lorscana want-list — ${total} cards across ${blocks.length} sets`;
    const text = `${header}\n\n${blocks.join('\n\n')}\n`;
    copyText(text).then((ok) =>
      flashToast(ok ? `Copied ${total}-card want-list` : 'Copy failed')
    );
  }, true);

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

  // Scroll the open binder's summary to just below the sticky `.binder-nav`
  // (or the topbar on pages without nav). This collapses the chrome above
  // the binder so the 3×3 page grid actually fits the viewport — a 1080px
  // viewport has ~370px of chrome above the second open binder when sat at
  // scroll-Y=0, but only ~133px once `.binder-nav` is pinned at top:0.
  function scrollBinderIntoFocus(binder, behavior) {
    const summary = binder.querySelector(':scope > summary');
    if (!summary) return;
    const nav = document.querySelector('.binder-nav');
    const topbar = document.querySelector('.topbar');
    // The nav is `position: sticky; top: 0`. Once we scroll past the
    // page header it pins, so the available headroom is its height. If
    // there's no nav (e.g. /scan), fall back to the topbar.
    const headroom = (nav ? nav.offsetHeight : 0) || (topbar ? topbar.offsetHeight : 0);
    const targetY = window.scrollY + summary.getBoundingClientRect().top - headroom - 8;
    window.scrollTo({ top: Math.max(0, targetY), behavior: behavior || 'auto' });
  }

})();
