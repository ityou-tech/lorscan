"""Bazaar of Magic adapter — listing-page + detail-page parsers + crawler."""

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
    # Bazaar (Shopware 6) wraps each product in an anchor pointing at /p/...
    # The href may be absolute or relative; substring match handles both.
    for anchor in soup.select("a[href*='/nl-NL/p/']"):
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
    up to the enclosing card container and search its text.
    """
    container = anchor
    for _ in range(5):
        container = container.parent
        if container is None:
            return None
        text = container.get_text(" ", strip=True)
        m = _PRICE_RE.search(text)
        if m:
            return int(m.group(1)) * 100 + int(m.group(2))
    return None
