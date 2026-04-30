"""Migration 009: normalize card_id case mismatches against set_code."""

from __future__ import annotations

from importlib import resources

from lorscan.storage.db import Database

_MIGRATION_009_SQL = (
    resources.files("lorscan.storage.migrations")
    .joinpath("009_normalize_card_id_case.sql")
    .read_text()
)


def _seed_legacy_typo(db: Database) -> None:
    """Insert a legacy `URs-190` row (typo) plus FK refs in collection_items
    and scan_results — mirrors the real-world breakage migration 009 fixes."""
    db.connection.execute(
        "INSERT INTO sets (set_code, name, total_cards, synced_at) "
        "VALUES ('URS', 'Ursula''s Return', 204, '2024-01-01T00:00:00Z')"
    )
    db.connection.execute(
        "INSERT INTO cards (card_id, set_code, collector_number, name, "
        "                   rarity, api_payload) "
        "VALUES ('URs-190', 'URS', '190', 'Test Card', 'Common', '{}')"
    )
    db.connection.execute(
        "INSERT INTO collection_items (card_id, finish, quantity, updated_at) "
        "VALUES ('URs-190', 'regular', 2, '2026-04-26T00:00:00Z')"
    )
    db.connection.execute(
        "INSERT INTO scans (photo_hash, photo_path, status, created_at) "
        "VALUES ('abc', '/tmp/x.jpg', 'completed', '2026-04-26T00:00:00Z')"
    )
    db.connection.execute(
        "INSERT INTO scan_results (scan_id, grid_position, confidence, "
        "                          matched_card_id, match_method) "
        "VALUES (1, '0,0', 'high', 'URs-190', 'collector_number_exact')"
    )
    db.connection.commit()


def test_legacy_card_id_typo_renamed_with_fk_refs(db: Database, stub_marketplace_listings):
    """A row with card_id='URs-190' (lowercase 's' typo) gets renamed to
    'URS-190' so later upserts at (set_code='URS', collector_number='190')
    don't collide on UNIQUE. FK refs in collection_items and scan_results
    follow the rename."""
    _seed_legacy_typo(db)

    # Re-apply 009 manually — running migrations are idempotent for this
    # rename pattern (the temp-table query yields zero rows after the fix).
    db.connection.executescript(_MIGRATION_009_SQL)

    rows = db.connection.execute(
        "SELECT card_id FROM cards WHERE set_code = 'URS'"
    ).fetchall()
    assert [r["card_id"] for r in rows] == ["URS-190"]

    ci = db.connection.execute(
        "SELECT card_id FROM collection_items"
    ).fetchone()
    assert ci["card_id"] == "URS-190"

    sr = db.connection.execute(
        "SELECT matched_card_id FROM scan_results"
    ).fetchone()
    assert sr["matched_card_id"] == "URS-190"


def test_correctly_cased_card_ids_unchanged(db: Database, stub_marketplace_listings):
    """A normal card with matching prefix (`TFC-001` for set_code 'TFC')
    must NOT be touched by migration 009."""
    db.connection.execute(
        "INSERT INTO sets (set_code, name, total_cards, synced_at) "
        "VALUES ('TFC', 'TFC', 204, '2024-01-01T00:00:00Z')"
    )
    db.connection.execute(
        "INSERT INTO cards (card_id, set_code, collector_number, name, "
        "                   rarity, api_payload) "
        "VALUES ('TFC-001', 'TFC', '1', 'Ariel', 'Common', '{}')"
    )
    db.connection.commit()

    db.connection.executescript(_MIGRATION_009_SQL)

    row = db.connection.execute(
        "SELECT card_id FROM cards WHERE set_code = 'TFC'"
    ).fetchone()
    assert row["card_id"] == "TFC-001"


def test_migration_is_idempotent(db: Database, stub_marketplace_listings):
    """Re-running 009 on already-clean data is a no-op."""
    db.connection.execute(
        "INSERT INTO sets (set_code, name, total_cards, synced_at) "
        "VALUES ('URS', 'URS', 204, '2024-01-01T00:00:00Z')"
    )
    db.connection.execute(
        "INSERT INTO cards (card_id, set_code, collector_number, name, "
        "                   rarity, api_payload) "
        "VALUES ('URS-190', 'URS', '190', 'X', 'Common', '{}')"
    )
    db.connection.commit()

    db.connection.executescript(_MIGRATION_009_SQL)
    db.connection.executescript(_MIGRATION_009_SQL)

    rows = db.connection.execute("SELECT card_id FROM cards").fetchall()
    assert [r["card_id"] for r in rows] == ["URS-190"]
