"""SQLite Database wrapper + forward-only migration runner."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from lorscan.services.lorcana_json.mapper import CardRecord
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

    def upsert_card_record(self, rec: CardRecord) -> None:
        """Upsert a LorcanaJSON-shaped CardRecord into the cards table.

        Subtitle is parsed from `full_name` by splitting on the first " - "
        so the existing UI surfaces (`pocket-sub`, scan/detail, CLI listings)
        continue to render an "Ariel — On Human Legs"-style title pair.
        """
        subtitle = rec.full_name.split(" - ", 1)[1] if " - " in rec.full_name else None
        self.connection.execute(
            "INSERT INTO cards (card_id, set_code, collector_number, name, subtitle, "
            "                   rarity, ink_color, cost, inkable, card_type, body_text, "
            "                   image_url, api_payload, "
            "                   cardmarket_id, cardmarket_url, "
            "                   cardtrader_id, cardtrader_url, "
            "                   tcgplayer_id, tcgplayer_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(card_id) DO UPDATE SET "
            "  set_code = excluded.set_code, "
            "  collector_number = excluded.collector_number, "
            "  name = excluded.name, "
            "  subtitle = excluded.subtitle, "
            "  rarity = excluded.rarity, "
            "  ink_color = excluded.ink_color, "
            "  cost = excluded.cost, "
            "  card_type = excluded.card_type, "
            "  image_url = excluded.image_url, "
            "  cardmarket_id = excluded.cardmarket_id, "
            "  cardmarket_url = excluded.cardmarket_url, "
            "  cardtrader_id = excluded.cardtrader_id, "
            "  cardtrader_url = excluded.cardtrader_url, "
            "  tcgplayer_id = excluded.tcgplayer_id, "
            "  tcgplayer_url = excluded.tcgplayer_url",
            (
                rec.card_id,
                rec.set_code,
                rec.collector_number,
                rec.name,
                subtitle,
                rec.rarity or "Unknown",
                rec.ink_color,
                rec.cost,
                None,
                rec.type,
                None,
                rec.image_url,
                "{}",
                rec.cardmarket_id,
                rec.cardmarket_url,
                rec.cardtrader_id,
                rec.cardtrader_url,
                rec.tcgplayer_id,
                rec.tcgplayer_url,
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

    # ---------- scan ops ----------

    def insert_scan(
        self,
        *,
        photo_hash: str,
        photo_path: str,
        binder_set_code: str | None = None,
    ) -> int:
        """Insert a new scan row in 'pending' status. Returns the new id."""
        cursor = self.connection.execute(
            "INSERT INTO scans (photo_hash, photo_path, status, binder_id, "
            "                   page_number, created_at) "
            "VALUES (?, ?, 'pending', NULL, NULL, ?) "
            "ON CONFLICT(photo_hash) DO UPDATE SET "
            "  photo_path = excluded.photo_path, "
            "  status = 'pending', "
            "  created_at = excluded.created_at",
            (photo_hash, photo_path, datetime.now(UTC).isoformat()),
        )
        self.connection.commit()
        # Need to look up the id whether INSERT or UPDATE happened.
        if cursor.lastrowid:
            row = self.connection.execute(
                "SELECT id FROM scans WHERE photo_hash = ?", (photo_hash,)
            ).fetchone()
            return int(row["id"])
        row = self.connection.execute(
            "SELECT id FROM scans WHERE photo_hash = ?", (photo_hash,)
        ).fetchone()
        return int(row["id"])

    def update_scan_completed(
        self,
        scan_id: int,
        *,
        api_request_payload: str | None,
        api_response_payload: str | None,
        cost_usd: float | None,
    ) -> None:
        self.connection.execute(
            "UPDATE scans SET status = 'completed', "
            "  api_request_payload = ?, api_response_payload = ?, "
            "  cost_usd = ?, completed_at = ? "
            "WHERE id = ?",
            (
                api_request_payload,
                api_response_payload,
                cost_usd,
                datetime.now(UTC).isoformat(),
                scan_id,
            ),
        )
        self.connection.commit()

    def update_scan_failed(self, scan_id: int, *, error_message: str) -> None:
        self.connection.execute(
            "UPDATE scans SET status = 'failed', error_message = ?, completed_at = ? WHERE id = ?",
            (error_message, datetime.now(UTC).isoformat(), scan_id),
        )
        self.connection.commit()

    def insert_scan_result(
        self,
        *,
        scan_id: int,
        grid_position: str,
        claude_name: str | None,
        claude_subtitle: str | None,
        claude_collector_number: str | None,
        claude_set_hint: str | None,
        claude_ink_color: str | None,
        claude_finish: str | None,
        confidence: str,
        matched_card_id: str | None,
        match_method: str | None,
        candidates: list[dict] | None = None,
    ) -> int:
        candidates_json = json.dumps(candidates) if candidates else None
        cursor = self.connection.execute(
            "INSERT INTO scan_results "
            "  (scan_id, grid_position, claude_name, claude_subtitle, "
            "   claude_collector_number, claude_set_hint, claude_ink_color, "
            "   claude_finish, confidence, matched_card_id, match_method, "
            "   candidates) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                scan_id,
                grid_position,
                claude_name,
                claude_subtitle,
                claude_collector_number,
                claude_set_hint,
                claude_ink_color,
                claude_finish,
                confidence,
                matched_card_id,
                match_method,
                candidates_json,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid or 0)

    def update_scan_result_match(
        self,
        scan_result_id: int,
        *,
        matched_card_id: str | None,
        match_method: str = "user_corrected",
    ) -> None:
        """Replace the matched_card_id on a scan_result (inline correction)."""
        self.connection.execute(
            "UPDATE scan_results SET matched_card_id = ?, match_method = ? "
            "WHERE id = ?",
            (matched_card_id, match_method, scan_result_id),
        )
        self.connection.commit()

    def get_recent_scans(self, *, limit: int = 10) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            "SELECT id, photo_hash, photo_path, status, binder_id, "
            "       cost_usd, created_at, completed_at "
            "FROM scans ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return list(rows)

    def get_scan(self, scan_id: int) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()

    def get_scan_by_photo_hash(self, photo_hash: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM scans WHERE photo_hash = ?", (photo_hash,)
        ).fetchone()

    def delete_scan_results(self, scan_id: int) -> None:
        """Wipe all scan_results for a scan. Used before re-running a scan
        so the table doesn't accumulate duplicates from prior runs."""
        self.connection.execute("DELETE FROM scan_results WHERE scan_id = ?", (scan_id,))
        self.connection.commit()

    def get_scan_results(self, scan_id: int) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            "SELECT * FROM scan_results WHERE scan_id = ? ORDER BY id",
            (scan_id,),
        ).fetchall()
        return list(rows)

    # ---------- collection ops ----------

    def upsert_collection_item(
        self,
        *,
        card_id: str,
        finish: str = "regular",
        finish_label: str | None = None,
        quantity_delta: int = 1,
    ) -> None:
        """Add `quantity_delta` to an existing item or insert a new one."""
        existing = self.connection.execute(
            "SELECT id, quantity FROM collection_items "
            "WHERE card_id = ? AND finish = ? "
            "  AND COALESCE(finish_label, '') = COALESCE(?, '')",
            (card_id, finish, finish_label),
        ).fetchone()
        now = datetime.now(UTC).isoformat()
        if existing is None:
            self.connection.execute(
                "INSERT INTO collection_items "
                "  (card_id, finish, finish_label, quantity, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (card_id, finish, finish_label, max(quantity_delta, 1), now),
            )
        else:
            new_qty = max(int(existing["quantity"]) + quantity_delta, 0)
            self.connection.execute(
                "UPDATE collection_items SET quantity = ?, updated_at = ? WHERE id = ?",
                (new_qty, now, existing["id"]),
            )
        self.connection.commit()

    def adjust_collection_item(self, item_id: int, *, delta: int) -> int:
        """Bump an existing collection_item's quantity by `delta`.

        Returns the resulting quantity. Caller is responsible for deciding
        whether to delete the row when the result is <= 0; we don't auto-
        delete here because the row may still need to exist briefly while
        the UI re-renders.
        """
        row = self.connection.execute(
            "SELECT id, quantity FROM collection_items WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            return 0
        new_qty = max(int(row["quantity"]) + delta, 0)
        self.connection.execute(
            "UPDATE collection_items SET quantity = ?, updated_at = ? WHERE id = ?",
            (new_qty, datetime.now(UTC).isoformat(), item_id),
        )
        self.connection.commit()
        return new_qty

    def delete_collection_item(self, item_id: int) -> None:
        """Remove a collection_item entirely (any finish, any quantity)."""
        self.connection.execute(
            "DELETE FROM collection_items WHERE id = ?", (item_id,)
        )
        self.connection.commit()

    def get_collection_with_cards(self) -> list[sqlite3.Row]:
        """All collection items joined to the cards table for display."""
        rows = self.connection.execute(
            "SELECT ci.id, ci.card_id, ci.finish, ci.finish_label, ci.quantity, "
            "       c.name, c.subtitle, c.set_code, c.collector_number, c.rarity, "
            "       c.ink_color, s.name AS set_name "
            "FROM collection_items ci "
            "JOIN cards c ON c.card_id = ci.card_id "
            "LEFT JOIN sets s ON s.set_code = c.set_code "
            "ORDER BY c.set_code, c.collector_number"
        ).fetchall()
        return list(rows)

    def get_collection_count(self) -> int:
        (n,) = self.connection.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM collection_items"
        ).fetchone()
        return int(n)

    def get_set_completion(self) -> list[sqlite3.Row]:
        """Per-set: total cards in set + how many distinct ones the user owns."""
        rows = self.connection.execute(
            "SELECT s.set_code, s.name, s.total_cards, "
            "  COUNT(DISTINCT ci.card_id) AS owned "
            "FROM sets s "
            "LEFT JOIN cards c ON c.set_code = s.set_code "
            "LEFT JOIN collection_items ci ON ci.card_id = c.card_id "
            "GROUP BY s.set_code, s.name, s.total_cards "
            "HAVING s.total_cards > 0 "
            "ORDER BY s.set_code"
        ).fetchall()
        return list(rows)

    def get_missing_in_set(self, set_code: str) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            "SELECT c.card_id, c.collector_number, c.name, c.subtitle, c.rarity, "
            "       c.ink_color, c.image_url "
            "FROM cards c "
            "LEFT JOIN collection_items ci ON ci.card_id = c.card_id "
            "WHERE c.set_code = ? AND ci.id IS NULL "
            "ORDER BY c.collector_number",
            (set_code,),
        ).fetchall()
        return list(rows)

    def mark_scan_results_applied(self, scan_id: int, applied_ids: list[int]) -> None:
        if not applied_ids:
            return
        placeholders = ",".join("?" for _ in applied_ids)
        self.connection.execute(
            f"UPDATE scan_results SET user_decision = 'accepted', applied_at = ? "
            f"WHERE scan_id = ? AND id IN ({placeholders})",
            (datetime.now(UTC).isoformat(), scan_id, *applied_ids),
        )
        self.connection.commit()

    # ---------- marketplace ops ----------

    def get_marketplace_by_slug(self, slug: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT id, slug, display_name, base_url, enabled "
            "FROM marketplaces WHERE slug = ?",
            (slug,),
        ).fetchone()

    def upsert_set_category(
        self,
        *,
        marketplace_id: int,
        set_code: str,
        category_id: str,
        category_path: str,
    ) -> None:
        self.connection.execute(
            "INSERT INTO marketplace_set_categories "
            "  (marketplace_id, set_code, category_id, category_path) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(marketplace_id, set_code) DO UPDATE SET "
            "  category_id = excluded.category_id, "
            "  category_path = excluded.category_path",
            (marketplace_id, set_code, category_id, category_path),
        )
        self.connection.commit()

    def get_enabled_set_categories(self, *, marketplace_id: int) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            "SELECT msc.set_code, msc.category_id, msc.category_path "
            "FROM marketplace_set_categories msc "
            "JOIN sets s ON s.set_code = msc.set_code "
            "WHERE msc.marketplace_id = ? "
            "ORDER BY msc.set_code",
            (marketplace_id,),
        ).fetchall()
        return list(rows)

    def upsert_listing(
        self,
        *,
        marketplace_id: int,
        external_id: str,
        card_id: str | None,
        finish: str | None,
        price_cents: int,
        currency: str,
        in_stock: bool,
        url: str,
        title: str,
        fetched_at: str,
    ) -> None:
        self.connection.execute(
            "INSERT INTO marketplace_listings "
            "  (marketplace_id, external_id, card_id, finish, price_cents, "
            "   currency, in_stock, url, title, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(marketplace_id, external_id) DO UPDATE SET "
            "  card_id = excluded.card_id, "
            "  finish = excluded.finish, "
            "  price_cents = excluded.price_cents, "
            "  currency = excluded.currency, "
            "  in_stock = excluded.in_stock, "
            "  url = excluded.url, "
            "  title = excluded.title, "
            "  fetched_at = excluded.fetched_at",
            (
                marketplace_id,
                external_id,
                card_id,
                finish,
                price_cents,
                currency,
                int(in_stock),
                url,
                title,
                fetched_at,
            ),
        )
        self.connection.commit()

    def get_cheapest_in_stock_per_card(self) -> dict[str, dict]:
        """Map card_id -> {price_cents, currency, url, marketplace_id, finish}.

        Picks the cheapest in-stock listing per card across all enabled shops.
        Excludes listings with NULL card_id (unmatched listings).
        """
        rows = self.connection.execute(
            "SELECT ml.card_id, ml.price_cents, ml.currency, ml.url, "
            "       ml.marketplace_id, ml.finish "
            "FROM marketplace_listings ml "
            "JOIN marketplaces m ON m.id = ml.marketplace_id "
            "WHERE ml.in_stock = 1 AND ml.card_id IS NOT NULL AND m.enabled = 1 "
            "AND ml.price_cents = ("
            "  SELECT MIN(ml2.price_cents) "
            "  FROM marketplace_listings ml2 "
            "  JOIN marketplaces m2 ON m2.id = ml2.marketplace_id "
            "  WHERE ml2.card_id = ml.card_id "
            "    AND ml2.in_stock = 1 "
            "    AND m2.enabled = 1"
            ") "
            "ORDER BY ml.id"
        ).fetchall()
        result: dict[str, dict] = {}
        for row in rows:
            cid = row["card_id"]
            if cid in result:
                continue  # tie - keep the first one
            result[cid] = {
                "price_cents": int(row["price_cents"]),
                "currency": row["currency"],
                "url": row["url"],
                "marketplace_id": int(row["marketplace_id"]),
                "finish": row["finish"],
            }
        return result

    def start_marketplace_sweep(self, marketplace_id: int) -> int:
        cursor = self.connection.execute(
            "INSERT INTO marketplace_sweeps "
            "  (marketplace_id, started_at, status) "
            "VALUES (?, ?, 'running')",
            (marketplace_id, datetime.now(UTC).isoformat()),
        )
        self.connection.commit()
        assert cursor.lastrowid is not None, "INSERT failed to produce a lastrowid"
        return int(cursor.lastrowid)

    def finish_marketplace_sweep(
        self,
        sweep_id: int,
        *,
        listings_seen: int,
        listings_matched: int,
        errors: int,
        status: str,
    ) -> None:
        self.connection.execute(
            "UPDATE marketplace_sweeps SET "
            "  finished_at = ?, listings_seen = ?, listings_matched = ?, "
            "  errors = ?, status = ? "
            "WHERE id = ?",
            (
                datetime.now(UTC).isoformat(),
                listings_seen,
                listings_matched,
                errors,
                status,
                sweep_id,
            ),
        )
        self.connection.commit()

    def get_sweep(self, sweep_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM marketplace_sweeps WHERE id = ?", (sweep_id,)
        ).fetchone()

    def get_latest_finished_sweep(self, marketplace_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM marketplace_sweeps "
            "WHERE marketplace_id = ? AND finished_at IS NOT NULL "
            "ORDER BY finished_at DESC LIMIT 1",
            (marketplace_id,),
        ).fetchone()
