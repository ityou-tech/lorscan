"""Catalog sync from LorcanaJSON.

The whole catalogue is a single static JSON file at
`lorcanajson.org/files/current/en/allCards.json` (~7-15 MB). One fetch
per `sync-catalog` invocation, no pagination. Idempotent — re-running
upserts the same rows in place.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from lorscan.services.lorcana_json.fetcher import fetch_all_cards
from lorscan.services.lorcana_json.mapper import map_lorcana_json_payload
from lorscan.services.lorcana_json.set_codes import to_lorscan_set_code
from lorscan.storage.db import Database
from lorscan.storage.models import CardSet

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalogSyncResult:
    cards_inserted: int
    sets_seen: int
    unknown_sets_skipped: int


async def sync_catalog(db: Database) -> CatalogSyncResult:
    """Pull the LorcanaJSON catalogue into the local SQLite database."""
    payload = await fetch_all_cards()

    seen_set_codes: set[str] = set()
    raw_sets = payload.get("sets") or {}
    for numeric, set_info in raw_sets.items():
        try:
            friendly = to_lorscan_set_code(str(numeric))
        except KeyError:
            log.warning("Skipping unknown set %s in payload sets dict", numeric)
            continue
        seen_set_codes.add(friendly)
        db.upsert_set(
            CardSet(
                set_code=friendly,
                name=set_info.get("name", f"Set {friendly}"),
                total_cards=0,  # recomputed below
                released_on=set_info.get("releaseDate") or None,
            )
        )

    raw_card_count = len(payload.get("cards", []))
    records = map_lorcana_json_payload(payload)
    unknown_sets_skipped = raw_card_count - len(records)

    cards_inserted = 0
    for rec in records:
        if rec.set_code not in seen_set_codes:
            db.upsert_set(
                CardSet(
                    set_code=rec.set_code,
                    name=f"Set {rec.set_code}",
                    total_cards=0,
                )
            )
            seen_set_codes.add(rec.set_code)
        db.upsert_card_record(rec)
        cards_inserted += 1

    existing_sets = {s.set_code: s for s in db.get_sets()}
    for set_code in seen_set_codes:
        (count,) = db.connection.execute(
            "SELECT COUNT(*) FROM cards WHERE set_code = ?", (set_code,)
        ).fetchone()
        prior = existing_sets.get(set_code)
        db.upsert_set(
            CardSet(
                set_code=set_code,
                name=prior.name if prior else f"Set {set_code}",
                total_cards=int(count),
                released_on=prior.released_on if prior else None,
                icon_url=prior.icon_url if prior else None,
            )
        )

    return CatalogSyncResult(
        cards_inserted=cards_inserted,
        sets_seen=len(seen_set_codes),
        unknown_sets_skipped=unknown_sets_skipped,
    )
