"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from lorscan.storage.db import Database


@pytest.fixture()
def db() -> Database:
    """A fresh in-memory SQLite database with all migrations applied."""
    database = Database.connect(":memory:")
    database.migrate()
    yield database
    database.close()


@pytest.fixture()
def stub_marketplace_listings(db: Database) -> Database:
    """Re-create the `marketplace_listings` table that migration 011 dropped.

    Migrations 009 and 010 still UPDATE/DELETE rows in this table; any test
    that replays those migrations against a fully-migrated db needs the
    table to exist. The stub schema (card_id only) matches the columns the
    historical migration SQL touches.
    """
    db.connection.execute(
        "CREATE TABLE IF NOT EXISTS marketplace_listings (card_id TEXT)"
    )
    return db


@pytest.fixture()
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway ~/.lorscan/-style directory for tests that touch disk."""
    data_dir = tmp_path / "lorscan-data"
    data_dir.mkdir()
    monkeypatch.setenv("LORSCAN_DATA_DIR", str(data_dir))
    return data_dir
