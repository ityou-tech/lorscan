"""Bazaar of Magic detail-page parser."""

from __future__ import annotations

from pathlib import Path

from lorscan.services.marketplaces.bazaarofmagic import (
    DetailExtras,
    parse_detail_page,
)

FIXTURE = (
    Path(__file__).parents[3]
    / "fixtures" / "marketplaces" / "bazaarofmagic" / "detail.html"
)


def test_detail_extracts_collector_number_and_finish():
    extras = parse_detail_page(FIXTURE.read_text())
    assert isinstance(extras, DetailExtras)
    assert extras.collector_number == "224"
    assert extras.finish == "foil"


def test_detail_extracts_in_stock_status():
    extras = parse_detail_page(FIXTURE.read_text())
    # Pinocchio fixture should be in stock when captured ("Op voorraad").
    # If the captured page later goes out of stock, regenerate the fixture.
    assert extras.in_stock is True


def test_detail_handles_title_without_collector_number():
    html = """<html><body>
        <h1 class="product-name">The Reforged Crown (oversized)</h1>
        <strong>Op voorraad</strong>
    </body></html>"""
    extras = parse_detail_page(html)
    assert extras.collector_number is None
    assert extras.finish == "regular"
    assert extras.in_stock is True


def test_detail_recognises_uitverkocht_as_out_of_stock():
    html = """<html><body>
        <h1>Some Card (foil)</h1>
        <span>Uitverkocht</span>
    </body></html>"""
    extras = parse_detail_page(html)
    assert extras.in_stock is False
    assert extras.finish == "foil"


def test_detail_recognises_cold_foil():
    html = "<html><body><h1>Card Name (cold foil)</h1>Op voorraad</body></html>"
    extras = parse_detail_page(html)
    assert extras.finish == "cold_foil"


def test_detail_pinocchio_fixture_is_in_stock_foil_224():
    """Pinned: Pinocchio #224 foil from captured detail.html.

    All three fields together — if any drift, this single test failing
    immediately tells us which field's heuristic broke.
    """
    extras = parse_detail_page(FIXTURE.read_text())
    assert extras == DetailExtras(
        collector_number="224",
        finish="foil",
        in_stock=True,
    )
