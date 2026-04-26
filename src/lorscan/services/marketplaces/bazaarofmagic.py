"""Bazaar of Magic adapter — listing-page parser.

Detail-page parser and the crawl_set generator land in Tasks 6 and 7
respectively (see docs/plans/2026-04-26-marketplace-stock-plan.md).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from lorscan.services.marketplaces.base import Listing


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

    in_stock = _detect_in_stock(soup)

    return DetailExtras(collector_number=collector, finish=finish, in_stock=in_stock)


def _detect_in_stock(soup: BeautifulSoup) -> bool:
    """Determine in-stock status, preferring the structural class hook.

    Bazaar emits `<div class="stockinfo in-stock">` or `<div class="stockinfo
    out-of-stock">` on the product page. That is the authoritative signal.
    Only if no `.stockinfo` element is found do we fall back to text-based
    detection (with conservative default = out-of-stock for unknown).

    Substring search alone is unsafe because the persistent sidebar always
    contains "70.000+ producten op voorraad" USP copy — that would flip
    every out-of-stock card to in-stock.
    """
    stockinfo = soup.select_one("div.stockinfo")
    if stockinfo is not None:
        classes = stockinfo.get("class") or []
        if "in-stock" in classes:
            return True
        if "out-of-stock" in classes:
            return False
        # Class present but neither marker matched — fall through to text.

    text_blob = soup.get_text(" ", strip=True).lower()
    if "uitverkocht" in text_blob:
        return False
    return "op voorraad" in text_blob


def _find_product_title(soup: BeautifulSoup) -> str | None:
    """Locate the product title element on a Bazaar detail page.

    Bazaar wraps the product title in `div.pdp ... div.title h1`; the
    cookie-banner off-canvas (`#offCanvasCookie`) also emits an `<h1>`
    earlier in the DOM, so we deliberately do NOT fall back to a bare
    `h1` selector — that would silently pick the cookie banner's
    "Fijn dat je er bent!" copy if the scoped selectors all stop matching
    after a Bazaar template change. Returning None on template drift is the
    "loud failure" path: downstream gets collector_number=None and
    finish="regular", and the matcher silently drops the listing — far
    better than confidently asserting the wrong title.
    """
    for selector in (
        "div.pdp div.title h1",
        "div.pdp h1",
        "h1.product-name",
        "h1[itemprop='name']",
    ):
        node = soup.select_one(selector)
        if node:
            text = node.get_text(strip=True)
            if text:
                return text
    return None


class BazaarAdapter:
    """Adapter for https://www.bazaarofmagic.eu (Shopware 6).

    Walks per-set listing pages and fans out detail-page fetches with a
    bounded concurrency window. Per-detail HTTP errors are silently dropped
    here — the sweep orchestrator (Task 10) tracks failure counts at a
    higher level so a single 500 doesn't poison an entire set crawl.
    """

    slug = "bazaarofmagic"
    display_name = "Bazaar of Magic"

    def __init__(
        self,
        *,
        items_per_page: int = 24,
        max_concurrent_details: int = 4,
        inter_batch_delay_s: float = 0.2,
    ):
        self._items_per_page = items_per_page
        self._max_concurrent_details = max_concurrent_details
        self._inter_batch_delay_s = inter_batch_delay_s

    async def crawl_set(
        self,
        client: httpx.AsyncClient,
        set_code: str,
        category_path: str,
    ) -> AsyncIterator[Listing]:
        base_url = f"{client.base_url.scheme}://{client.base_url.host}"
        page = 1
        sem = asyncio.Semaphore(self._max_concurrent_details)

        while True:
            response = await client.get(
                category_path,
                params={"page": str(page), "items": str(self._items_per_page)},
            )
            response.raise_for_status()
            listing_cards = parse_listing_page(response.text, base_url=base_url)
            if not listing_cards:
                return

            async def fetch(card: ListingCard) -> Listing | None:
                async with sem:
                    try:
                        detail_resp = await client.get(_path_only(card.url))
                        detail_resp.raise_for_status()
                    except httpx.HTTPError:
                        return None
                    extras = parse_detail_page(detail_resp.text)
                return Listing(
                    external_id=card.external_id,
                    title=card.title,
                    price_cents=card.price_cents,
                    currency="EUR",
                    in_stock=extras.in_stock,
                    url=card.url,
                    finish=extras.finish,
                    collector_number=extras.collector_number,
                )

            results = await asyncio.gather(*(fetch(c) for c in listing_cards))
            for listing in results:
                if listing is not None:
                    yield listing

            if self._inter_batch_delay_s > 0:
                await asyncio.sleep(self._inter_batch_delay_s)
            page += 1


def _path_only(url: str) -> str:
    """Return just the path+query portion of an absolute URL."""
    parsed = urlparse(url)
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")
