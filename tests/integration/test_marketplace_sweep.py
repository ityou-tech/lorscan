"""End-to-end sweep: TOML → adapter → matcher → DB, with HTTP mocked."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from lorscan.services.marketplaces.bazaarofmagic import BazaarAdapter
from lorscan.services.marketplaces.orchestrator import run_sweep
from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "marketplaces" / "bazaarofmagic"


def _seed_catalog(db: Database) -> None:
    db.upsert_set(CardSet(set_code="ROF", name="Rise of the Floodborn", total_cards=204))
    db.upsert_card(
        Card(
            card_id="rof-224",
            set_code="ROF",
            collector_number="224",
            name="Pinocchio",
            subtitle="Strings Attached",
            rarity="Enchanted",
        )
    )


async def test_sweep_writes_listings_and_records_status(db: Database):
    _seed_catalog(db)
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    db.upsert_set_category(
        marketplace_id=mp["id"],
        set_code="ROF",
        category_id="1000676",
        category_path="/nl-NL/c/rise-of-the-floodborn/1000676",
    )

    base = "https://www.bazaarofmagic.eu"
    listing_html = (FIXTURE_DIR / "listing.html").read_text()
    detail_html = (FIXTURE_DIR / "detail.html").read_text()
    empty_html = (FIXTURE_DIR / "empty_listing.html").read_text()

    with respx.mock(assert_all_called=False) as mock:
        mock.get(
            f"{base}/nl-NL/c/rise-of-the-floodborn/1000676",
            params={"page": "1", "items": "24"},
        ).mock(return_value=httpx.Response(200, text=listing_html))
        mock.get(
            f"{base}/nl-NL/c/rise-of-the-floodborn/1000676",
            params={"page": "2", "items": "24"},
        ).mock(return_value=httpx.Response(200, text=empty_html))
        mock.get(url__regex=rf"{base}/nl-NL/p/.+").mock(
            return_value=httpx.Response(200, text=detail_html)
        )

        result = await run_sweep(
            db,
            adapter=BazaarAdapter(inter_batch_delay_s=0.0),
            base_url=base,
        )

    assert result.status == "ok"
    assert result.listings_seen == 24
    # Only the rof-224 card is in our catalog → 1 match (all 24 detail responses
    # are the Pinocchio fixture, but the listing-page external_ids differ —
    # so 24 listings, 1 of which matches by (set, collector_number)=(ROF, 224)).
    # Actually: every listing's collector_number is "224" because all detail
    # responses are the Pinocchio fixture. So all 24 match to rof-224.
    assert result.listings_matched == 24

    sweep = db.get_latest_finished_sweep(mp["id"])
    assert sweep is not None
    assert sweep["status"] == "ok"
    assert sweep["listings_seen"] == 24

    # Cheapest map has rof-224 (since all 24 listings matched to it).
    cheapest = db.get_cheapest_in_stock_per_card()
    assert "rof-224" in cheapest


async def test_sweep_partial_when_one_set_fails(db: Database):
    """If a set's listing-page request 5xx's, that set is skipped and sweep
    is marked 'partial' (not 'failed'), and other sets keep going."""
    _seed_catalog(db)
    db.upsert_set(CardSet(set_code="ITI", name="Into the Inklands", total_cards=204))

    mp = db.get_marketplace_by_slug("bazaarofmagic")
    db.upsert_set_category(
        marketplace_id=mp["id"],
        set_code="ROF",
        category_id="1000676",
        category_path="/nl-NL/c/rise-of-the-floodborn/1000676",
    )
    db.upsert_set_category(
        marketplace_id=mp["id"],
        set_code="ITI",
        category_id="1000697",
        category_path="/nl-NL/c/into-the-inklands/1000697",
    )

    base = "https://www.bazaarofmagic.eu"
    listing_html = (FIXTURE_DIR / "listing.html").read_text()
    detail_html = (FIXTURE_DIR / "detail.html").read_text()
    empty_html = (FIXTURE_DIR / "empty_listing.html").read_text()

    with respx.mock(assert_all_called=False) as mock:
        # ROF succeeds.
        mock.get(
            f"{base}/nl-NL/c/rise-of-the-floodborn/1000676",
            params={"page": "1", "items": "24"},
        ).mock(return_value=httpx.Response(200, text=listing_html))
        mock.get(
            f"{base}/nl-NL/c/rise-of-the-floodborn/1000676",
            params={"page": "2", "items": "24"},
        ).mock(return_value=httpx.Response(200, text=empty_html))
        # ITI fails.
        mock.get(
            f"{base}/nl-NL/c/into-the-inklands/1000697",
            params={"page": "1", "items": "24"},
        ).mock(return_value=httpx.Response(503, text="upstream down"))
        mock.get(url__regex=rf"{base}/nl-NL/p/.+").mock(
            return_value=httpx.Response(200, text=detail_html)
        )

        result = await run_sweep(
            db,
            adapter=BazaarAdapter(inter_batch_delay_s=0.0),
            base_url=base,
        )

    assert result.status == "partial"
    assert result.errors >= 1
    # ROF still completed: 24 listings should be in the DB.
    assert result.listings_seen == 24


async def test_sweep_only_set_filter(db: Database):
    """run_sweep(only_set='ROF') restricts the crawl to just that set."""
    _seed_catalog(db)
    db.upsert_set(CardSet(set_code="ITI", name="Into the Inklands", total_cards=204))
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    db.upsert_set_category(
        marketplace_id=mp["id"], set_code="ROF",
        category_id="1000676", category_path="/nl-NL/c/rise-of-the-floodborn/1000676",
    )
    db.upsert_set_category(
        marketplace_id=mp["id"], set_code="ITI",
        category_id="1000697", category_path="/nl-NL/c/into-the-inklands/1000697",
    )

    base = "https://www.bazaarofmagic.eu"
    listing_html = (FIXTURE_DIR / "listing.html").read_text()
    detail_html = (FIXTURE_DIR / "detail.html").read_text()
    empty_html = (FIXTURE_DIR / "empty_listing.html").read_text()

    with respx.mock(assert_all_called=False) as mock:
        # Only ROF should be hit. ITI route is registered but should NEVER be called.
        mock.get(
            f"{base}/nl-NL/c/rise-of-the-floodborn/1000676",
            params={"page": "1", "items": "24"},
        ).mock(return_value=httpx.Response(200, text=listing_html))
        mock.get(
            f"{base}/nl-NL/c/rise-of-the-floodborn/1000676",
            params={"page": "2", "items": "24"},
        ).mock(return_value=httpx.Response(200, text=empty_html))
        iti_route = mock.get(url__regex=rf"{base}/nl-NL/c/into-the-inklands/.+")
        iti_route.mock(return_value=httpx.Response(500, text="should not be called"))
        mock.get(url__regex=rf"{base}/nl-NL/p/.+").mock(
            return_value=httpx.Response(200, text=detail_html)
        )

        result = await run_sweep(
            db,
            adapter=BazaarAdapter(inter_batch_delay_s=0.0),
            base_url=base,
            only_set="ROF",
        )

    assert result.status == "ok"
    assert iti_route.called is False, "only_set filter leaked into ITI crawl"


async def test_sweep_counts_per_detail_errors(db: Database):
    """Per-detail HTTP errors increment the sweep's `errors` count via on_error."""
    _seed_catalog(db)
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    db.upsert_set_category(
        marketplace_id=mp["id"], set_code="ROF",
        category_id="1000676", category_path="/nl-NL/c/rise-of-the-floodborn/1000676",
    )

    base = "https://www.bazaarofmagic.eu"
    listing_html = (FIXTURE_DIR / "listing.html").read_text()
    empty_html = (FIXTURE_DIR / "empty_listing.html").read_text()

    with respx.mock(assert_all_called=False) as mock:
        mock.get(
            f"{base}/nl-NL/c/rise-of-the-floodborn/1000676",
            params={"page": "1", "items": "24"},
        ).mock(return_value=httpx.Response(200, text=listing_html))
        mock.get(
            f"{base}/nl-NL/c/rise-of-the-floodborn/1000676",
            params={"page": "2", "items": "24"},
        ).mock(return_value=httpx.Response(200, text=empty_html))
        mock.get(url__regex=rf"{base}/nl-NL/p/.+").mock(
            return_value=httpx.Response(500, text="boom"),
        )

        result = await run_sweep(
            db,
            adapter=BazaarAdapter(inter_batch_delay_s=0.0),
            base_url=base,
        )

    # 24 listing cards, all 24 detail fetches 500 → 24 errors.
    assert result.errors == 24
    assert result.listings_seen == 0  # nothing yielded
    # When there's no listing-page error but per-detail errors abound,
    # status should be 'ok' (the SET completed; individual cards failed).
    # Or 'partial' if you prefer — pick one and document. We expect 'ok'.
    assert result.status == "ok"


async def test_sweep_raises_when_no_categories_seeded(db: Database):
    """If TOML hasn't been seeded into marketplace_set_categories, the
    orchestrator raises RuntimeError and the sweep row is closed as 'failed'."""
    base = "https://www.bazaarofmagic.eu"
    with pytest.raises(RuntimeError, match="No enabled set categories"):
        await run_sweep(
            db,
            adapter=BazaarAdapter(inter_batch_delay_s=0.0),
            base_url=base,
        )

    # Sweep row was closed (not left running).
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    sweep = db.get_latest_finished_sweep(mp["id"])
    assert sweep is not None
    assert sweep["status"] == "failed"


async def test_sweep_failed_when_all_sets_fail(db: Database):
    """Two sets, both 5xx → status 'failed'."""
    _seed_catalog(db)
    db.upsert_set(CardSet(set_code="ITI", name="Into the Inklands", total_cards=204))
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    db.upsert_set_category(
        marketplace_id=mp["id"], set_code="ROF",
        category_id="1000676", category_path="/nl-NL/c/rise-of-the-floodborn/1000676",
    )
    db.upsert_set_category(
        marketplace_id=mp["id"], set_code="ITI",
        category_id="1000697", category_path="/nl-NL/c/into-the-inklands/1000697",
    )

    base = "https://www.bazaarofmagic.eu"
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=rf"{base}/nl-NL/c/.+").mock(
            return_value=httpx.Response(503, text="all down")
        )

        result = await run_sweep(
            db,
            adapter=BazaarAdapter(inter_batch_delay_s=0.0),
            base_url=base,
        )

    assert result.status == "failed"
    assert result.errors >= 2  # both sets failed
    assert result.listings_seen == 0


async def test_sweep_raises_when_marketplace_not_seeded(db: Database):
    """If the marketplace row was never created, raise RuntimeError loud."""
    # Delete the seeded Bazaar row to simulate an unseeded environment.
    db.connection.execute("DELETE FROM marketplaces WHERE slug = 'bazaarofmagic'")
    db.connection.commit()

    with pytest.raises(RuntimeError, match="not seeded"):
        await run_sweep(
            db,
            adapter=BazaarAdapter(inter_batch_delay_s=0.0),
            base_url="https://www.bazaarofmagic.eu",
        )
