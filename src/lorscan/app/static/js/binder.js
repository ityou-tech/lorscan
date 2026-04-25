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

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => initBooks(document));
  } else {
    initBooks(document);
  }

  // Re-init when a binder is opened — until that point the first page might
  // not have been laid out, and lazy-loaded images haven't kicked in.
  document.addEventListener('toggle', (e) => {
    if (!(e.target instanceof HTMLDetailsElement)) return;
    if (!e.target.classList.contains('binder')) return;
    if (e.target.open) initBooks(e.target);
  }, true);
})();
