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
                set_code = _resolve_set_code(raw)
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


def _resolve_set_code(raw: dict) -> str:
    """Prefer the textual `Set_ID` (e.g., 'ARI'); fall back to the numeric `Set_Num`."""
    set_id = raw.get("Set_ID")
    if isinstance(set_id, str) and set_id.strip():
        return set_id.strip()
    set_num = raw.get("Set_Num")
    if set_num is not None:
        return str(set_num)
    raise KeyError("Set_ID and Set_Num both missing from card payload")


def _resolve_collector_number(raw: dict) -> str:
    """Prefer textual `Card_Number` (preserves suffixes like '1a'); fall back to `Card_Num`."""
    card_number = raw.get("Card_Number")
    if isinstance(card_number, str) and card_number.strip():
        return card_number.strip()
    card_num = raw.get("Card_Num")
    if card_num is not None:
        return str(card_num)
    raise KeyError("Card_Number and Card_Num both missing from card payload")


def _split_name(full_name: str) -> tuple[str, str | None]:
    """Split 'Rhino - Motivational Speaker' into ('Rhino', 'Motivational Speaker').

    Some Lorcana cards (Songs, Locations, single-name characters) have no
    subtitle. For those, returns (full_name, None).
    """
    if " - " in full_name:
        head, _, tail = full_name.partition(" - ")
        return head.strip(), tail.strip() or None
    return full_name.strip(), None


def _parse_card(raw: dict, set_code: str) -> Card:
    """Map a lorcana-api.com card object into our Card dataclass."""
    inkable_raw = raw.get("Inkable")
    inkable = bool(inkable_raw) if inkable_raw is not None else None
    cost = raw.get("Cost")
    cost = int(cost) if cost is not None else None

    full_name = str(raw["Name"])
    name, derived_subtitle = _split_name(full_name)
    # Prefer an explicit Subtitle field if the API ever exposes one;
    # otherwise use what we derived by splitting on " - ".
    subtitle = raw.get("Subtitle") or derived_subtitle

    return Card(
        card_id=str(raw["Unique_ID"]),
        set_code=set_code,
        collector_number=_resolve_collector_number(raw),
        name=name,
        subtitle=subtitle or None,
        rarity=str(raw.get("Rarity") or "Common"),
        ink_color=raw.get("Color") or None,
        cost=cost,
        inkable=inkable,
        card_type=raw.get("Type") or None,
        body_text=raw.get("Body_Text") or None,
        image_url=raw.get("Image") or None,
        api_payload=json.dumps(raw, ensure_ascii=False),
    )
