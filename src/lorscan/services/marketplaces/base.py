"""Marketplace scraping primitives: shared dataclass + adapter Protocol."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx


@dataclass(frozen=True)
class Listing:
    """One product as scraped from a marketplace.

    Identity is `(marketplace_id, external_id)`. `card_id` is resolved later
    by the matcher; here we only carry what the shop told us. `finish` and
    `collector_number` may be None when the title doesn't expose them — the
    matcher decides what to do with those listings.
    """

    external_id: str
    title: str
    price_cents: int
    currency: str
    in_stock: bool
    url: str
    finish: str | None              # 'regular' | 'foil' | 'cold_foil'
    collector_number: str | None    # parsed from title; None if absent


@runtime_checkable
class ShopAdapter(Protocol):
    """One marketplace's scraping surface. One adapter per shop."""

    slug: str
    display_name: str

    def crawl_set(
        self,
        client: httpx.AsyncClient,
        set_code: str,
        category_path: str,
    ) -> AsyncIterator[Listing]: ...
