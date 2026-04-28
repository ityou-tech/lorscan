"""Migration 010: drop legacy INK set rows + unsuffixed ITI-004."""

from __future__ import annotations

from importlib import resources

from lorscan.storage.db import Database

_MIGRATION_010_SQL = (
    resources.files("lorscan.storage.migrations")
    .joinpath("010_drop_legacy_ink_set.sql")
    .read_text()
)


def _seed_legacy(db: Database) -> None:
    db.connection.execute(
        "INSERT INTO sets (set_code, name, total_cards, synced_at) VALUES "
        "('INK', 'Into the Inklands (legacy)', 204, '2024-01-01T00:00:00Z'), "
        "('ITI', 'Into the Inklands', 222, '2024-01-01T00:00:00Z')"
    )
    db.connection.execute(
        "INSERT INTO cards (card_id, set_code, collector_number, name, rarity, api_payload) VALUES "
        "('INK-004', 'INK', '4', 'Dalmatian Puppy', 'Common', '{}'), "
        "('INK-040', 'INK', '40', 'Iago', 'Common', '{}'), "
        "('ITI-004', 'ITI', '4', 'Dalmatian Puppy', 'Common', '{}'), "
        "('ITI-040', 'ITI', '40', 'Iago', 'Common', '{}')"
    )
    db.connection.execute(
        "INSERT INTO collection_items (card_id, finish, quantity, updated_at) "
        "VALUES ('INK-040', 'regular', 1, '2026-04-26T00:00:00Z')"
    )
    db.connection.commit()


def test_legacy_ink_rows_removed(db: Database):
    _seed_legacy(db)

    db.connection.executescript(_MIGRATION_010_SQL)

    sets = db.connection.execute(
        "SELECT set_code FROM sets ORDER BY set_code"
    ).fetchall()
    assert [s[0] for s in sets] == ["ITI"]

    cards = db.connection.execute(
        "SELECT card_id FROM cards ORDER BY card_id"
    ).fetchall()
    # INK-* rows AND legacy ITI-004 (unsuffixed Dalmatian) are gone;
    # other ITI rows survive.
    assert [c[0] for c in cards] == ["ITI-040"]

    # FK refs to deleted cards are also gone.
    items = db.connection.execute(
        "SELECT card_id FROM collection_items"
    ).fetchall()
    assert items == []


def test_non_ink_data_untouched(db: Database):
    """Sets / cards / collection that don't match the cleanup pattern
    survive the migration unchanged."""
    db.connection.execute(
        "INSERT INTO sets (set_code, name, total_cards, synced_at) "
        "VALUES ('TFC', 'TFC', 216, '2024-01-01T00:00:00Z')"
    )
    db.connection.execute(
        "INSERT INTO cards (card_id, set_code, collector_number, name, rarity, api_payload) "
        "VALUES ('TFC-001', 'TFC', '1', 'Ariel', 'Common', '{}')"
    )
    db.connection.execute(
        "INSERT INTO collection_items (card_id, finish, quantity, updated_at) "
        "VALUES ('TFC-001', 'regular', 1, '2026-04-26T00:00:00Z')"
    )
    db.connection.commit()

    db.connection.executescript(_MIGRATION_010_SQL)

    cards = db.connection.execute("SELECT card_id FROM cards").fetchall()
    assert [c[0] for c in cards] == ["TFC-001"]
    items = db.connection.execute("SELECT card_id FROM collection_items").fetchall()
    assert [i[0] for i in items] == ["TFC-001"]
