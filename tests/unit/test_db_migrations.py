"""Migrations: forward-only, idempotent, version-tracked."""
from __future__ import annotations

import sqlite3

import pytest

from lorscan.storage.db import Database


def test_migrate_creates_all_tables(db: Database):
    cursor = db.connection.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]
    assert tables == [
        "binders", "cards", "collection_items",
        "scan_results", "scans", "schema_migrations", "sets",
    ]


def test_migrate_records_versions(db: Database):
    cursor = db.connection.cursor()
    cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
    versions = [row[0] for row in cursor.fetchall()]
    assert versions == ["001_catalog", "002_collection", "003_scans", "004_binders"]


def test_migrate_is_idempotent(db: Database):
    db.migrate()  # second run should no-op
    cursor = db.connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM schema_migrations")
    (count,) = cursor.fetchone()
    assert count == 4


def test_foreign_keys_are_enforced(db: Database):
    (enabled,) = db.connection.execute("PRAGMA foreign_keys").fetchone()
    assert enabled == 1


def test_collection_items_unique_constraint(db: Database):
    cursor = db.connection.cursor()
    cursor.execute(
        "INSERT INTO sets (set_code, name, total_cards, synced_at) "
        "VALUES ('1', 'TFC', 204, '2026-04-25T00:00:00')"
    )
    cursor.execute(
        "INSERT INTO cards (card_id, set_code, collector_number, name, rarity, api_payload) "
        "VALUES ('c1', '1', '1', 'Mickey', 'Common', '{}')"
    )
    cursor.execute(
        "INSERT INTO collection_items (card_id, finish, quantity, updated_at) "
        "VALUES ('c1', 'regular', 1, '2026-04-25T00:00:00')"
    )
    db.connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute(
            "INSERT INTO collection_items (card_id, finish, quantity, updated_at) "
            "VALUES ('c1', 'regular', 1, '2026-04-25T00:00:00')"
        )
