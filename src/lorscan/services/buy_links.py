"""Build deep-links into external card marketplaces.

Cardmarket has a query-string filter system (sellerCountry, sellerReputation,
language, minCondition, isFoil...). CardTrader has its own analogous one
(language / condition / seller country / foil). For both we surface a small,
opinionated default optimised for a Netherlands-based collector and let
`config.toml` override each value. Filters can also be lists, in which case
the param is repeated.

TCGplayer URLs are passed through unchanged — it does not expose filter
parameters that lorscan currently surfaces.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Cardmarket numeric codes (from their filter UI):
#   sellerCountry: 21=Belgium, 5=Germany, 7=France, 23=Netherlands, 33=UK, ...
#   sellerReputation: 1=any, 2=neutral+, 3=ok+, 4=good+, 5=very-good+, 6=outstanding
#   language: 1=English, 2=French, 3=German, 4=Spanish, 5=Italian, ...
#   minCondition: 1=Mint, 2=Near Mint, 3=Excellent, 4=Good, 5=Light Played, ...
DEFAULT_CARDMARKET_FILTERS: dict[str, int | list[int]] = {
    "sellerCountry": 23,    # Netherlands
    "sellerReputation": 4,  # Good and above
    "language": 1,          # English
    "minCondition": 3,      # Excellent and above
}

# CardTrader filter keys come from their `/cards/<id>/filter.json` payload —
# every blueprint_value's `property.ui_reference_name` is the canonical
# filter key. Filterable properties for Lorcana:
#   language    Select  values: en, fr, it, de, es, jp, zh-CN
#   condition   Select  values: Near Mint, Slightly Played, Moderately Played,
#                                Played, Poor    (single-value, no min-floor)
#   foil        Boolean
#   signed      Boolean
#   altered     Boolean
# Note: seller country is NOT URL-filterable on CardTrader — their
# "Same Country" toggle is applied client-side off the user's profile
# country. Set it once in your CardTrader account if you want NL-only
# sellers (and stay logged in when clicking the buy-link).
DEFAULT_CARDTRADER_FILTERS: dict[str, Any] = {
    "language": "en",
}


def _stringify(value: Any) -> str:
    """Serialize a single filter value the way external marketplaces expect.

    TOML `foil = true` parses to Python `True`; `str(True)` would emit
    `"True"` (capital T) which CardTrader doesn't recognise — coerce
    booleans to JSON-style lowercase explicitly.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _build_url_with_filters(
    base_url: str,
    defaults: Mapping[str, Any],
    overrides: Mapping[str, Any] | None,
) -> str:
    """Merge base-URL query, defaults, and overrides; re-emit as one URL.

    LorcanaJSON's marketplace URLs sometimes ship with their own query
    params (e.g. Cardmarket's `?language=1`). Merging by re-parsing
    avoids duplicate keys that would let the upstream value silently win
    over a lorscan-side override.

    Precedence (last wins): base URL query → lorscan defaults → user filters.
    """
    parsed = urlsplit(base_url)
    merged: dict[str, Any] = dict(parse_qsl(parsed.query, keep_blank_values=True))
    merged.update(defaults)
    if overrides:
        merged.update(overrides)

    if not merged:
        return base_url

    pairs: list[tuple[str, str]] = []
    for key, value in merged.items():
        if isinstance(value, (list, tuple)):
            pairs.extend((key, _stringify(v)) for v in value)
        else:
            pairs.append((key, _stringify(value)))

    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(pairs), parsed.fragment)
    )


def cardmarket_buy_url(
    base_url: str | None,
    *,
    filters: Mapping[str, int | Sequence[int]] | None = None,
) -> str:
    """Append filter query string to a Cardmarket product URL.

    `filters` overlays on top of `DEFAULT_CARDMARKET_FILTERS`; pass a list
    to repeat a param (e.g. `{"sellerCountry": [23, 5]}` for NL+DE).
    Returns "" if `base_url` is falsy so templates can render conditionally.
    """
    if not base_url:
        return ""
    return _build_url_with_filters(base_url, DEFAULT_CARDMARKET_FILTERS, filters)


def cardtrader_buy_url(
    base_url: str | None,
    *,
    filters: Mapping[str, Any] | None = None,
) -> str:
    """Append filter query string to a CardTrader product URL.

    Symmetric with `cardmarket_buy_url` — `filters` overlays on
    `DEFAULT_CARDTRADER_FILTERS`. With no filters configured, the URL is
    returned unchanged (LorcanaJSON's cardTraderUrl is already complete).
    """
    if not base_url:
        return ""
    return _build_url_with_filters(base_url, DEFAULT_CARDTRADER_FILTERS, filters)


