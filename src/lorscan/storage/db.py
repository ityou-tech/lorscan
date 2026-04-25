"""SQLite Database wrapper + forward-only migration runner."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path


class Database:
    """Owns one sqlite3 connection and the migration runner.

    All SQL in lorscan lives behind this class. Services and routes
    receive typed domain objects, never raw rows.
    """

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    @classmethod
    def connect(cls, path: str | Path) -> Database:
        conn = sqlite3.connect(str(path), detect_types=sqlite3.PARSE_DECLTYPES)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            if str(path) != ":memory:":
                conn.execute("PRAGMA journal_mode = WAL")
            conn.row_factory = sqlite3.Row
        except Exception:
            conn.close()
            raise
        return cls(conn)

    def close(self) -> None:
        self.connection.close()

    def migrate(self) -> None:
        """Apply pending migrations in alphabetical order. Idempotent.

        A failed `executescript` does NOT mark its version as applied —
        the exception propagates and the next run will retry that migration.
        """
        self._ensure_migrations_table()
        applied = self._applied_versions()

        for migration in self._discover_migrations():
            version = migration.name.removesuffix(".sql")
            if version in applied:
                continue
            sql = migration.read_text()
            self.connection.executescript(sql)
            self.connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(UTC).isoformat()),
            )
            self.connection.commit()

    def _ensure_migrations_table(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        )
        if cursor.fetchone() is None:
            cursor.execute(
                "CREATE TABLE schema_migrations ("
                "  version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            self.connection.commit()

    def _applied_versions(self) -> set[str]:
        cursor = self.connection.cursor()
        cursor.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cursor.fetchall()}

    @staticmethod
    def _discover_migrations() -> list[Traversable]:
        package = resources.files("lorscan.storage.migrations")
        files = [f for f in package.iterdir() if f.name.endswith(".sql")]
        return sorted(files, key=lambda f: f.name)
