"""SQLite Database wrapper + forward-only migration runner."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from lorscan.storage.models import Card, CardSet


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

    # ---------- catalog ops ----------

    def upsert_set(self, s: CardSet) -> None:
        self.connection.execute(
            "INSERT INTO sets (set_code, name, released_on, total_cards, icon_url, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(set_code) DO UPDATE SET "
            "  name = excluded.name, "
            "  released_on = excluded.released_on, "
            "  total_cards = excluded.total_cards, "
            "  icon_url = excluded.icon_url, "
            "  synced_at = excluded.synced_at",
            (
                s.set_code,
                s.name,
                s.released_on,
                s.total_cards,
                s.icon_url,
                datetime.now(UTC).isoformat(),
            ),
        )
        self.connection.commit()

    def get_sets(self) -> list[CardSet]:
        rows = self.connection.execute(
            "SELECT set_code, name, released_on, total_cards, icon_url FROM sets ORDER BY set_code"
        ).fetchall()
        return [
            CardSet(
                set_code=r["set_code"],
                name=r["name"],
                released_on=r["released_on"],
                total_cards=r["total_cards"],
                icon_url=r["icon_url"],
            )
            for r in rows
        ]

    def upsert_card(self, c: Card) -> None:
        self.connection.execute(
            "INSERT INTO cards (card_id, set_code, collector_number, name, subtitle, "
            "                   rarity, ink_color, cost, inkable, card_type, body_text, "
            "                   image_url, api_payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(card_id) DO UPDATE SET "
            "  set_code = excluded.set_code, "
            "  collector_number = excluded.collector_number, "
            "  name = excluded.name, "
            "  subtitle = excluded.subtitle, "
            "  rarity = excluded.rarity, "
            "  ink_color = excluded.ink_color, "
            "  cost = excluded.cost, "
            "  inkable = excluded.inkable, "
            "  card_type = excluded.card_type, "
            "  body_text = excluded.body_text, "
            "  image_url = excluded.image_url, "
            "  api_payload = excluded.api_payload",
            (
                c.card_id,
                c.set_code,
                c.collector_number,
                c.name,
                c.subtitle,
                c.rarity,
                c.ink_color,
                c.cost,
                int(c.inkable) if c.inkable is not None else None,
                c.card_type,
                c.body_text,
                c.image_url,
                c.api_payload,
            ),
        )
        self.connection.commit()

    def get_card_by_id(self, card_id: str) -> Card | None:
        row = self.connection.execute(
            "SELECT * FROM cards WHERE card_id = ?", (card_id,)
        ).fetchone()
        return self._row_to_card(row)

    def get_card_by_collector_number(self, set_code: str, collector_number: str) -> Card | None:
        row = self.connection.execute(
            "SELECT * FROM cards WHERE set_code = ? AND collector_number = ?",
            (set_code, collector_number),
        ).fetchone()
        return self._row_to_card(row)

    def search_cards_by_name(self, name: str, *, set_code: str | None = None) -> list[Card]:
        if set_code:
            rows = self.connection.execute(
                "SELECT * FROM cards WHERE set_code = ? AND name = ? ORDER BY collector_number",
                (set_code, name),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM cards WHERE name = ? ORDER BY set_code, collector_number",
                (name,),
            ).fetchall()
        return [c for c in (self._row_to_card(r) for r in rows) if c is not None]

    @staticmethod
    def _row_to_card(row: sqlite3.Row | None) -> Card | None:
        if row is None:
            return None
        return Card(
            card_id=row["card_id"],
            set_code=row["set_code"],
            collector_number=row["collector_number"],
            name=row["name"],
            subtitle=row["subtitle"],
            rarity=row["rarity"],
            ink_color=row["ink_color"],
            cost=row["cost"],
            inkable=bool(row["inkable"]) if row["inkable"] is not None else None,
            card_type=row["card_type"],
            body_text=row["body_text"],
            image_url=row["image_url"],
            api_payload=row["api_payload"],
        )
