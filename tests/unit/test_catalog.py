"""Catalog sync: pulls from lorcana-api.com (mocked) into the database."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx

from lorscan.services.catalog import sync_catalog
from lorscan.storage.db import Database

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "api" / "cards-page-1.json"


async def test_sync_inserts_sets_and_cards(db: Database):
    fixture_payload = json.loads(FIXTURE_PATH.read_text())

    with respx.mock(base_url="https://api.lorcana-api.com") as mock:
        # First page returns our fixture; second page returns empty (end signal).
        mock.get("/cards/all", params={"pagesize": "1000", "page": "1"}).mock(
            return_value=httpx.Response(200, json=fixture_payload)
        )
        mock.get("/cards/all", params={"pagesize": "1000", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )

        result = await sync_catalog(db, base_url="https://api.lorcana-api.com")

    assert result.cards_synced == 4
    assert result.sets_synced == 2

    sets = db.get_sets()
    set_codes = {s.set_code for s in sets}
    assert set_codes == {"1", "99"}

    mickey = db.get_card_by_collector_number("1", "127")
    assert mickey is not None
    assert mickey.name == "Mickey Mouse"
    assert mickey.subtitle == "Brave Little Tailor"
    assert mickey.rarity == "Legendary"
    assert mickey.ink_color == "Steel"
    assert mickey.inkable is False

    a = db.get_card_by_collector_number("99", "1a")
    b = db.get_card_by_collector_number("99", "1b")
    assert a is not None and a.subtitle == "Path A"
    assert b is not None and b.subtitle == "Path B"


async def test_sync_is_idempotent(db: Database):
    fixture_payload = json.loads(FIXTURE_PATH.read_text())

    with respx.mock(base_url="https://api.lorcana-api.com") as mock:
        mock.get("/cards/all", params={"pagesize": "1000", "page": "1"}).mock(
            return_value=httpx.Response(200, json=fixture_payload)
        )
        mock.get("/cards/all", params={"pagesize": "1000", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )

        await sync_catalog(db, base_url="https://api.lorcana-api.com")

    with respx.mock(base_url="https://api.lorcana-api.com") as mock:
        mock.get("/cards/all", params={"pagesize": "1000", "page": "1"}).mock(
            return_value=httpx.Response(200, json=fixture_payload)
        )
        mock.get("/cards/all", params={"pagesize": "1000", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )

        result = await sync_catalog(db, base_url="https://api.lorcana-api.com")

    assert result.cards_synced == 4  # upsert: still 4, no duplicates
    cursor = db.connection.cursor()
    (count,) = cursor.execute("SELECT COUNT(*) FROM cards").fetchone()
    assert count == 4
