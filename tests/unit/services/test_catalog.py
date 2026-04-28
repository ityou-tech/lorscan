"""Catalog sync from LorcanaJSON."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from lorscan.services.catalog import sync_catalog
from lorscan.services.lorcana_json.fetcher import LORCANA_JSON_URL
from lorscan.storage.db import Database

FIXTURE = Path(__file__).parents[2] / "fixtures" / "lorcana_json" / "allCards.subset.json"


@pytest.mark.asyncio
async def test_sync_catalog_populates_cards_and_external_links(db: Database):
    payload = json.loads(FIXTURE.read_text())

    with respx.mock(assert_all_called=True) as mock:
        mock.get(LORCANA_JSON_URL).mock(return_value=httpx.Response(200, json=payload))
        result = await sync_catalog(db)

    assert result.cards_inserted >= 1
    row = db.connection.execute(
        "SELECT cardmarket_url FROM cards WHERE cardmarket_url IS NOT NULL LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["cardmarket_url"].startswith("https://www.cardmarket.com")


@pytest.mark.asyncio
async def test_sync_catalog_imports_every_card_in_payload(db: Database):
    """No card is silently dropped, regardless of collector number.

    Enchanteds (#205+), iconics, promos, and Illumineer's Quest entries
    must all land in the cards table — the importer cannot cap at 204
    or filter by rarity, or users will end up with empty pockets that
    can never be filled."""
    payload = json.loads(FIXTURE.read_text())
    with respx.mock() as mock:
        mock.get(LORCANA_JSON_URL).mock(return_value=httpx.Response(200, json=payload))
        await sync_catalog(db)

    expected_count = sum(
        1 for c in payload["cards"]
        if str(c.get("setCode", "")).startswith("Q")
        or str(c.get("setCode", "")) in {str(i) for i in range(1, 13)}
    )
    actual_count = db.connection.execute(
        "SELECT COUNT(*) FROM cards"
    ).fetchone()[0]
    assert actual_count == expected_count, (
        f"Expected {expected_count} cards from fixture, got {actual_count}"
    )

    high = db.connection.execute(
        "SELECT COUNT(*) FROM cards WHERE CAST(collector_number AS INTEGER) > 204"
    ).fetchone()[0]
    assert high >= 1, "No enchanted/promo cards (>204) imported — main bug"


@pytest.mark.asyncio
async def test_sync_catalog_imports_set_12(db: Database):
    """Set 12 (Wilds Unknown, May 2026) lands as WUN-* card_ids."""
    payload = {
        "metadata": {"formatVersion": "test"},
        "sets": {"12": {"name": "Wilds Unknown", "type": "expansion"}},
        "cards": [
            {
                "setCode": "12", "number": 1,
                "name": "Buzz", "fullName": "Buzz Lightyear - Space Ranger",
                "type": "Character", "rarity": "Common",
                "cost": 3, "color": "Steel",
                "externalLinks": {},
            },
            {
                "setCode": "12", "number": 210,
                "name": "Buzz", "fullName": "Buzz Lightyear - Enchanted",
                "type": "Character", "rarity": "Enchanted",
                "cost": 3, "color": "Steel",
                "externalLinks": {},
            },
        ],
    }
    with respx.mock() as mock:
        mock.get(LORCANA_JSON_URL).mock(return_value=httpx.Response(200, json=payload))
        await sync_catalog(db)

    rows = db.connection.execute(
        "SELECT card_id FROM cards WHERE set_code = 'WUN' ORDER BY card_id"
    ).fetchall()
    assert [r["card_id"] for r in rows] == ["WUN-001", "WUN-210"]


@pytest.mark.asyncio
async def test_sync_catalog_is_idempotent(db: Database):
    payload = json.loads(FIXTURE.read_text())
    with respx.mock() as mock:
        mock.get(LORCANA_JSON_URL).mock(return_value=httpx.Response(200, json=payload))
        await sync_catalog(db)
        first_total = db.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        await sync_catalog(db)
        second_total = db.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    assert first_total > 0
    assert second_total == first_total
