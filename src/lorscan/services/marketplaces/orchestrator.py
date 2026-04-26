"""Drive one full sweep against one shop adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from lorscan.services.marketplaces.base import ShopAdapter
from lorscan.services.marketplaces.bazaarofmagic import BazaarAdapter, ListingCard
from lorscan.services.marketplaces.matching import resolve_listing
from lorscan.storage.db import Database


@dataclass(frozen=True)
class SweepResult:
    sweep_id: int
    status: str          # 'ok' | 'partial' | 'failed'
    listings_seen: int
    listings_matched: int
    errors: int


_USER_AGENT = "lorscan/0.1 (+https://github.com/ityou-tech/lorscan)"


async def run_sweep(
    db: Database,
    *,
    adapter: ShopAdapter,
    base_url: str,
    only_set: str | None = None,
) -> SweepResult:
    """Crawl every enabled set on `adapter`, write listings, record sweep stats."""
    mp = db.get_marketplace_by_slug(adapter.slug)
    if mp is None:
        raise RuntimeError(
            f"marketplace {adapter.slug!r} not seeded — apply migration 007"
        )
    sweep_id = db.start_marketplace_sweep(mp["id"])

    categories = db.get_enabled_set_categories(marketplace_id=mp["id"])
    if only_set:
        categories = [c for c in categories if c["set_code"] == only_set]

    seen = matched = 0
    detail_errors = 0
    set_failures = 0

    # Per-detail-failure counter — passed to BazaarAdapter so we observe errors
    # that happen inside crawl_set's gather() loop. Other adapters that don't
    # support this hook will simply not increment detail_errors.
    def on_detail_error(card: ListingCard, exc: Exception) -> None:
        nonlocal detail_errors
        detail_errors += 1

    if isinstance(adapter, BazaarAdapter):
        adapter._on_error = on_detail_error  # type: ignore[attr-defined]

    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=20.0,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        for cat in categories:
            try:
                async for listing in adapter.crawl_set(
                    client,
                    set_code=cat["set_code"],
                    category_path=cat["category_path"],
                ):
                    seen += 1
                    card_id = resolve_listing(
                        db, set_code=cat["set_code"], listing=listing
                    )
                    if card_id is not None:
                        matched += 1
                    db.upsert_listing(
                        marketplace_id=mp["id"],
                        external_id=listing.external_id,
                        card_id=card_id,
                        finish=listing.finish,
                        price_cents=listing.price_cents,
                        currency=listing.currency,
                        in_stock=listing.in_stock,
                        url=listing.url,
                        title=listing.title,
                        fetched_at=datetime.now(UTC).isoformat(),
                    )
            except httpx.HTTPError:
                set_failures += 1
                continue

    if not categories:
        status = "ok"  # nothing to do, but the sweep ran cleanly
    elif set_failures == 0:
        status = "ok"
    elif set_failures == len(categories):
        status = "failed"
    else:
        status = "partial"

    db.finish_marketplace_sweep(
        sweep_id,
        listings_seen=seen,
        listings_matched=matched,
        errors=detail_errors + set_failures,
        status=status,
    )
    return SweepResult(
        sweep_id=sweep_id,
        status=status,
        listings_seen=seen,
        listings_matched=matched,
        errors=detail_errors + set_failures,
    )
