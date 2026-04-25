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
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway ~/.lorscan/-style directory for tests that touch disk."""
    data_dir = tmp_path / "lorscan-data"
    data_dir.mkdir()
    monkeypatch.setenv("LORSCAN_DATA_DIR", str(data_dir))
    return data_dir
