"""Migration 007: marketplace tables exist after migrate()."""

from __future__ import annotations

from lorscan.storage.db import Database


def test_marketplace_tables_created(db: Database):
    cursor = db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('marketplaces','marketplace_set_categories',"
        "'marketplace_listings','marketplace_sweeps')"
    )
    names = {row[0] for row in cursor.fetchall()}
    assert names == {
        "marketplaces",
        "marketplace_set_categories",
        "marketplace_listings",
        "marketplace_sweeps",
    }


def test_bazaar_marketplace_seeded(db: Database):
    row = db.connection.execute(
        "SELECT slug, display_name, base_url, enabled "
        "FROM marketplaces WHERE slug = 'bazaarofmagic'"
    ).fetchone()
    assert row is not None
    assert row["display_name"] == "Bazaar of Magic"
    assert row["base_url"] == "https://www.bazaarofmagic.eu"
    assert row["enabled"] == 1


def test_listing_card_fk_is_nullable(db: Database):
    db.connection.execute(
        "INSERT INTO marketplace_listings "
        "(marketplace_id, external_id, card_id, finish, price_cents, "
        " currency, in_stock, url, title, fetched_at) "
        "VALUES (1, 'x123', NULL, 'regular', 400, 'EUR', 1, "
        " 'https://example.com/x', 'Whatever', '2026-04-26T00:00:00+00:00')"
    )
    # Should not raise — card_id is nullable for unmatched listings.


def test_listing_unique_per_marketplace_external_id(db: Database):
    import sqlite3
    db.connection.execute(
        "INSERT INTO marketplace_listings "
        "(marketplace_id, external_id, card_id, finish, price_cents, "
        " currency, in_stock, url, title, fetched_at) "
        "VALUES (1, 'dup', NULL, 'regular', 100, 'EUR', 1, 'u', 't', 'now')"
    )
    try:
        db.connection.execute(
            "INSERT INTO marketplace_listings "
            "(marketplace_id, external_id, card_id, finish, price_cents, "
            " currency, in_stock, url, title, fetched_at) "
            "VALUES (1, 'dup', NULL, 'foil', 200, 'EUR', 0, 'u2', 't2', 'now')"
        )
    except sqlite3.IntegrityError:
        return
    raise AssertionError("Expected UNIQUE violation on (marketplace_id, external_id)")
