"""DB ops: marketplaces, set-categories, listings, sweeps."""

from __future__ import annotations

from datetime import UTC, datetime

from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet


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


def test_get_marketplace_by_slug_returns_seeded_bazaar(db: Database):
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    assert mp is not None
    assert mp["display_name"] == "Bazaar of Magic"


def test_get_marketplace_by_slug_returns_none_for_unknown(db: Database):
    assert db.get_marketplace_by_slug("does-not-exist") is None


def test_upsert_set_category_inserts_then_updates(db: Database):
    _seed_catalog(db)
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    db.upsert_set_category(
        marketplace_id=mp["id"],
        set_code="ROF",
        category_id="1000676",
        category_path="/nl-NL/c/rise-of-the-floodborn/1000676",
    )
    cats = db.get_enabled_set_categories(marketplace_id=mp["id"])
    assert len(cats) == 1
    assert cats[0]["set_code"] == "ROF"

    db.upsert_set_category(
        marketplace_id=mp["id"],
        set_code="ROF",
        category_id="1000676",
        category_path="/nl-NL/c/rise-of-the-floodborn-NEW/1000676",
    )
    cats = db.get_enabled_set_categories(marketplace_id=mp["id"])
    assert len(cats) == 1
    assert cats[0]["category_path"].endswith("-NEW/1000676")


def test_get_enabled_set_categories_skips_unseeded_sets(db: Database):
    """FK constraint on set_code rejects unknown sets."""
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    import sqlite3
    try:
        db.upsert_set_category(
            marketplace_id=mp["id"],
            set_code="ZZZ",
            category_id="1000999",
            category_path="/nl-NL/c/zzz/1000999",
        )
    except sqlite3.IntegrityError:
        return
    raise AssertionError("Expected IntegrityError on unknown set_code")


def test_sweep_lifecycle(db: Database):
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    sweep_id = db.start_marketplace_sweep(mp["id"])
    assert isinstance(sweep_id, int)
    db.finish_marketplace_sweep(
        sweep_id,
        listings_seen=10,
        listings_matched=8,
        errors=0,
        status="ok",
    )
    row = db.get_sweep(sweep_id)
    assert row["status"] == "ok"
    assert row["listings_seen"] == 10
    assert row["listings_matched"] == 8
    assert row["errors"] == 0
    assert row["finished_at"] is not None


def test_upsert_listing_then_query_cheapest_in_stock(db: Database):
    _seed_catalog(db)
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    now = datetime.now(UTC).isoformat()
    base = dict(
        marketplace_id=mp["id"],
        currency="EUR",
        url="https://example.com/x",
        title="Pinocchio (#224) (foil)",
        fetched_at=now,
    )
    db.upsert_listing(external_id="A", card_id="rof-224", finish="foil",
                      price_cents=1500, in_stock=True, **base)
    db.upsert_listing(external_id="B", card_id="rof-224", finish="regular",
                      price_cents=400, in_stock=True, **base)
    db.upsert_listing(external_id="C", card_id="rof-224", finish="regular",
                      price_cents=300, in_stock=False, **base)

    cheapest = db.get_cheapest_in_stock_per_card()
    assert "rof-224" in cheapest
    assert cheapest["rof-224"]["price_cents"] == 400
    assert cheapest["rof-224"]["marketplace_id"] == mp["id"]


def test_upsert_listing_updates_existing_external_id(db: Database):
    _seed_catalog(db)
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    now = datetime.now(UTC).isoformat()

    db.upsert_listing(
        marketplace_id=mp["id"], external_id="A", card_id="rof-224", finish="foil",
        price_cents=1500, currency="EUR", in_stock=True,
        url="https://example.com/x", title="Old title", fetched_at=now,
    )
    later = datetime.now(UTC).isoformat()
    db.upsert_listing(
        marketplace_id=mp["id"], external_id="A", card_id="rof-224", finish="foil",
        price_cents=1200, currency="EUR", in_stock=True,
        url="https://example.com/x", title="New title", fetched_at=later,
    )
    cheapest = db.get_cheapest_in_stock_per_card()
    assert cheapest["rof-224"]["price_cents"] == 1200


def test_get_cheapest_in_stock_excludes_unmatched_listings(db: Database):
    """Listings with NULL card_id (failed matches) must not appear."""
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    now = datetime.now(UTC).isoformat()
    db.upsert_listing(
        marketplace_id=mp["id"], external_id="oversized", card_id=None, finish=None,
        price_cents=300, currency="EUR", in_stock=True,
        url="https://example.com/oversized", title="The Reforged Crown (oversized)",
        fetched_at=now,
    )
    cheapest = db.get_cheapest_in_stock_per_card()
    assert cheapest == {}


def test_get_latest_finished_sweep_returns_none_when_empty(db: Database):
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    assert db.get_latest_finished_sweep(mp["id"]) is None


def test_get_latest_finished_sweep_returns_most_recent(db: Database):
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    s1 = db.start_marketplace_sweep(mp["id"])
    db.finish_marketplace_sweep(s1, listings_seen=1, listings_matched=1, errors=0, status="ok")
    s2 = db.start_marketplace_sweep(mp["id"])
    db.finish_marketplace_sweep(s2, listings_seen=2, listings_matched=2, errors=0, status="ok")
    latest = db.get_latest_finished_sweep(mp["id"])
    assert latest["id"] == s2
