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
    import logging
    caplog.set_level(logging.WARNING)
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
