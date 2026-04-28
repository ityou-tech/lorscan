"""Map LorcanaJSON card dicts to lorscan's internal CardRecord shape."""

from __future__ import annotations

import json
from pathlib import Path

from lorscan.services.lorcana_json.mapper import (
    CardRecord,
    is_main_set_card,
    map_lorcana_json_card,
    map_lorcana_json_payload,
)

FIXTURE = Path(__file__).parents[3] / "fixtures" / "lorcana_json" / "allCards.subset.json"


def test_card_id_derivation_is_stable():
    """card_id must be `<3-letter-set>-<NNN>` (3-digit zero-pad) to preserve
    referential integrity with existing collection_items rows that were
    written by the prior lorcana-api.com importer."""
    payload = json.loads(FIXTURE.read_text())
    raw = next(c for c in payload["cards"] if c["setCode"] == "1")
    rec = map_lorcana_json_card(raw)
    assert rec.card_id == f"TFC-{int(raw['number']):03d}"
    # collector_number itself stays unpadded for display.
    assert rec.collector_number == str(raw["number"])


def test_card_id_zero_pads_low_collector_numbers():
    """Cards 1-99 zero-pad to 3 digits in card_id — matches the legacy
    lorcana-api.com Unique_ID format the user's existing rows reference."""
    raw = {
        "setCode": "1", "number": 7,
        "name": "Stitch", "fullName": "Stitch - Carefree Surfer",
        "type": "Character", "rarity": "Common", "cost": 4, "color": "Ruby",
    }
    rec = map_lorcana_json_card(raw)
    assert rec.card_id == "TFC-007"
    assert rec.collector_number == "7"


def test_card_id_does_not_pad_above_99():
    """Numbers >= 100 already have 3 digits and are kept as-is."""
    raw = {
        "setCode": "1", "number": 127,
        "name": "Tigger", "fullName": "Tigger - Wonderful Thing",
        "type": "Character", "rarity": "Rare", "cost": 5, "color": "Ruby",
    }
    rec = map_lorcana_json_card(raw)
    assert rec.card_id == "TFC-127"


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
        # >204 numbers are 3 digits already; card_id ends with the
        # number verbatim once zero-padding is applied.
        assert rec.card_id.endswith(f"-{int(raw['number']):03d}")


def test_set_12_wilds_unknown_imports():
    """Set 12 cards (Wilds Unknown, releases May 2026) must not be
    treated as 'unknown set'."""
    raw = {
        "setCode": "12",
        "number": 1,
        "name": "Buzz",
        "fullName": "Buzz Lightyear - Space Ranger",
        "type": "Character",
        "rarity": "Common",
        "cost": 3,
        "color": "Steel",
    }
    rec = map_lorcana_json_card(raw)
    assert rec.set_code == "WUN"
    assert rec.card_id == "WUN-001"


def test_illumineers_quest_imports():
    """Q1 set codes pass through with their friendly form intact."""
    raw = {
        "setCode": "Q1",
        "number": 5,
        "name": "Quest",
        "fullName": "Quest - Sample",
        "type": "Character",
        "rarity": "Common",
        "cost": 1,
        "color": "Amber",
    }
    rec = map_lorcana_json_card(raw)
    assert rec.set_code == "Q1"
    assert rec.card_id == "Q1-005"


def test_unknown_set_code_is_skipped(caplog):
    """A card from an unmapped set logs a warning and is dropped, not raised."""
    import logging
    caplog.set_level(logging.WARNING)
    payload = {
        "metadata": {},
        "sets": {},
        "cards": [
            {"setCode": "999", "number": "1", "name": "X", "fullName": "X",
             "fullIdentifier": "1/204 • EN • 999"},
            {"setCode": "1", "number": "1", "name": "Y", "fullName": "Y - Z",
             "fullIdentifier": "1/204 • EN • 1",
             "type": "Character", "rarity": "Common", "cost": 1, "color": "Amber"},
        ],
    }
    records = map_lorcana_json_payload(payload)
    assert len(records) == 1
    assert records[0].set_code == "TFC"
    assert any("999" in r.message for r in caplog.records)


def test_is_main_set_card_distinguishes_promos():
    """Promo / challenger / D23 variants must not be mapped — they share
    (setCode, number) with the main printing and would collide on
    cards.UNIQUE(set_code, collector_number)."""
    main = {"fullIdentifier": "1/204 • EN • 1"}
    enchanted = {"fullIdentifier": "205/204 • EN • 1"}
    quest = {"fullIdentifier": "1/31 • EN • Q1"}
    promo_p1 = {"fullIdentifier": "1 TFC • EN • 1/P1"}
    challenger_c1 = {"fullIdentifier": "1/C1 • EN • 1"}
    d23 = {"fullIdentifier": "01/D23 • EN • 1"}

    assert is_main_set_card(main)
    assert is_main_set_card(enchanted)
    assert is_main_set_card(quest)
    assert not is_main_set_card(promo_p1)
    assert not is_main_set_card(challenger_c1)
    assert not is_main_set_card(d23)


def test_suffix_variants_get_distinct_card_ids():
    """ITI's 5 Dalmatian Puppies share JSON number=4 but have fullIdentifier
    heads `4a`, `4b`, `4c`, `4d`, `4e`. Each must produce its own card_id
    and collector_number so they render as distinct pockets."""
    raws = []
    for suffix in "abcde":
        raws.append({
            "setCode": "3", "number": 4,
            "name": "Dalmatian Puppy", "fullName": "Dalmatian Puppy - Tail Wagger",
            "fullIdentifier": f"4{suffix}/204 • EN • 3",
            "type": "Character", "rarity": "Common", "cost": 2, "color": "Amber",
        })

    records = [map_lorcana_json_card(r) for r in raws]
    card_ids = sorted(r.card_id for r in records)
    assert card_ids == ["ITI-004a", "ITI-004b", "ITI-004c", "ITI-004d", "ITI-004e"]
    coll_nums = sorted(r.collector_number for r in records)
    assert coll_nums == ["4a", "4b", "4c", "4d", "4e"]


def test_no_suffix_card_unchanged():
    """Normal `1/204` head produces card_id with no suffix."""
    raw = {
        "setCode": "1", "number": 1,
        "name": "Ariel", "fullName": "Ariel - On Human Legs",
        "fullIdentifier": "1/204 • EN • 1",
        "type": "Character", "rarity": "Common", "cost": 4, "color": "Amber",
    }
    rec = map_lorcana_json_card(raw)
    assert rec.card_id == "TFC-001"
    assert rec.collector_number == "1"


def test_payload_filters_out_promos_with_duplicate_key(caplog):
    """A payload mixing main + promo for the same (setCode, number) emits
    only the main card."""
    import logging
    caplog.set_level(logging.INFO)
    payload = {
        "metadata": {},
        "sets": {},
        "cards": [
            {
                "setCode": "1", "number": 1,
                "name": "Ariel", "fullName": "Ariel - On Human Legs",
                "fullIdentifier": "1/204 • EN • 1",
                "type": "Character", "rarity": "Common", "cost": 4, "color": "Amber",
            },
            {
                "setCode": "1", "number": 1,
                "name": "Mickey Mouse", "fullName": "Mickey Mouse - Brave Little Tailor",
                "fullIdentifier": "1 TFC • EN • 1/P1",
                "type": "Character", "rarity": "Promo", "cost": 8, "color": "Steel",
            },
        ],
    }
    records = map_lorcana_json_payload(payload)
    assert len(records) == 1
    assert records[0].name == "Ariel"


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
