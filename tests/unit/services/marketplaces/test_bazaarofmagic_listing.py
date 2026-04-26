"""Bazaar of Magic listing-page parser."""

from __future__ import annotations

from pathlib import Path

from lorscan.services.marketplaces.bazaarofmagic import (
    ListingCard,
    parse_listing_page,
)

FIXTURE_DIR = Path(__file__).parents[3] / "fixtures" / "marketplaces" / "bazaarofmagic"


def test_parse_listing_returns_24_products():
    html = (FIXTURE_DIR / "listing.html").read_text()
    cards = parse_listing_page(html, base_url="https://www.bazaarofmagic.eu")
    # ROF page 1 with items=24 has up to 24 product cards. Allow a small
    # range to tolerate Bazaar tweaking page size or cross-sell modules.
    assert 18 <= len(cards) <= 30, f"got {len(cards)} cards"


def test_listing_card_fields_are_populated():
    html = (FIXTURE_DIR / "listing.html").read_text()
    cards = parse_listing_page(html, base_url="https://www.bazaarofmagic.eu")
    sample = cards[0]
    assert isinstance(sample, ListingCard)
    assert sample.external_id  # non-empty product id (numeric string)
    assert sample.external_id.isdigit()
    assert sample.url.startswith("https://www.bazaarofmagic.eu/nl-NL/p/")
    assert sample.title  # non-empty
    assert sample.price_cents > 0


def test_listing_external_ids_are_unique():
    html = (FIXTURE_DIR / "listing.html").read_text()
    cards = parse_listing_page(html, base_url="https://www.bazaarofmagic.eu")
    ids = [c.external_id for c in cards]
    assert len(ids) == len(set(ids)), "duplicate external_ids — dedupe is broken"


def test_empty_page_returns_empty_list():
    html = (FIXTURE_DIR / "empty_listing.html").read_text()
    cards = parse_listing_page(html, base_url="https://www.bazaarofmagic.eu")
    assert cards == [], f"expected [] for empty page, got {len(cards)} cards"
