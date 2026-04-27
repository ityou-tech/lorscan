"""Cardmarket / CardTrader buy-link builders."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from lorscan.services.buy_links import (
    DEFAULT_CARDMARKET_FILTERS,
    cardmarket_buy_url,
    cardtrader_buy_url,
)

BASE = (
    "https://www.cardmarket.com/en/Lorcana/Products/Singles/"
    "The-First-Chapter/Stitch-Carefree-Surfer-V1"
)


def test_default_filters_match_user_preference():
    """NL sellers, English, min condition Excellent, reputation 'Good'."""
    assert DEFAULT_CARDMARKET_FILTERS == {
        "sellerCountry": 23,
        "sellerReputation": 4,
        "language": 1,
        "minCondition": 3,
    }


def test_url_appends_default_filters():
    url = cardmarket_buy_url(BASE)
    qs = parse_qs(urlsplit(url).query)
    assert qs["sellerCountry"] == ["23"]
    assert qs["language"] == ["1"]
    assert qs["minCondition"] == ["3"]
    assert qs["sellerReputation"] == ["4"]


def test_custom_filters_override_defaults():
    url = cardmarket_buy_url(BASE, filters={"sellerCountry": 21, "language": 5})
    qs = parse_qs(urlsplit(url).query)
    assert qs["sellerCountry"] == ["21"]
    assert qs["language"] == ["5"]
    assert "minCondition" in qs


def test_extra_filters_widen_search():
    """Multiple seller countries: Cardmarket accepts repeated params."""
    url = cardmarket_buy_url(
        BASE,
        filters={"sellerCountry": [23, 5, 7]},
    )
    qs = parse_qs(urlsplit(url).query)
    assert qs["sellerCountry"] == ["23", "5", "7"]


def test_empty_base_returns_empty_string():
    """A card without a cardmarket_url shouldn't blow up the template."""
    assert cardmarket_buy_url("") == ""
    assert cardmarket_buy_url(None) == ""


def test_cardtrader_url_is_passthrough():
    """CardTrader URLs from LorcanaJSON are already complete."""
    base = "https://www.cardtrader.com/cards/stitch-carefree-surfer"
    assert cardtrader_buy_url(base) == base
    assert cardtrader_buy_url(None) == ""
