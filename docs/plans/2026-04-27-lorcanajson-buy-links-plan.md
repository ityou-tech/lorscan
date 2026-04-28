# LorcanaJSON Catalog + Marketplace Buy-Links Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Switch the primary catalog source from `lorcana-api.com` to [LorcanaJSON](https://lorcanajson.org), populate Cardmarket / CardTrader / TCGplayer external IDs and URLs on every card, and surface "Buy on Cardmarket (NL sellers)" and "Buy on CardTrader" deep-links on the empty pockets of `/collection`. The links render whenever the card has a URL on file, **regardless of whether Bazaar has a listing**; the user gets to compare prices and seller pools across marketplaces side-by-side.

**Why now:**
- The marketplace-stock plan (`2026-04-26-marketplace-stock-plan.md`) gives us live Bazaar of Magic prices, but a single marketplace is not enough to make a buying decision. Cardmarket has the largest EU seller pool, CardTrader has different stock, and prices/conditions vary across all three. Showing all available links together lets the user make the right call per card.
- LorcanaJSON ships marketplace IDs/URLs out of the box (`externalLinks.cardmarketUrl`, `externalLinks.cardTraderId`, etc.) so the migration *is* the buy-links feature — no separate data merge.
- LorcanaJSON's image URLs come from the official Lorcana app data feed, which should reduce the manual `~/.lorscan/overrides/` workaround documented in the README. Phase 5 audits the win.

**Architecture:**

A new `services/lorcana_json.py` fetches `https://lorcanajson.org/files/current/en/allCards.json` once per `sync-catalog` (single static download, ~5–15 MB). A hand-maintained `LORCANA_JSON_SET_CODE_MAP` translates LorcanaJSON's numeric `setCode` ("1", "2", "Q1", …) into lorscan's friendly 3-letter codes (`TFC`, `ROF`, `Q1`, …). The existing `services/catalog.py` is rewritten to use this source; `lorcana-api.com` is removed entirely. Migration 008 adds nullable `cardmarket_*`, `cardtrader_*`, `tcgplayer_*` columns to `cards`. `services/buy_links.py` builds Cardmarket URLs with the user's preferred filter query string (NL sellers, English, min condition, reputation) read from `config.toml`. `/collection`'s empty-pocket badge gains an inline link icon when a `cardmarket_url` is present.

**Tech stack:**
- Python 3.12, FastAPI, Jinja2, SQLite (via the existing `Database` wrapper, *all SQL lives there*)
- `httpx` for outbound HTTP (already a dep)
- `tomllib` from stdlib for config parsing (already used)
- `respx` for HTTP mocking in tests (already a dev dep)
- pytest-asyncio in `auto` mode

**Conventions (read before starting):**
- `db.py` is the only place SQL lives. Services receive a `Database` instance and call typed methods.
- Tests use `:memory:` SQLite via the `db` fixture in `tests/conftest.py`.
- Commits are small and per-task. Each commit message follows the `type(scope): subject` pattern (`feat(catalog): ...`, `test(catalog): ...`, `feat(buy-links): ...`).
- Run `uv run ruff check src tests` and `uv run pytest` before each commit.
- The `card_id` derivation must stay stable across this migration (formula: `f"{set_code}-{collector_number}"`). Existing rows in `collection_items` and `binders` reference `card_id`. **Do not change the derivation rule** or you will silently orphan every collected card.
- **Import every card LorcanaJSON ships, not just main-set 1-204.** Lorcana sets contain main-set cards (1-204), enchanteds (typically 205-223), iconics, special promo numbers, and separate Illumineer's Quest sets (`Q1`, …). The catalog importer must round-trip all of them — capping at 204 or filtering by rarity is a regression that leaves the user with empty pockets they can never fill. Test for this explicitly (Tasks 4 and 6).
- The set-code map in `set_codes.py` follows official Ravensburger numbering (Set 6 = Azurite Sea, Set 12 = Wilds Unknown), not the README's set-codes table which is a flat list and not in numeric order. Task 12 reconciles the README.

**Reference plans:**
- Sibling plan (must merge first): `docs/plans/2026-04-26-marketplace-stock-plan.md`
- LorcanaJSON schema reference: <https://lorcanajson.org/> ("Format" section)

---

## Pre-work: Verify the marketplace-stock plan has merged

### Task 0: Confirm dependencies

**Files:**
- None modified. Verification only.

**Step 1: Confirm the Bazaar plan landed on this branch's base**

Run:
```bash
git log --oneline | grep -E "(marketplaces|migration 007)" | head -5
```

Expected: at least one commit referencing `marketplaces` migration 007 and the Bazaar adapter. If empty, **stop** and merge `2026-04-26-marketplace-stock-plan.md` first. This plan layers on top of `/collection`'s post-merge state where `/missing` has been deleted and empty-pocket badges already exist.

**Step 2: Confirm the empty-pocket badge template hook exists**

Run:
```bash
grep -rn "empty-pocket" src/lorscan/app/templates/ | head
```

Expected: at least one match in the `_partials/binder.html` (or wherever the per-pocket markup lives post-Bazaar). Take note of the surrounding template structure; Task 10 will reopen this file to add the buy-link icon next to the existing price badge.

**Step 3: No commit**

Pre-work is verification-only. Proceed to Phase 1.

---

## Phase 1 — Schema migration

### Task 1: Migration 008 — external link columns on `cards`

**Files:**
- Create: `src/lorscan/storage/migrations/008_external_links.sql`
- Create: `tests/unit/test_db_migrations_008.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_db_migrations_008.py
"""Migration 008: external-link columns on cards."""

from __future__ import annotations

from lorscan.storage.db import Database


def test_external_link_columns_exist(db: Database):
    cursor = db.connection.execute("PRAGMA table_info(cards)")
    columns = {row["name"] for row in cursor.fetchall()}
    expected = {
        "cardmarket_id",
        "cardmarket_url",
        "cardtrader_id",
        "cardtrader_url",
        "tcgplayer_id",
        "tcgplayer_url",
    }
    missing = expected - columns
    assert not missing, f"Missing columns: {missing}"


def test_external_link_columns_are_nullable(db: Database):
    """A card with no external links should insert without error."""
    db.connection.execute(
        "INSERT INTO cards (card_id, set_code, collector_number, name) "
        "VALUES ('TFC-001', 'TFC', '1', 'Test Card')"
    )
    row = db.connection.execute(
        "SELECT cardmarket_url, cardtrader_url, tcgplayer_url "
        "FROM cards WHERE card_id = 'TFC-001'"
    ).fetchone()
    assert row["cardmarket_url"] is None
    assert row["cardtrader_url"] is None
    assert row["tcgplayer_url"] is None


def test_existing_card_id_index_still_works(db: Database):
    """Migration is purely additive — pre-existing indexes unaffected."""
    cursor = db.connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='index' AND tbl_name='cards'"
    )
    index_names = {row[0] for row in cursor.fetchall()}
    # The exact pre-existing index names depend on earlier migrations; just
    # assert at least one survived.
    assert any("card" in n.lower() for n in index_names)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_db_migrations_008.py -v`
Expected: FAIL — columns don't exist yet.

**Step 3: Write the migration**

Create `src/lorscan/storage/migrations/008_external_links.sql`:

```sql
ALTER TABLE cards ADD COLUMN cardmarket_id  INTEGER;
ALTER TABLE cards ADD COLUMN cardmarket_url TEXT;
ALTER TABLE cards ADD COLUMN cardtrader_id  INTEGER;
ALTER TABLE cards ADD COLUMN cardtrader_url TEXT;
ALTER TABLE cards ADD COLUMN tcgplayer_id   INTEGER;
ALTER TABLE cards ADD COLUMN tcgplayer_url  TEXT;
```

No index is added. The columns are looked up by `card_id` (already indexed), never as a search key.

**Step 4: Re-run test**

Run: `uv run pytest tests/unit/test_db_migrations_008.py -v`
Expected: all 3 tests PASS.

**Step 5: Commit**

```bash
git add src/lorscan/storage/migrations/008_external_links.sql \
        tests/unit/test_db_migrations_008.py
git commit -m "feat(cards): migration 008 adds marketplace ID/URL columns"
```

---

## Phase 2 — Catalog source switch

### Task 2: LorcanaJSON set-code map

**Files:**
- Create: `src/lorscan/services/lorcana_json/__init__.py` (empty)
- Create: `src/lorscan/services/lorcana_json/set_codes.py`
- Create: `tests/unit/services/lorcana_json/__init__.py` (empty)
- Create: `tests/unit/services/lorcana_json/test_set_codes.py`

**Step 1: Write the failing test**

```python
# tests/unit/services/lorcana_json/test_set_codes.py
"""LorcanaJSON numeric set-code → lorscan 3-letter code map."""

from __future__ import annotations

import pytest

from lorscan.services.lorcana_json.set_codes import (
    LORCANA_JSON_SET_CODE_MAP,
    to_lorscan_set_code,
)


def test_known_sets_round_trip():
    """Numeric set codes map to the 3-letter codes lorscan uses for card_ids.

    Order follows the official Ravensburger numbering, NOT alphabetical
    or release-date-within-year. Confirmed against
    https://lorcanajson.org and Ravensburger's set list.
    """
    assert to_lorscan_set_code("1") == "TFC"   # The First Chapter
    assert to_lorscan_set_code("2") == "ROF"   # Rise of the Floodborn
    assert to_lorscan_set_code("3") == "ITI"   # Into the Inklands
    assert to_lorscan_set_code("4") == "URS"   # Ursula's Return
    assert to_lorscan_set_code("5") == "SSK"   # Shimmering Skies
    assert to_lorscan_set_code("6") == "AZS"   # Azurite Sea
    assert to_lorscan_set_code("7") == "ARI"   # Archazia's Island
    assert to_lorscan_set_code("8") == "ROJ"   # Reign of Jafar
    assert to_lorscan_set_code("9") == "FAB"   # Fabled
    assert to_lorscan_set_code("10") == "WHI"  # Whispers in the Well
    assert to_lorscan_set_code("11") == "WIN"  # Winterspell
    assert to_lorscan_set_code("12") == "WUN"  # Wilds Unknown


def test_illumineers_quest_passthrough():
    """Q1 etc. are already friendly codes; pass through unchanged."""
    assert to_lorscan_set_code("Q1") == "Q1"


def test_unknown_set_raises():
    with pytest.raises(KeyError):
        to_lorscan_set_code("99999")


def test_map_is_bijective():
    """Each 3-letter code must map back to exactly one numeric code."""
    inverse: dict[str, str] = {}
    for numeric, friendly in LORCANA_JSON_SET_CODE_MAP.items():
        assert friendly not in inverse, f"Duplicate friendly code: {friendly}"
        inverse[friendly] = numeric
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/services/lorcana_json/test_set_codes.py -v`
Expected: FAIL — module doesn't exist.

**Step 3: Implement**

```python
# src/lorscan/services/lorcana_json/set_codes.py
"""Translate LorcanaJSON's numeric `setCode` to lorscan's 3-letter codes.

LorcanaJSON labels sets numerically as printed on the card ("1" for The
First Chapter, "Q1" for Illumineer's Quest, etc.). lorscan has used
3-letter friendly codes since launch; collection rows reference those
codes via the composite `card_id`. Update this map (and the README's
set-codes table) whenever a new Lorcana set drops.

NOTE on README mismatch: the existing README abbreviates set 10 as
"Whisperwood" and set 11 as "Winter", which predate the official
Ravensburger names "Whispers in the Well" and "Winterspell". The
3-letter codes WHI/WIN are kept stable so existing card_id rows in
collection_items don't orphan; only the human-readable names in the
README's set-codes table need updating (Task 12).
"""

from __future__ import annotations

LORCANA_JSON_SET_CODE_MAP: dict[str, str] = {
    "1":  "TFC",   # The First Chapter         (Aug 2023)
    "2":  "ROF",   # Rise of the Floodborn     (Nov 2023)
    "3":  "ITI",   # Into the Inklands         (Feb 2024)
    "4":  "URS",   # Ursula's Return           (May 2024)
    "5":  "SSK",   # Shimmering Skies          (Aug 2024)
    "6":  "AZS",   # Azurite Sea               (Nov 2024)
    "7":  "ARI",   # Archazia's Island         (Feb 2025)
    "8":  "ROJ",   # Reign of Jafar            (May 2025)
    "9":  "FAB",   # Fabled                    (Aug 2025)
    "10": "WHI",   # Whispers in the Well      (Nov 2025)
    "11": "WIN",   # Winterspell               (Feb 2026)
    "12": "WUN",   # Wilds Unknown             (May 2026)
}


def to_lorscan_set_code(numeric: str) -> str:
    """Map LorcanaJSON's numeric set code to lorscan's 3-letter code.

    Illumineer's Quest codes ("Q1" etc.) pass through unchanged because
    they are already in lorscan's friendly form.

    Raises:
        KeyError: if `numeric` isn't a known set. Caller should log and
            skip the card so an unknown set doesn't silently take down
            the whole sync.
    """
    if numeric.startswith("Q"):
        return numeric
    return LORCANA_JSON_SET_CODE_MAP[numeric]
```

**Step 4: Re-run test**

Run: `uv run pytest tests/unit/services/lorcana_json/test_set_codes.py -v`
Expected: all 4 tests PASS (the round-trip test now covers all 12 main sets plus the IQ passthrough).

**Step 5: Commit**

```bash
git add src/lorscan/services/lorcana_json/__init__.py \
        src/lorscan/services/lorcana_json/set_codes.py \
        tests/unit/services/lorcana_json/__init__.py \
        tests/unit/services/lorcana_json/test_set_codes.py
git commit -m "feat(catalog): LorcanaJSON numeric to friendly set-code map"
```

---

### Task 3: Capture a LorcanaJSON fixture

**Files:**
- Create: `tests/fixtures/lorcana_json/__init__.py` (empty)
- Create: `tests/fixtures/lorcana_json/allCards.subset.json`

**Step 1: Fetch the real upstream**

```bash
mkdir -p tests/fixtures/lorcana_json
curl -sL --user-agent "lorscan-fixture-capture/1.0" \
  https://lorcanajson.org/files/current/en/allCards.json \
  > /tmp/lorcanajson-full.json

wc -c /tmp/lorcanajson-full.json
```

Expected: at least 5 MB.

**Step 2: Reduce to a subset for fast tests**

We don't want a 5 MB fixture in the repo. Cut it down to ~25 cards covering the **collector-number ranges** that actually matter, since lorscan must import the entire range — main set (1-204), enchanteds (typically 205-223), iconics, promos, and Illumineer's Quest. A fixture with only the first card from each set will silently mask bugs where the importer drops anything above 204.

```bash
uv run python - <<'PY'
import json, pathlib
src = json.loads(pathlib.Path("/tmp/lorcanajson-full.json").read_text())

picks = []
seen_setcode_keys = set()  # (setCode, number-bucket) — pick one per bucket

def bucket(card):
    """Group cards into number ranges so we can pick one of each kind."""
    n = card.get("number")
    set_code = str(card.get("setCode", ""))
    if set_code.startswith("Q"):
        return (set_code, "quest")
    try:
        num = int(str(n))
    except (TypeError, ValueError):
        return (set_code, "non-numeric")  # promo with weird id
    if num <= 204:
        return (set_code, "main")
    if num <= 223:
        return (set_code, "enchanted")
    return (set_code, "iconic-or-promo")

# Grab one card per (set, bucket). Prefer cards with externalLinks populated.
candidates = sorted(
    src["cards"],
    key=lambda c: (
        0 if c.get("externalLinks", {}).get("cardmarketUrl") else 1,
        str(c.get("setCode", "")),
        c.get("number", 0),
    ),
)
for card in candidates:
    key = bucket(card)
    if key in seen_setcode_keys:
        continue
    seen_setcode_keys.add(key)
    picks.append(card)

# Make sure we have at least one card with number > 204 — Lorcana enchanted
# slots are critical and the importer must not silently drop them.
have_enchanted = any(
    isinstance(c.get("number"), int) and c["number"] > 204 for c in picks
)
assert have_enchanted, "Fixture must include an enchanted (>204) card"

# Make sure we have at least one card with cardmarketUrl populated.
have_cm = any(c.get("externalLinks", {}).get("cardmarketUrl") for c in picks)
assert have_cm, "Fixture must include a card with a cardmarketUrl"

subset = {
    "metadata": src.get("metadata", {}),
    "sets": src.get("sets", {}),
    "cards": picks,
}
out = pathlib.Path("tests/fixtures/lorcana_json/allCards.subset.json")
out.write_text(json.dumps(subset, indent=2))
print(f"Wrote {out} with {len(picks)} cards")
print(f"Buckets covered: {sorted(seen_setcode_keys)}")
PY
```

Expected: ~20-30 cards (one per (set, bucket)), file size <150 KB. The buckets list printed at the end should include at least one `(SET, 'enchanted')` entry — that's the >204 card the importer needs to handle.

**Step 3: Commit**

```bash
git add tests/fixtures/lorcana_json/
git commit -m "test(catalog): capture LorcanaJSON allCards subset fixture"
```

---

### Task 4: LorcanaJSON fetcher + card mapper

**Files:**
- Create: `src/lorscan/services/lorcana_json/fetcher.py`
- Create: `src/lorscan/services/lorcana_json/mapper.py`
- Create: `tests/unit/services/lorcana_json/test_mapper.py`

**Step 1: Write the failing test (mapper only — fetcher tested in Task 5 with respx)**

```python
# tests/unit/services/lorcana_json/test_mapper.py
"""Map LorcanaJSON card dicts to lorscan's internal CardRecord shape."""

from __future__ import annotations

import json
from pathlib import Path

from lorscan.services.lorcana_json.mapper import (
    CardRecord,
    map_lorcana_json_card,
    map_lorcana_json_payload,
)

FIXTURE = Path(__file__).parents[3] / "fixtures" / "lorcana_json" / "allCards.subset.json"


def test_card_id_derivation_is_stable():
    """card_id must be `<3-letter-set>-<collector-number>` to preserve
    referential integrity with existing collection_items rows."""
    payload = json.loads(FIXTURE.read_text())
    raw = next(c for c in payload["cards"] if c["setCode"] == "1")
    rec = map_lorcana_json_card(raw)
    assert rec.card_id == f"TFC-{raw['number']}"


def test_external_link_fields_propagate():
    payload = json.loads(FIXTURE.read_text())
    raw = next(
        c for c in payload["cards"]
        if c.get("externalLinks", {}).get("cardmarketUrl")
    )
    rec = map_lorcana_json_card(raw)
    assert rec.cardmarket_url == raw["externalLinks"]["cardmarketUrl"]
    assert rec.cardmarket_id == raw["externalLinks"].get("cardmarketId")


def test_missing_external_links_is_none_not_keyerror():
    raw = {
        "setCode": "1",
        "number": "999",
        "name": "Test",
        "fullName": "Test - Sample",
        "type": "Character",
        "rarity": "Common",
        "cost": 1,
        "color": "Amber",
        # No externalLinks at all.
    }
    rec = map_lorcana_json_card(raw)
    assert rec.cardmarket_url is None
    assert rec.cardtrader_url is None
    assert rec.tcgplayer_url is None


def test_high_collector_numbers_are_preserved():
    """Enchanteds (205-223), iconics, and other above-main-set numbers
    must round-trip cleanly. The importer cannot cap at 204."""
    payload = json.loads(FIXTURE.read_text())
    high_cards = [
        c for c in payload["cards"]
        if isinstance(c.get("number"), int) and c["number"] > 204
    ]
    assert high_cards, "Fixture broken: must include at least one >204 card"
    for raw in high_cards:
        rec = map_lorcana_json_card(raw)
        assert int(rec.collector_number) > 204
        # card_id includes the number verbatim so two enchanteds in the
        # same set end up with different card_ids.
        assert rec.card_id.endswith(f"-{raw['number']}")


def test_set_12_wilds_unknown_imports():
    """Set 12 cards (Wilds Unknown, releases May 2026) must not be
    treated as 'unknown set'."""
    raw = {
        "setCode": "12",
        "number": "1",
        "name": "Buzz",
        "fullName": "Buzz Lightyear - Space Ranger",
        "type": "Character",
        "rarity": "Common",
        "cost": 3,
        "color": "Steel",
    }
    rec = map_lorcana_json_card(raw)
    assert rec.set_code == "WUN"
    assert rec.card_id == "WUN-1"


def test_illumineers_quest_imports():
    """Q1 set codes pass through with their friendly form intact."""
    raw = {
        "setCode": "Q1",
        "number": "5",
        "name": "Quest",
        "fullName": "Quest - Sample",
        "type": "Character",
        "rarity": "Common",
        "cost": 1,
        "color": "Amber",
    }
    rec = map_lorcana_json_card(raw)
    assert rec.set_code == "Q1"
    assert rec.card_id == "Q1-5"


def test_unknown_set_code_is_skipped(caplog):
    """A card from an unmapped set logs a warning and is dropped, not raised."""
    payload = {
        "metadata": {},
        "sets": {},
        "cards": [
            {"setCode": "999", "number": "1", "name": "X", "fullName": "X"},
            {"setCode": "1", "number": "1", "name": "Y", "fullName": "Y - Z",
             "type": "Character", "rarity": "Common", "cost": 1, "color": "Amber"},
        ],
    }
    records = map_lorcana_json_payload(payload)
    assert len(records) == 1
    assert records[0].set_code == "TFC"
    assert any("999" in r.message for r in caplog.records)


def test_record_is_a_dataclass():
    rec = CardRecord(
        card_id="TFC-001",
        set_code="TFC",
        collector_number="001",
        name="Test",
        full_name="Test - Subtitle",
        type="Character",
        rarity="Common",
        cost=1,
        ink_color="Amber",
        cardmarket_id=None,
        cardmarket_url=None,
        cardtrader_id=None,
        cardtrader_url=None,
        tcgplayer_id=None,
        tcgplayer_url=None,
        image_url=None,
    )
    assert rec.card_id == "TFC-001"
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/services/lorcana_json/test_mapper.py -v`
Expected: FAIL — modules don't exist.

**Step 3: Implement**

```python
# src/lorscan/services/lorcana_json/fetcher.py
"""Download LorcanaJSON's allCards.json once per sync.

The whole catalogue is a single static JSON file (~5–15 MB). We don't
do incremental sync; the cost of a full refetch is well under 30 s on
a typical home connection and the file's metadata.formatVersion makes
schema-change detection trivial later if we want it.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

LORCANA_JSON_URL = "https://lorcanajson.org/files/current/en/allCards.json"
log = logging.getLogger(__name__)


async def fetch_all_cards(client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Fetch the full LorcanaJSON allCards.json payload.

    Caller may pass a pre-configured `httpx.AsyncClient` (for testing
    via `respx`); otherwise a fresh one is created and closed.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=60.0)
    try:
        log.info("Fetching LorcanaJSON: %s", LORCANA_JSON_URL)
        response = await client.get(LORCANA_JSON_URL)
        response.raise_for_status()
        payload = response.json()
        log.info(
            "LorcanaJSON: %d cards, format v%s",
            len(payload.get("cards", [])),
            payload.get("metadata", {}).get("formatVersion", "?"),
        )
        return payload
    finally:
        if own_client:
            await client.aclose()
```

```python
# src/lorscan/services/lorcana_json/mapper.py
"""Translate LorcanaJSON's card schema to lorscan's CardRecord."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from lorscan.services.lorcana_json.set_codes import (
    LORCANA_JSON_SET_CODE_MAP,
    to_lorscan_set_code,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CardRecord:
    """The flattened shape lorscan stores in the `cards` table."""

    card_id: str
    set_code: str
    collector_number: str
    name: str
    full_name: str
    type: str | None
    rarity: str | None
    cost: int | None
    ink_color: str | None  # 'color' field in LorcanaJSON; rename for clarity
    cardmarket_id: int | None
    cardmarket_url: str | None
    cardtrader_id: int | None
    cardtrader_url: str | None
    tcgplayer_id: int | None
    tcgplayer_url: str | None
    image_url: str | None  # primary front-face image URL


def map_lorcana_json_card(raw: dict[str, Any]) -> CardRecord:
    """Map ONE LorcanaJSON card dict to a CardRecord.

    Raises KeyError if the card's setCode is not in LORCANA_JSON_SET_CODE_MAP
    (callers should catch and skip).
    """
    numeric_set = str(raw["setCode"])
    set_code = to_lorscan_set_code(numeric_set)
    collector_number = str(raw["number"])
    card_id = f"{set_code}-{collector_number}"

    external = raw.get("externalLinks") or {}
    images = raw.get("images") or {}
    image_url = images.get("full") or images.get("foilFull") or images.get("thumbnail")

    return CardRecord(
        card_id=card_id,
        set_code=set_code,
        collector_number=collector_number,
        name=raw.get("name", ""),
        full_name=raw.get("fullName", raw.get("name", "")),
        type=raw.get("type"),
        rarity=raw.get("rarity"),
        cost=raw.get("cost"),
        ink_color=raw.get("color"),
        cardmarket_id=external.get("cardmarketId"),
        cardmarket_url=external.get("cardmarketUrl"),
        cardtrader_id=external.get("cardTraderId"),
        cardtrader_url=external.get("cardTraderUrl"),
        tcgplayer_id=external.get("tcgPlayerId"),
        tcgplayer_url=external.get("tcgPlayerUrl"),
        image_url=image_url,
    )


def map_lorcana_json_payload(payload: dict[str, Any]) -> list[CardRecord]:
    """Map the full allCards.json payload, dropping unknown-set cards.

    Cards from unmapped sets are logged at WARNING and skipped — one bad
    set entry must not abort the whole sync.
    """
    records: list[CardRecord] = []
    for raw in payload.get("cards", []):
        try:
            records.append(map_lorcana_json_card(raw))
        except KeyError as exc:
            log.warning(
                "Skipping card from unmapped set %s (id=%s): %s",
                raw.get("setCode"),
                raw.get("id"),
                exc,
            )
    return records
```

**Step 4: Re-run test**

Run: `uv run pytest tests/unit/services/lorcana_json/test_mapper.py -v`
Expected: all 8 PASS (added: high-collector-numbers, set 12 Wilds Unknown, Illumineer's Quest passthrough).

**Step 5: Commit**

```bash
git add src/lorscan/services/lorcana_json/fetcher.py \
        src/lorscan/services/lorcana_json/mapper.py \
        tests/unit/services/lorcana_json/test_mapper.py
git commit -m "feat(catalog): LorcanaJSON fetcher + card-record mapper"
```

---

### Task 5: Database upsert for CardRecord

**Files:**
- Modify: `src/lorscan/storage/db.py`
- Modify: `tests/unit/test_db.py` (or create if absent)

**Step 1: Inspect the existing `upsert_card` (or equivalent)**

Run: `grep -n "def upsert_card\|def insert_card\|def upsert_cards" src/lorscan/storage/db.py`

There is almost certainly an existing card-upsert method used by the current `services/catalog.py`. Read it. The new method must:
1. Match the existing signature shape so swapping the catalog source doesn't ripple.
2. Accept a `CardRecord` (or list thereof) and write all 6 new external link columns plus the existing ones.
3. Be idempotent (re-running `sync-catalog` is a no-op if nothing changed).

If the existing method takes a dict, keep it taking a dict; the new catalog service can call `dataclasses.asdict(record)` at the boundary. Either design is fine — the goal is **don't change the public surface of `db.py` more than necessary**.

**Step 2: Write the failing test**

```python
# Append to tests/unit/test_db.py (or create fresh)

from lorscan.services.lorcana_json.mapper import CardRecord


def test_upsert_card_writes_external_links(db):
    rec = CardRecord(
        card_id="TFC-042",
        set_code="TFC",
        collector_number="42",
        name="Test",
        full_name="Test - Subtitle",
        type="Character",
        rarity="Common",
        cost=2,
        ink_color="Amber",
        cardmarket_id=12345,
        cardmarket_url="https://www.cardmarket.com/en/Lorcana/Products/Singles/The-First-Chapter/Test-Subtitle",
        cardtrader_id=67890,
        cardtrader_url="https://www.cardtrader.com/cards/test",
        tcgplayer_id=None,
        tcgplayer_url=None,
        image_url="https://example.com/test.avif",
    )
    db.upsert_card(rec)

    row = db.connection.execute(
        "SELECT cardmarket_id, cardmarket_url, cardtrader_id, cardtrader_url, "
        "tcgplayer_id, tcgplayer_url FROM cards WHERE card_id = ?",
        ("TFC-042",),
    ).fetchone()
    assert row["cardmarket_id"] == 12345
    assert row["cardmarket_url"].startswith("https://www.cardmarket.com")
    assert row["cardtrader_id"] == 67890
    assert row["tcgplayer_id"] is None


def test_upsert_card_is_idempotent(db):
    rec = CardRecord(
        card_id="TFC-001",
        set_code="TFC", collector_number="1",
        name="N", full_name="N - F",
        type="Character", rarity="Common", cost=1, ink_color="Amber",
        cardmarket_id=None, cardmarket_url=None,
        cardtrader_id=None, cardtrader_url=None,
        tcgplayer_id=None, tcgplayer_url=None,
        image_url=None,
    )
    db.upsert_card(rec)
    db.upsert_card(rec)
    count = db.connection.execute(
        "SELECT COUNT(*) FROM cards WHERE card_id = ?", ("TFC-001",)
    ).fetchone()[0]
    assert count == 1
```

**Step 3: Run to verify it fails**

Run: `uv run pytest tests/unit/test_db.py -v -k upsert_card`
Expected: FAIL.

**Step 4: Implement / extend `upsert_card`**

In `src/lorscan/storage/db.py`, ensure `upsert_card` writes all six external-link columns. Use `INSERT ... ON CONFLICT(card_id) DO UPDATE SET ...` with explicit columns (no `*`). The new columns belong in both the INSERT column list AND the UPDATE SET clause.

If the existing method accepts a dict-shaped row, also add an `upsert_card_record` overload that takes a `CardRecord` and forwards to it via `dataclasses.asdict`. Don't break callers.

**Step 5: Re-run all `test_db` tests**

Run: `uv run pytest tests/unit/test_db.py -v`
Expected: all PASS, including the two new ones.

**Step 6: Commit**

```bash
git add src/lorscan/storage/db.py tests/unit/test_db.py
git commit -m "feat(storage): upsert_card persists marketplace ID/URL columns"
```

---

### Task 6: Rewrite `services/catalog.py` to use LorcanaJSON

**Files:**
- Modify: `src/lorscan/services/catalog.py`
- Modify: `tests/unit/services/test_catalog.py` (existing tests will need rework)
- Modify: `pyproject.toml` if `lorcana-api.com` was a dep (unlikely but check)

**Step 1: Read the current state**

Run: `cat src/lorscan/services/catalog.py | head -120`

Note the public surface — what `cli.py`'s `sync-catalog` command calls. Whatever functions are imported elsewhere (`sync_catalog()`, `fetch_sets()`, etc.) must keep their names and signatures so `cli.py` and tests don't have to change in this task.

**Step 2: Write the new catalog test**

```python
# tests/unit/services/test_catalog.py — replace/extend

import json
from pathlib import Path

import httpx
import pytest
import respx

from lorscan.services.catalog import sync_catalog
from lorscan.storage.db import Database

FIXTURE = Path(__file__).parents[2] / "fixtures" / "lorcana_json" / "allCards.subset.json"


@pytest.mark.asyncio
async def test_sync_catalog_populates_cards_and_external_links(db: Database):
    payload = json.loads(FIXTURE.read_text())

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://lorcanajson.org/files/current/en/allCards.json").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = await sync_catalog(db)

    assert result.cards_inserted >= 1
    # Spot-check that at least one card's cardmarket_url was written.
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
        mock.get("https://lorcanajson.org/files/current/en/allCards.json").mock(
            return_value=httpx.Response(200, json=payload)
        )
        await sync_catalog(db)

    # Every card with a known set in the fixture must show up in the DB.
    expected_count = sum(
        1 for c in payload["cards"]
        if str(c.get("setCode", "")).startswith("Q")
        or str(c.get("setCode", "")) in {
            "1","2","3","4","5","6","7","8","9","10","11","12"
        }
    )
    actual_count = db.connection.execute(
        "SELECT COUNT(*) FROM cards"
    ).fetchone()[0]
    assert actual_count == expected_count, (
        f"Expected {expected_count} cards from fixture, got {actual_count}"
    )

    # Specifically: at least one card with collector_number > 204 made it.
    high = db.connection.execute(
        "SELECT COUNT(*) FROM cards WHERE CAST(collector_number AS INTEGER) > 204"
    ).fetchone()[0]
    assert high >= 1, "No enchanted/promo cards (>204) imported — main bug"


@pytest.mark.asyncio
async def test_sync_catalog_imports_set_12(db: Database):
    """Set 12 (Wilds Unknown, May 2026) lands as WUN-* card_ids."""
    # Synthesise a payload with only a set-12 card so this test stays
    # green even before the fixture is regenerated post-set-12-release.
    payload = {
        "metadata": {"formatVersion": "test"},
        "sets": {"12": {"name": "Wilds Unknown", "type": "expansion"}},
        "cards": [
            {
                "setCode": "12", "number": "1",
                "name": "Buzz", "fullName": "Buzz Lightyear - Space Ranger",
                "type": "Character", "rarity": "Common",
                "cost": 3, "color": "Steel",
                "externalLinks": {},
            },
            {
                "setCode": "12", "number": "210",
                "name": "Buzz", "fullName": "Buzz Lightyear - Enchanted",
                "type": "Character", "rarity": "Enchanted",
                "cost": 3, "color": "Steel",
                "externalLinks": {},
            },
        ],
    }
    with respx.mock() as mock:
        mock.get("https://lorcanajson.org/files/current/en/allCards.json").mock(
            return_value=httpx.Response(200, json=payload)
        )
        await sync_catalog(db)

    rows = db.connection.execute(
        "SELECT card_id FROM cards WHERE set_code = 'WUN' ORDER BY card_id"
    ).fetchall()
    assert [r["card_id"] for r in rows] == ["WUN-1", "WUN-210"]


@pytest.mark.asyncio
async def test_sync_catalog_is_idempotent(db: Database):
    payload = json.loads(FIXTURE.read_text())
    with respx.mock() as mock:
        mock.get("https://lorcanajson.org/files/current/en/allCards.json").mock(
            return_value=httpx.Response(200, json=payload)
        )
        first = await sync_catalog(db)
        second = await sync_catalog(db)
    # Same payload twice — second call should update zero net rows.
    total = db.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    assert total == first.cards_inserted
    assert second.cards_inserted == 0 or second.cards_updated >= 0
```

**Step 3: Run to verify it fails**

Run: `uv run pytest tests/unit/services/test_catalog.py -v`
Expected: FAIL — sync_catalog still hits lorcana-api.com.

**Step 4: Rewrite `services/catalog.py`**

Replace the body so `sync_catalog(db)`:
1. Calls `lorcana_json.fetcher.fetch_all_cards()`.
2. Calls `lorcana_json.mapper.map_lorcana_json_payload(payload)` to get `list[CardRecord]`.
3. Upserts each via `db.upsert_card`.
4. Also upserts the `sets` dict from the payload into the `sets` table (translate numeric → friendly via `to_lorscan_set_code`).
5. Returns a small result struct: `CatalogSyncResult(cards_inserted, cards_updated, sets_seen, unknown_sets_skipped)`.

Delete every reference to `lorcana-api.com` from this module.

**Step 5: Confirm `cli.py` still works**

Run: `grep -n "from lorscan.services.catalog" src/lorscan/cli.py src/lorscan/app/`
Expected: imports still resolve. If a renamed symbol broke them, fix the import (don't rename back).

**Step 6: Re-run full test suite**

Run: `uv run pytest -v`
Expected: all PASS. Some pre-existing tests that mocked `lorcana-api.com` URLs will need their respx routes rewritten to `lorcanajson.org`. Update them in this commit.

**Step 7: Commit**

```bash
git add src/lorscan/services/catalog.py tests/unit/services/test_catalog.py
git commit -m "feat(catalog): switch primary source to LorcanaJSON"
```

---

### Task 7: Drop `lorcana-api.com` references

**Files:**
- Modify: any file that still references `lorcana-api.com`

**Step 1: Hunt down stragglers**

Run:
```bash
grep -rn "lorcana-api" src/ tests/ docs/ README.md
```

Expected: matches in `README.md` (the "How recognition works" section, the "Manual image overrides" section, the `services/catalog.py` docstring at the top of the project tree). Maybe a stray import or comment.

**Step 2: Replace each reference**

In `README.md`:
- "synced from `lorcana-api.com`" → "synced from `lorcanajson.org`"
- The "Manual image overrides" paragraph still applies in spirit (some images may 404), but the parenthetical "(`lorcana-api.com`)" should become "(`lorcanajson.org`)". Keep the override mechanism — Phase 5 audits whether it's still needed.
- The Lorcast paragraph at the end of "Manual image overrides" can stay; it's still a valid alternative when LorcanaJSON's image URL is dead.

In `src/lorscan/services/catalog.py`: docstring already updated in Task 6.

If any test fixture filename or constant has `lorcana_api` in it, rename to `lorcana_json`.

**Step 3: Sanity-check**

Run:
```bash
grep -rn "lorcana-api" src/ tests/ docs/ README.md
```
Expected: no matches outside historic plan files in `docs/plans/`.

**Step 4: Commit**

```bash
git add -u
git commit -m "refactor(catalog): drop lorcana-api.com references"
```

---

## Phase 3 — Buy-link helpers

### Task 8: Cardmarket URL builder with filter query string

**Files:**
- Create: `src/lorscan/services/buy_links.py`
- Create: `tests/unit/services/test_buy_links.py`

**Step 1: Write the failing test**

```python
# tests/unit/services/test_buy_links.py
"""Cardmarket / CardTrader buy-link builders."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from lorscan.services.buy_links import (
    DEFAULT_CARDMARKET_FILTERS,
    cardmarket_buy_url,
    cardtrader_buy_url,
)

BASE = (
    "https://www.cardmarket.com/en/Lorcana/Products/Singles/"
    "The-First-Chapter/Stitch-Carefree-Surfer-V1"
)


def test_default_filters_match_user_preference():
    """NL sellers, English, min condition Excellent, reputation 'Good'."""
    assert DEFAULT_CARDMARKET_FILTERS == {
        "sellerCountry": 23,    # Netherlands
        "sellerReputation": 4,  # Good and above
        "language": 1,          # English
        "minCondition": 3,      # Excellent and above
    }


def test_url_appends_default_filters():
    url = cardmarket_buy_url(BASE)
    qs = parse_qs(urlsplit(url).query)
    assert qs["sellerCountry"] == ["23"]
    assert qs["language"] == ["1"]
    assert qs["minCondition"] == ["3"]
    assert qs["sellerReputation"] == ["4"]


def test_custom_filters_override_defaults():
    url = cardmarket_buy_url(BASE, filters={"sellerCountry": 21, "language": 5})
    qs = parse_qs(urlsplit(url).query)
    assert qs["sellerCountry"] == ["21"]
    assert qs["language"] == ["5"]
    # Other defaults still applied.
    assert "minCondition" in qs


def test_extra_filters_widen_search():
    """Multiple seller countries: Cardmarket accepts repeated params."""
    url = cardmarket_buy_url(
        BASE,
        filters={"sellerCountry": [23, 5, 7]},  # NL + BE + DE
    )
    qs = parse_qs(urlsplit(url).query)
    assert qs["sellerCountry"] == ["23", "5", "7"]


def test_empty_base_returns_empty_string():
    """A card without a cardmarket_url shouldn't blow up the template."""
    assert cardmarket_buy_url("") == ""
    assert cardmarket_buy_url(None) == ""


def test_cardtrader_url_is_passthrough():
    """CardTrader URLs from LorcanaJSON are already complete."""
    base = "https://www.cardtrader.com/cards/stitch-carefree-surfer"
    assert cardtrader_buy_url(base) == base
    assert cardtrader_buy_url(None) == ""
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/services/test_buy_links.py -v`
Expected: FAIL — module doesn't exist.

**Step 3: Implement**

```python
# src/lorscan/services/buy_links.py
"""Build deep-links into external card marketplaces.

Cardmarket has a query-string filter system (sellerCountry, sellerReputation,
language, minCondition, isFoil...). We surface a small, opinionated default
optimised for a Netherlands-based collector and let `config.toml` override
each value. Filters can also be lists, in which case the param is repeated
(Cardmarket honours repeated params for sellerCountry and language).

CardTrader and TCGplayer URLs are passed through unchanged — neither
exposes filter parameters that lorscan currently surfaces.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from urllib.parse import urlencode

# Cardmarket numeric codes (from their filter UI):
#   sellerCountry: 21=Belgium, 5=Germany, 7=France, 23=Netherlands, 33=UK, ...
#   sellerReputation: 1=any, 2=neutral+, 3=ok+, 4=good+, 5=very-good+, 6=outstanding
#   language: 1=English, 2=French, 3=German, 4=Spanish, 5=Italian, ...
#   minCondition: 1=Mint, 2=Near Mint, 3=Excellent, 4=Good, 5=Light Played, ...
DEFAULT_CARDMARKET_FILTERS: dict[str, int | list[int]] = {
    "sellerCountry": 23,    # Netherlands
    "sellerReputation": 4,  # Good and above
    "language": 1,          # English
    "minCondition": 3,      # Excellent and above
}


def cardmarket_buy_url(
    base_url: str | None,
    *,
    filters: Mapping[str, int | Sequence[int]] | None = None,
) -> str:
    """Append filter query string to a Cardmarket product URL.

    `filters` overlays on top of `DEFAULT_CARDMARKET_FILTERS`; pass a list
    to repeat a param (e.g. `{"sellerCountry": [23, 5]}` for NL+DE).
    Returns "" if `base_url` is falsy so templates can render conditionally.
    """
    if not base_url:
        return ""

    merged: dict[str, int | Sequence[int]] = dict(DEFAULT_CARDMARKET_FILTERS)
    if filters:
        merged.update(filters)

    pairs: list[tuple[str, str]] = []
    for key, value in merged.items():
        if isinstance(value, (list, tuple)):
            for v in value:
                pairs.append((key, str(v)))
        else:
            pairs.append((key, str(value)))

    return f"{base_url}?{urlencode(pairs)}"


def cardtrader_buy_url(base_url: str | None) -> str:
    """Pass-through; LorcanaJSON's cardTraderUrl is already complete."""
    return base_url or ""
```

**Step 4: Re-run test**

Run: `uv run pytest tests/unit/services/test_buy_links.py -v`
Expected: all 6 PASS.

**Step 5: Commit**

```bash
git add src/lorscan/services/buy_links.py \
        tests/unit/services/test_buy_links.py
git commit -m "feat(buy-links): Cardmarket URL builder with NL-default filters"
```

---

### Task 9: Wire user-configurable filters into `config.toml`

**Files:**
- Modify: `src/lorscan/config.py`
- Modify: `tests/unit/test_config.py` (or create)
- Modify: `README.md` (config snippet section)

**Step 1: Inspect current config**

Run: `cat src/lorscan/config.py`

Note the existing config structure (probably a dataclass loaded from `~/.lorscan/config.toml` and/or env vars). The new section is `[buy_links.cardmarket]`.

**Step 2: Write the failing test**

```python
# tests/unit/test_config.py — append

import tomllib

from lorscan.config import Config, load_config


def test_default_buy_link_filters(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("")  # empty — pure defaults
    cfg = load_config(cfg_path)
    assert cfg.buy_links.cardmarket_filters == {
        "sellerCountry": 23,
        "sellerReputation": 4,
        "language": 1,
        "minCondition": 3,
    }


def test_user_overrides_partial(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[buy_links.cardmarket]\n'
        'sellerCountry = [23, 5]   # NL + DE\n'
        'minCondition  = 2          # near-mint+\n'
    )
    cfg = load_config(cfg_path)
    f = cfg.buy_links.cardmarket_filters
    assert f["sellerCountry"] == [23, 5]
    assert f["minCondition"] == 2
    # Unmentioned keys keep their defaults.
    assert f["language"] == 1
    assert f["sellerReputation"] == 4
```

**Step 3: Run to verify it fails**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: FAIL.

**Step 4: Extend `config.py`**

Add a `BuyLinksConfig` nested dataclass with a single `cardmarket_filters: dict[str, int | list[int]]` field. Default = `DEFAULT_CARDMARKET_FILTERS` (import from `services/buy_links.py`). Merge user overrides on top. Wire into the top-level `Config` dataclass.

**Step 5: Re-run test**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: PASS.

**Step 6: Commit**

```bash
git add src/lorscan/config.py tests/unit/test_config.py
git commit -m "feat(config): user-configurable cardmarket buy-link filters"
```

---

## Phase 4 — UI integration on `/collection`

### Task 10: Add buy-link icon to empty-pocket badge

**Files:**
- Modify: the `_partials/binder.html` (or whichever partial renders the per-pocket cell post-Bazaar merge)
- Modify: `src/lorscan/app/routes/collection.py` (pass buy-link helpers to template)
- Modify: `src/lorscan/app/static/css/collection.css` (or equivalent)
- Modify: `tests/integration/test_routes_smoke.py`

**Step 1: Re-confirm template structure**

Run:
```bash
grep -rn "empty-pocket\|missing-cell\|pocket-empty" src/lorscan/app/templates/_partials/
```

Inspect the section that renders the empty-pocket marker post-Bazaar. It should already have a `{% if listing %}` price-badge block from the marketplace plan; the new block hangs off the same card record.

**Step 2: Pass buy-link config & helper into the route**

In `src/lorscan/app/routes/collection.py`'s collection-index handler, add to the template context:

```python
from lorscan.services.buy_links import cardmarket_buy_url

return templates.TemplateResponse(
    "collection/index.html",
    {
        "request": request,
        # ... existing keys ...
        "cardmarket_filters": config.buy_links.cardmarket_filters,
    },
)
```

Register `cardmarket_buy_url` as a Jinja global once at app startup:

```python
# in app/main.py (or wherever templates is built)
from lorscan.services.buy_links import cardmarket_buy_url, cardtrader_buy_url

templates.env.globals["cardmarket_buy_url"] = cardmarket_buy_url
templates.env.globals["cardtrader_buy_url"] = cardtrader_buy_url
```

**Step 3: Modify the binder partial**

Inside the empty-pocket block, after the existing Bazaar price badge (if any):

```jinja
{% if card.cardmarket_url %}
<a class="buy-link buy-link--cardmarket"
   href="{{ cardmarket_buy_url(card.cardmarket_url, filters=cardmarket_filters) }}"
   target="_blank" rel="noopener"
   title="Buy on Cardmarket (filters: NL sellers, English, Excellent+)">
  CM
</a>
{% endif %}
{% if card.cardtrader_url %}
<a class="buy-link buy-link--cardtrader"
   href="{{ cardtrader_buy_url(card.cardtrader_url) }}"
   target="_blank" rel="noopener"
   title="Buy on CardTrader">
  CT
</a>
{% endif %}
```

**Step 4: Style the icons**

In `src/lorscan/app/static/css/collection.css` (or the existing collection-page stylesheet), add:

```css
.buy-link {
  display: inline-block;
  padding: 0 4px;
  font-size: 0.7rem;
  font-weight: 600;
  text-decoration: none;
  border: 1px solid currentColor;
  border-radius: 3px;
  margin-left: 4px;
  vertical-align: middle;
  opacity: 0.75;
  transition: opacity 0.15s;
}
.buy-link:hover { opacity: 1; }
.buy-link--cardmarket { color: #c00; }
.buy-link--cardtrader { color: #0a6; }
```

The `CM` and `CT` icons render alongside the Bazaar price badge as equal citizens — the user is comparing across marketplaces, not falling back to one when another is missing. The Bazaar badge keeps its richer treatment (price + currency) because it's the only one with a known live price; the external links carry only the link-out marker.

**Step 5: Add a smoke test**

Append to `tests/integration/test_routes_smoke.py`:

```python
def test_collection_empty_pocket_shows_cardmarket_link_when_url_present(
    client, db
):
    """Cards with a cardmarket_url should render a CM link in their pocket."""
    db.connection.execute(
        "INSERT INTO sets (set_code, name) VALUES ('TFC', 'The First Chapter')"
    )
    db.connection.execute(
        "INSERT INTO cards (card_id, set_code, collector_number, name, "
        "cardmarket_url) VALUES (?, ?, ?, ?, ?)",
        ("TFC-001", "TFC", "1", "Test Card",
         "https://www.cardmarket.com/en/Lorcana/Products/Singles/"
         "The-First-Chapter/Test-Card"),
    )
    db.connection.commit()

    response = client.get("/collection")
    assert response.status_code == 200
    assert 'buy-link--cardmarket' in response.text
    assert 'sellerCountry=23' in response.text


def test_collection_pocket_omits_buy_link_when_url_absent(client, db):
    """No cardmarket_url → no CM badge."""
    db.connection.execute(
        "INSERT INTO sets (set_code, name) VALUES ('TFC', 'The First Chapter')"
    )
    db.connection.execute(
        "INSERT INTO cards (card_id, set_code, collector_number, name) "
        "VALUES ('TFC-002', 'TFC', '2', 'Bare')"
    )
    db.connection.commit()

    response = client.get("/collection")
    assert response.status_code == 200
    # The whole row should still render, just without the CM link.
    assert "Bare" in response.text or "TFC-002" in response.text


def test_collection_pocket_shows_buy_links_alongside_bazaar_listing(
    client, db
):
    """Buy links are NOT a fallback — they coexist with a Bazaar listing
    so the user can compare marketplaces side-by-side."""
    db.connection.execute(
        "INSERT INTO sets (set_code, name) VALUES ('TFC', 'The First Chapter')"
    )
    db.connection.execute(
        "INSERT INTO cards (card_id, set_code, collector_number, name, "
        "cardmarket_url, cardtrader_url) VALUES (?, ?, ?, ?, ?, ?)",
        ("TFC-003", "TFC", "3", "Both",
         "https://www.cardmarket.com/en/Lorcana/Products/Singles/X/Both",
         "https://www.cardtrader.com/cards/both"),
    )
    # Insert a Bazaar listing for the same card. Adjust column list to
    # match migration 007's marketplace_listings schema.
    db.connection.execute(
        "INSERT INTO marketplace_listings (marketplace_id, external_id, "
        "card_id, finish, price_cents, currency, in_stock, url, title, "
        "fetched_at) VALUES (1, 'bz-1', 'TFC-003', 'regular', 450, 'EUR', "
        "1, 'https://www.bazaarofmagic.eu/p/x/1', 'Both', "
        "'2026-04-27T00:00:00+00:00')"
    )
    db.connection.commit()

    response = client.get("/collection")
    assert response.status_code == 200
    body = response.text
    # All three marketplace markers visible at once.
    assert "buy-link--cardmarket" in body
    assert "buy-link--cardtrader" in body
    # Whatever class the Bazaar badge uses post-marketplace-plan; the
    # exact selector here may need adjustment after reading the merged
    # template — the assertion is "Bazaar marker is also present".
    assert "€" in body or "bazaar" in body.lower()
```

**Step 6: Run all integration tests**

Run: `uv run pytest tests/integration/ -v`
Expected: all PASS, including the two new ones.

**Step 7: Commit**

```bash
git add src/lorscan/app/templates/_partials/binder.html \
        src/lorscan/app/routes/collection.py \
        src/lorscan/app/main.py \
        src/lorscan/app/static/css/collection.css \
        tests/integration/test_routes_smoke.py
git commit -m "feat(collection): Cardmarket/CardTrader buy-link icons on empty pockets"
```

---

## Phase 5 — Image overrides audit (investigative)

### Task 11: Re-run `index-images` and audit overrides folder

This task may end up a no-op if LorcanaJSON's image URLs are no better than `lorcana-api.com`'s for our specific failure modes. That's a fine outcome — we still want to know.

**Files:**
- Modify: `README.md` (the "Manual image overrides" section, only if findings warrant)

**Step 1: Snapshot the current overrides**

Run:
```bash
ls ~/.lorscan/overrides/ 2>/dev/null | sort > /tmp/overrides-before.txt
wc -l /tmp/overrides-before.txt
```

**Step 2: Force a fresh image-cache rebuild**

```bash
rm -rf ~/.lorscan/cache/images/
uv run lorscan sync-catalog
uv run lorscan index-images 2>&1 | tee /tmp/index-images-log.txt
```

Watch the log for "Skipping card …" warnings (the README's symptom of an unfetchable image URL). Count them:

```bash
grep -c "Skipping card" /tmp/index-images-log.txt
```

**Step 3: Compare against pre-migration baseline**

If there was a baseline log from before the migration, compare. Otherwise just record the count in the commit message.

**Step 4: Test with overrides disabled**

```bash
mv ~/.lorscan/overrides ~/.lorscan/overrides.bak
uv run lorscan index-images 2>&1 | grep -c "Skipping card"
mv ~/.lorscan/overrides.bak ~/.lorscan/overrides
```

Compare to step 2's count. Cards that no longer skip when overrides are absent are ones where LorcanaJSON's image URL works and the override is no longer needed.

**Step 5: Update README if findings are notable**

If the skip count dropped substantially, update the "Manual image overrides" section's framing:
- Soften the language ("occasionally hands out image URLs whose hashes 404" stays valid in spirit, but the data source changed).
- Add a one-liner: "After the LorcanaJSON migration (April 2026) the override list shrank from N to M; the workaround remains available for the remaining cases."

If nothing changed: no edit needed; commit the smoke results in a comment in the next task.

**Step 6: Commit only if there's a doc change**

```bash
git add README.md
git commit -m "docs(readme): note image-override reduction post-LorcanaJSON migration"
```

If no commit: skip and move to Phase 6.

---

## Phase 6 — Documentation

### Task 12: README updates

**Files:**
- Modify: `README.md`

**Step 1: Update the "Setup" and "How recognition works" sections**

Already touched in Task 7 to remove `lorcana-api.com`; double-check accuracy.

**Step 2: Add a new "Buy missing cards" section after "Marketplace stock"**

```markdown
## Buy missing cards

Every card in the catalog carries direct links to its Cardmarket,
CardTrader, and TCGplayer product pages (sourced from LorcanaJSON's
`externalLinks` block). On `/collection`, empty pockets show small
`CM` / `CT` icons next to any Bazaar price badge — clicking opens
the marketplace product page with your preferred filters pre-applied.

The default Cardmarket filter set is tuned for a Netherlands-based
collector:

| Filter           | Default              |
| ---------------- | -------------------- |
| Seller country   | Netherlands (23)     |
| Seller reputation| Good and above (4)   |
| Language         | English (1)          |
| Min condition    | Excellent and above (3) |

Override any of these in `~/.lorscan/config.toml`:

​```toml
[buy_links.cardmarket]
sellerCountry = [23, 5, 21]   # widen to NL + DE + BE
minCondition  = 2              # near-mint and above only
isFoil        = "Y"            # foils only
​```

Pass a list to repeat a query parameter (Cardmarket honours repeated
`sellerCountry` and `language`).
```

**Step 3: Update the "Set codes" table**

The existing table is a flat alphabetical-ish list. Replace with the canonical Ravensburger numeric ordering matching `LORCANA_JSON_SET_CODE_MAP`, and add Set 12:

```markdown
| #  | Code | Name                  |
| -- | ---- | --------------------- |
| 1  | TFC  | The First Chapter     |
| 2  | ROF  | Rise of the Floodborn |
| 3  | ITI  | Into the Inklands     |
| 4  | URS  | Ursula's Return       |
| 5  | SSK  | Shimmering Skies      |
| 6  | AZS  | Azurite Sea           |
| 7  | ARI  | Archazia's Island     |
| 8  | ROJ  | Reign of Jafar        |
| 9  | FAB  | Fabled                |
| 10 | WHI  | Whispers in the Well  |
| 11 | WIN  | Winterspell           |
| 12 | WUN  | Wilds Unknown         |
| Q1 | Q1   | Illumineer's Quest    |
```

Right after the table, add a one-paragraph note about card numbering inside each set:

```markdown
Each main set ships ~204 numbered cards plus higher-numbered enchanteds
(typically 205-223), iconics, and a handful of promos with their own
numbering. `lorscan` imports all of them — when a "missing" pocket on
`/collection` shows an enchanted, it's just another collector number to
hunt down, treated identically to a common.
```

**Step 4: Update the project-structure tree**

Replace:

```
├── catalog.py     # lorcana-api.com sync
```

with:

```
├── catalog.py            # LorcanaJSON sync (sets + cards + external links)
├── lorcana_json/         # LorcanaJSON-specific fetcher, mapper, set-code map
├── buy_links.py          # Cardmarket/CardTrader URL builders
```

**Step 5: Run the full test suite**

Run: `uv run pytest`
Expected: all green.

**Step 6: Lint**

Run: `uv run ruff check src tests`
Expected: clean.

**Step 7: Manual smoke**

```bash
uv run lorscan sync-catalog        # should fetch from lorcanajson.org now
uv run lorscan serve
```

Open <http://localhost:8000/collection>. Confirm:
- Empty pockets in known sets show small `CM` (and `CT` if present) icons.
- Clicking `CM` opens a Cardmarket product page with `?sellerCountry=23&sellerReputation=4&language=1&minCondition=3` in the URL.
- A card with no `cardmarket_url` (rare, mostly newest promos) shows neither icon — the page doesn't crash.
- **For a card that has both a Bazaar listing and a Cardmarket URL: all three appear together (Bazaar price badge + `CM` + `CT`).** The buy links are not gated on Bazaar being absent.
- Existing Bazaar price badges from the marketplace plan still render and link out correctly.
- **Set 12 (Wilds Unknown) shows up as its own binder** with `WUN-*` card_ids. (If LorcanaJSON hasn't released set 12 data yet at the time you run this, the binder will be absent — not an error. Re-run `sync-catalog` after release.)
- **Enchanteds at collector numbers >204 appear in the binder** for any released set. Spot-check one: e.g. `ROF-224` (Pinocchio, Strings Attached enchanted) should be a real pocket on the ROF binder, not silently dropped.

```bash
# Quick CLI sanity check that high numbers and set 12 made it in:
uv run python -c "
from lorscan.storage.db import Database
from lorscan.config import load_config
db = Database(load_config().db_path)
high = db.connection.execute(
    'SELECT COUNT(*) FROM cards WHERE CAST(collector_number AS INTEGER) > 204'
).fetchone()[0]
wun = db.connection.execute(
    \"SELECT COUNT(*) FROM cards WHERE set_code = 'WUN'\"
).fetchone()[0]
print(f'High-number cards (>204): {high}')
print(f'Set 12 (Wilds Unknown) cards: {wun}')
"
```

Expected: dozens of high-number cards across all released sets. Set 12 count depends on whether LorcanaJSON has Wilds Unknown data live yet.

**Step 8: Commit**

```bash
git add README.md
git commit -m "docs(readme): document LorcanaJSON catalog source + buy-link icons"
```

---

## Done — final verification

```bash
uv run pytest -v        # everything green
uv run ruff check src tests
git log --oneline -20   # ~10–12 small commits, all on this branch
```

Open a PR (or merge to main) once the manual smoke passes. The PR description should call out:
- Catalog source switched from `lorcana-api.com` to `lorcanajson.org`.
- 6 new nullable columns on `cards` (additive migration 008).
- New `/collection` empty-pocket icons: `CM` and `CT`.
- New `[buy_links.cardmarket]` config section, defaults tuned for NL.
- Image-override count now N (was M before) — see Task 11 commit (if any).
