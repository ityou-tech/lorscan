"""Catalog sync from lorcana-api.com."""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet

PAGE_SIZE = 1000


@dataclass(frozen=True)
class SyncResult:
    cards_synced: int
    sets_synced: int


async def sync_catalog(db: Database, *, base_url: str) -> SyncResult:
    """Pull all cards from lorcana-api.com into the local SQLite catalog.

    Idempotent — uses upsert semantics, so re-running is safe.
    """
    sets_seen: dict[str, CardSet] = {}
    cards_total = 0

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        page = 1
        while True:
            response = await client.get(
                "/cards/all", params={"pagesize": str(PAGE_SIZE), "page": str(page)}
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError(
                    f"Expected a JSON array from /cards/all, got {type(payload).__name__}"
                )
            if not payload:
                break

            for raw in payload:
                set_code = str(raw["Set_Num"])
                set_name = raw.get("Set_Name", f"Set {set_code}")
                if set_code not in sets_seen:
                    # Upsert a provisional set row so the FK constraint is satisfied
                    # before we insert any cards for this set.
                    provisional = CardSet(
                        set_code=set_code,
                        name=set_name,
                        total_cards=0,
                    )
                    db.upsert_set(provisional)
                    sets_seen[set_code] = provisional

                card = _parse_card(raw, set_code)
                db.upsert_card(card)
                cards_total += 1

            page += 1

    # Re-compute total_cards per set from actual inserted rows, then update.
    for set_code, partial in sets_seen.items():
        (count,) = db.connection.execute(
            "SELECT COUNT(*) FROM cards WHERE set_code = ?", (set_code,)
        ).fetchone()
        db.upsert_set(
            CardSet(
                set_code=partial.set_code,
                name=partial.name,
                total_cards=int(count),
            )
        )

    return SyncResult(cards_synced=cards_total, sets_synced=len(sets_seen))


def _parse_card(raw: dict, set_code: str) -> Card:
    """Map a lorcana-api.com card object into our Card dataclass."""
    inkable_raw = raw.get("Inkable")
    inkable = bool(inkable_raw) if inkable_raw is not None else None
    cost = raw.get("Cost")
    cost = int(cost) if cost is not None else None

    return Card(
        card_id=str(raw["Unique_ID"]),
        set_code=set_code,
        collector_number=str(raw["Card_Number"]),
        name=str(raw["Name"]),
        subtitle=raw.get("Subtitle") or None,
        rarity=str(raw.get("Rarity") or "Common"),
        ink_color=raw.get("Color") or None,
        cost=cost,
        inkable=inkable,
        card_type=raw.get("Type") or None,
        body_text=raw.get("Body_Text") or None,
        image_url=raw.get("Image") or None,
        api_payload=json.dumps(raw, ensure_ascii=False),
    )
