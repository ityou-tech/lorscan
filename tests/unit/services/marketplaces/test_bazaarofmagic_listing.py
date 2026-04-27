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
    # ROF page 1 with items=24 has exactly 24 product cards. Pin the count
    # so any leak from sidebar / cross-sell / recommendations modules into
    # the parser is caught loudly rather than tolerated by a fuzzy range.
    assert len(cards) == 24, f"got {len(cards)} cards"


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


def test_listing_excludes_sidebar_anchors():
    """Sidebar 'recent comments' anchors must not leak into results."""
    html = (FIXTURE_DIR / "listing.html").read_text()
    cards = parse_listing_page(html, base_url="https://www.bazaarofmagic.eu")
    # Bazaar's sidebar emits anchors to product pages from arbitrary sets
    # (not the requested ROF). The parser must scope to the grid only.
    # If we ever return >24 cards from a page that has 24 visible products,
    # we are leaking sidebar/recommendations.
    assert len(cards) == 24, (
        f"Expected exactly 24 grid cards, got {len(cards)}. "
        "Sidebar / cross-sell anchors are leaking into results."
    )


def test_listing_pins_specific_prices():
    """Lock specific (title, price) pairs to detect cross-card leaks."""
    html = (FIXTURE_DIR / "listing.html").read_text()
    cards = parse_listing_page(html, base_url="https://www.bazaarofmagic.eu")
    by_title = {c.title: c.price_cents for c in cards}

    # Three cards from the fixture with KNOWN-DISTINCT prices (50 / 75 / 400
    # cents). A regression where every card gets the first card's price
    # would fail two of these three assertions immediately.
    samples = {
        "Winnie The Pooh, Hunny Wizard (foil)": 50,
        "Bucky, Squirrel Squeak Tutor (errata version) (foil)": 75,
        "Yzma, Scary Beyond All Reason (foil)": 400,
    }
    for title, expected_cents in samples.items():
        assert by_title.get(title) == expected_cents, (
            f"price mismatch for {title!r}: "
            f"expected {expected_cents}, got {by_title.get(title)}"
        )
