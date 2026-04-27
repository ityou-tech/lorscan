"""Build deep-links into external card marketplaces.

Cardmarket has a query-string filter system (sellerCountry, sellerReputation,
language, minCondition, isFoil...). We surface a small, opinionated default
optimised for a Netherlands-based collector and let `config.toml` override
each value. Filters can also be lists, in which case the param is repeated
(Cardmarket honours repeated params for sellerCountry and language).

CardTrader and TCGplayer URLs are passed through unchanged — neither
exposes filter parameters that lorscan currently surfaces.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from urllib.parse import urlencode

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

    merged: dict[str, int | Sequence[int]] = dict(DEFAULT_CARDMARKET_FILTERS)
    if filters:
        merged.update(filters)

    pairs: list[tuple[str, str]] = []
    for key, value in merged.items():
        if isinstance(value, (list, tuple)):
            for v in value:
                pairs.append((key, str(v)))
        else:
            pairs.append((key, str(value)))

    return f"{base_url}?{urlencode(pairs)}"


def cardtrader_buy_url(base_url: str | None) -> str:
    """Pass-through; LorcanaJSON's cardTraderUrl is already complete."""
    return base_url or ""
