"""Bazaar of Magic adapter — listing-page parser.

Detail-page parser and the crawl_set generator land in Tasks 6 and 7
respectively (see docs/plans/2026-04-26-marketplace-stock-plan.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class ListingCard:
    """A product as it appears on a category-listing page (sparse)."""

    external_id: str
    title: str
    price_cents: int
    url: str


_PRICE_RE = re.compile(r"€\s*(\d+)[,.](\d{2})")
_PRODUCT_URL_RE = re.compile(r"/nl-NL/p/[^/]+/(\d+)")


def parse_listing_page(html: str, *, base_url: str) -> list[ListingCard]:
    """Parse one /c/<set>?page=N HTML body into ListingCard rows.

    Returns [] if the page has no products (end of pagination).
    """
    soup = BeautifulSoup(html, "html.parser")
    cards: list[ListingCard] = []
    # Bazaar (Shopware 6) wraps each product card in `div.singles`. Scoping
    # the anchor selector to that container avoids the ~16 sibling anchors
    # in the persistent off-canvas "recent comments" sidebar (and any
    # cross-sell modules) leaking into the result set. On a true past-end
    # page the grid wrapper is absent entirely and we return [] cleanly.
    for anchor in soup.select("div.singles a[href*='/nl-NL/p/']"):
        href = anchor.get("href", "")
        match = _PRODUCT_URL_RE.search(href)
        if not match:
            continue
        external_id = match.group(1)
        title = (anchor.get_text(strip=True) or "").strip()
        if not title:
            continue
        price_cents = _extract_price_near(anchor)
        if price_cents is None:
            continue
        url = urljoin(base_url, href)
        cards.append(
            ListingCard(
                external_id=external_id,
                title=title,
                price_cents=price_cents,
                url=url,
            )
        )
    # Dedupe by external_id (Shopware emits the link multiple times per card).
    seen: set[str] = set()
    deduped: list[ListingCard] = []
    for c in cards:
        if c.external_id in seen:
            continue
        seen.add(c.external_id)
        deduped.append(c)
    return deduped


def _extract_price_near(anchor) -> int | None:
    """Find the price text near a product anchor.

    Bazaar puts the price in a sibling element of the product card; we walk
    up to the enclosing card container and search its text. The price sits
    at depth ~2 from the anchor in the current template — a budget of 3
    keeps one level of safety margin without escaping the card wrapper
    (where we would otherwise pick up the FIRST card's price for every
    product).
    """
    container = anchor
    for _ in range(3):
        container = container.parent
        if container is None:
            return None
        text = container.get_text(" ", strip=True)
        m = _PRICE_RE.search(text)
        if m:
            return int(m.group(1)) * 100 + int(m.group(2))
    return None


@dataclass(frozen=True)
class DetailExtras:
    """Per-product fields only available on the detail page."""

    collector_number: str | None
    finish: str | None
    in_stock: bool


_COLLECTOR_RE = re.compile(r"#(\d+)")
_FINISH_RES = (
    ("cold_foil", re.compile(r"\(cold foil\)", re.IGNORECASE)),
    ("foil", re.compile(r"\(foil\)", re.IGNORECASE)),
)


def parse_detail_page(html: str) -> DetailExtras:
    """Parse a /p/<slug>/<id> HTML body for collector_number/finish/in_stock."""
    soup = BeautifulSoup(html, "html.parser")
    title = _find_product_title(soup)

    collector = None
    if title:
        m = _COLLECTOR_RE.search(title)
        if m:
            collector = m.group(1)

    finish: str | None = "regular"
    if title:
        for label, pattern in _FINISH_RES:
            if pattern.search(title):
                finish = label
                break

    text_blob = soup.get_text(" ", strip=True).lower()
    if "uitverkocht" in text_blob:
        in_stock = False
    elif "op voorraad" in text_blob:
        in_stock = True
    else:
        # Conservative default: treat unknown as out-of-stock so we never
        # advertise something we can't confirm.
        in_stock = False

    return DetailExtras(collector_number=collector, finish=finish, in_stock=in_stock)


def _find_product_title(soup: BeautifulSoup) -> str | None:
    """Locate the product title element on a Bazaar detail page.

    Tries specific selectors first, then falls back to the first h1.
    Bazaar wraps the product title in `div.pdp ... div.title h1`; the
    cookie-banner off-canvas (`#offCanvasCookie`) also emits an `<h1>`
    earlier in the DOM, so a naive `h1` fallback would mis-identify the
    title as the cookie banner copy. The pdp/title selectors guard against
    that. Returns None if no title found.
    """
    for selector in (
        "div.pdp div.title h1",
        "div.pdp h1",
        "h1.product-name",
        "h1[itemprop='name']",
        "h1",
    ):
        node = soup.select_one(selector)
        if node:
            text = node.get_text(strip=True)
            if text:
                return text
    return None
