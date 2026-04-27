"""Drive one full sweep against one shop adapter."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from lorscan import __version__
from lorscan.services.marketplaces.base import ShopAdapter
from lorscan.services.marketplaces.bazaarofmagic import BazaarAdapter, ListingCard
from lorscan.services.marketplaces.matching import resolve_listing
from lorscan.storage.db import Database

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SweepResult:
    sweep_id: int
    status: str          # 'ok' | 'partial' | 'failed'
    listings_seen: int
    listings_matched: int
    errors: int


_USER_AGENT = f"lorscan/{__version__} (+https://github.com/ityou-tech/lorscan)"


async def run_sweep(
    db: Database,
    *,
    adapter: ShopAdapter,
    base_url: str,
    only_set: str | None = None,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> SweepResult:
    """Crawl every enabled set on `adapter`, write listings, record sweep stats."""
    mp = db.get_marketplace_by_slug(adapter.slug)
    if mp is None:
        raise RuntimeError(
            f"marketplace {adapter.slug!r} not seeded — apply migration 007"
        )
    sweep_id = db.start_marketplace_sweep(mp["id"])

    seen = matched = 0
    detail_errors = 0
    set_failures = 0
    crashed = False
    # Initialized before the try so the `finally` block can safely reference
    # len(categories) even if the assignment inside the try never runs.
    categories: list = []

    # Per-detail-failure counter — passed to BazaarAdapter so we observe errors
    # that happen inside crawl_set's gather() loop. Other adapters that don't
    # support this hook will simply not increment detail_errors.
    def on_detail_error(card: ListingCard, exc: Exception) -> None:
        nonlocal detail_errors
        detail_errors += 1

    if isinstance(adapter, BazaarAdapter):
        adapter._on_error = on_detail_error  # type: ignore[attr-defined]

    try:
        categories = db.get_enabled_set_categories(marketplace_id=mp["id"])
        if only_set:
            categories = [c for c in categories if c["set_code"] == only_set]
        if not categories:
            raise RuntimeError(
                f"No enabled set categories for {adapter.slug!r}. "
                f"Seed the per-set TOML and re-run."
            )

        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=20.0,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            for cat in categories:
                set_seen = 0
                set_matched = 0
                if on_progress is not None:
                    on_progress(cat["set_code"], 0, 0)
                try:
                    async for listing in adapter.crawl_set(
                        client,
                        set_code=cat["set_code"],
                        category_path=cat["category_path"],
                    ):
                        seen += 1
                        set_seen += 1
                        card_id = resolve_listing(
                            db, set_code=cat["set_code"], listing=listing
                        )
                        if card_id is not None:
                            matched += 1
                            set_matched += 1
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
                        # Periodic progress every 25 listings.
                        if on_progress is not None and set_seen % 25 == 0:
                            on_progress(cat["set_code"], set_seen, set_matched)
                except httpx.HTTPError as e:
                    set_failures += 1
                    logger.warning(
                        "sweep: set %s listing-page failed: %s",
                        cat["set_code"], e,
                    )
                    continue
                # Per-set summary (always, even if 0 listings).
                if on_progress is not None:
                    on_progress(cat["set_code"], set_seen, set_matched)
    except BaseException:
        crashed = True
        raise
    finally:
        if crashed:
            status = "failed"
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
