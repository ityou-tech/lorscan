"""Migration 008: external-link columns on cards."""

from __future__ import annotations

from lorscan.storage.db import Database


def test_external_link_columns_exist(db: Database):
    cursor = db.connection.execute("PRAGMA table_info(cards)")
    columns = {row["name"] for row in cursor.fetchall()}
    expected = {
        "cardmarket_id",
        "cardmarket_url",
        "cardtrader_id",
        "cardtrader_url",
        "tcgplayer_id",
        "tcgplayer_url",
    }
    missing = expected - columns
    assert not missing, f"Missing columns: {missing}"


def test_external_link_columns_are_nullable(db: Database):
    """A card with no external links should insert without error."""
    db.connection.execute(
        "INSERT INTO sets (set_code, name, total_cards, synced_at) "
        "VALUES ('TFC', 'The First Chapter', 204, '2024-01-01T00:00:00Z')"
    )
    db.connection.execute(
        "INSERT INTO cards (card_id, set_code, collector_number, name, "
        "                   rarity, api_payload) "
        "VALUES ('TFC-001', 'TFC', '1', 'Test Card', 'Common', '{}')"
    )
    row = db.connection.execute(
        "SELECT cardmarket_url, cardtrader_url, tcgplayer_url "
        "FROM cards WHERE card_id = 'TFC-001'"
    ).fetchone()
    assert row["cardmarket_url"] is None
    assert row["cardtrader_url"] is None
    assert row["tcgplayer_url"] is None


def test_existing_card_id_index_still_works(db: Database):
    """Migration is purely additive — pre-existing indexes unaffected."""
    cursor = db.connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='index' AND tbl_name='cards'"
    )
    index_names = {row[0] for row in cursor.fetchall()}
    assert any("card" in n.lower() for n in index_names)
