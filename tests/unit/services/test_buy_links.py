"""Cardmarket / CardTrader buy-link builders + Cardmarket want-list export."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from lorscan.services.buy_links import (
    DEFAULT_CARDMARKET_FILTERS,
    DEFAULT_CARDTRADER_FILTERS,
    cardmarket_buy_url,
    cardtrader_buy_url,
)

BASE = (
    "https://www.cardmarket.com/en/Lorcana/Products/Singles/"
    "The-First-Chapter/Stitch-Carefree-Surfer-V1"
)


def _params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def test_default_filters_match_user_preference():
    """NL sellers, English, min condition Excellent, reputation 'Good'."""
    assert DEFAULT_CARDMARKET_FILTERS == {
        "sellerCountry": 23,
        "sellerReputation": 4,
        "language": 1,
        "minCondition": 3,
    }


def test_url_appends_default_filters():
    qs = _params(cardmarket_buy_url(BASE))
    assert qs["sellerCountry"] == ["23"]
    assert qs["language"] == ["1"]
    assert qs["minCondition"] == ["3"]
    assert qs["sellerReputation"] == ["4"]


def test_custom_filters_override_defaults():
    qs = _params(cardmarket_buy_url(BASE, filters={"sellerCountry": 21, "language": 5}))
    assert qs["sellerCountry"] == ["21"]
    assert qs["language"] == ["5"]
    assert "minCondition" in qs


def test_extra_filters_widen_search():
    """Multiple seller countries: Cardmarket accepts repeated params."""
    qs = _params(cardmarket_buy_url(BASE, filters={"sellerCountry": [23, 5, 7]}))
    assert sorted(qs["sellerCountry"]) == ["23", "5", "7"]


def test_empty_base_returns_empty_string():
    """A card without a cardmarket_url shouldn't blow up the template."""
    assert cardmarket_buy_url("") == ""
    assert cardmarket_buy_url(None) == ""


def test_user_filter_overrides_base_url_query():
    """LorcanaJSON's URLs include `?language=1`. A user override must win
    over that — otherwise the duplicate param could let upstream silently
    decide language."""
    qs = _params(cardmarket_buy_url(f"{BASE}?language=1", filters={"language": 3}))
    assert qs["language"] == ["3"]


def test_default_overrides_base_url_query():
    """Even without user filters, lorscan's defaults take precedence over
    whatever query the marketplace URL shipped with."""
    qs = _params(cardmarket_buy_url(f"{BASE}?language=2"))  # upstream French
    assert qs["language"] == [str(DEFAULT_CARDMARKET_FILTERS["language"])]


# ---------- CardTrader ----------


def test_cardtrader_default_filters_minimal():
    """Default ships only `language=en`; seller-country isn't URL-filterable
    on CardTrader (their 'Same Country' toggle is profile-driven)."""
    assert DEFAULT_CARDTRADER_FILTERS == {"language": "en"}


def test_cardtrader_buy_url_applies_default_language():
    url = cardtrader_buy_url(
        "https://www.cardtrader.com/en/cards/stitch-carefree-surfer"
    )
    assert _params(url)["language"] == ["en"]


def test_cardtrader_user_overrides_replace_default():
    url = cardtrader_buy_url(
        "https://www.cardtrader.com/p",
        filters={"language": "de", "condition": "Near Mint", "foil": False},
    )
    qs = _params(url)
    assert qs["language"] == ["de"]
    assert qs["condition"] == ["Near Mint"]
    assert qs["foil"] == ["false"]


def test_cardtrader_buy_url_returns_empty_for_falsy_base():
    assert cardtrader_buy_url(None) == ""
    assert cardtrader_buy_url("") == ""


def test_cardtrader_filters_preserve_existing_query_string():
    base = "https://www.cardtrader.com/en/cards/foo?ref=lorscan"
    qs = _params(cardtrader_buy_url(base, filters={"condition": "Near Mint"}))
    assert qs["ref"] == ["lorscan"]
    assert qs["condition"] == ["Near Mint"]
    assert qs["language"] == ["en"]  # default still applied


def test_cardtrader_list_filter_repeats_param():
    qs = _params(cardtrader_buy_url(
        "https://www.cardtrader.com/p",
        filters={"language": ["en", "fr"]},
    ))
    assert sorted(qs["language"]) == ["en", "fr"]


def test_cardtrader_boolean_filter_serializes_lowercase():
    """TOML `foil = true` parses to Python True; CardTrader needs lowercase."""
    qs = _params(cardtrader_buy_url(
        "https://www.cardtrader.com/p",
        filters={"foil": True, "signed": False},
    ))
    assert qs["foil"] == ["true"]
    assert qs["signed"] == ["false"]
