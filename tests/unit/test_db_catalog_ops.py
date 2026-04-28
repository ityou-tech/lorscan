"""Catalog operations: upsert + read for sets and cards."""

from __future__ import annotations

from lorscan.services.lorcana_json.mapper import CardRecord
from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet


def test_upsert_set_inserts_then_updates(db: Database):
    db.upsert_set(CardSet(set_code="1", name="The First Chapter", total_cards=204))
    db.upsert_set(CardSet(set_code="1", name="TFC (renamed)", total_cards=204))
    rows = db.get_sets()
    assert len(rows) == 1
    assert rows[0].name == "TFC (renamed)"


def test_upsert_card_inserts_then_updates(db: Database):
    db.upsert_set(CardSet(set_code="1", name="TFC", total_cards=204))
    db.upsert_card(
        Card(card_id="c-127", set_code="1", collector_number="127", name="Mickey", rarity="Common")
    )
    db.upsert_card(
        Card(
            card_id="c-127",
            set_code="1",
            collector_number="127",
            name="Mickey Mouse",
            rarity="Rare",
        )
    )
    found = db.get_card_by_id("c-127")
    assert found is not None
    assert found.name == "Mickey Mouse"
    assert found.rarity == "Rare"


def test_get_card_by_collector_number_with_suffix(db: Database):
    db.upsert_set(CardSet(set_code="X", name="Adventure Set", total_cards=27))
    db.upsert_card(
        Card(card_id="x-1a", set_code="X", collector_number="1a", name="Story A", rarity="Common")
    )
    db.upsert_card(
        Card(card_id="x-1b", set_code="X", collector_number="1b", name="Story B", rarity="Common")
    )

    a = db.get_card_by_collector_number("X", "1a")
    b = db.get_card_by_collector_number("X", "1b")
    assert a is not None and a.card_id == "x-1a"
    assert b is not None and b.card_id == "x-1b"
    assert db.get_card_by_collector_number("X", "1") is None


def test_search_cards_by_name(db: Database):
    db.upsert_set(CardSet(set_code="1", name="TFC", total_cards=204))
    db.upsert_card(
        Card(
            card_id="c1",
            set_code="1",
            collector_number="1",
            name="Mickey Mouse",
            subtitle="Brave Little Tailor",
            rarity="Legendary",
        )
    )
    db.upsert_card(
        Card(
            card_id="c2",
            set_code="1",
            collector_number="2",
            name="Mickey Mouse",
            subtitle="Detective",
            rarity="Rare",
        )
    )

    matches = db.search_cards_by_name("Mickey Mouse")
    assert len(matches) == 2
    matches_in_set = db.search_cards_by_name("Mickey Mouse", set_code="1")
    assert len(matches_in_set) == 2
    miss = db.search_cards_by_name("Donald Duck")
    assert miss == []


def test_upsert_card_record_writes_external_links(db: Database):
    db.upsert_set(CardSet(set_code="TFC", name="The First Chapter", total_cards=204))
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
    db.upsert_card_record(rec)

    row = db.connection.execute(
        "SELECT cardmarket_id, cardmarket_url, cardtrader_id, cardtrader_url, "
        "tcgplayer_id, tcgplayer_url, subtitle FROM cards WHERE card_id = ?",
        ("TFC-042",),
    ).fetchone()
    assert row["cardmarket_id"] == 12345
    assert row["cardmarket_url"].startswith("https://www.cardmarket.com")
    assert row["cardtrader_id"] == 67890
    assert row["tcgplayer_id"] is None
    # subtitle parsed from full_name's "name - subtitle" form
    assert row["subtitle"] == "Subtitle"


def test_upsert_card_record_is_idempotent(db: Database):
    db.upsert_set(CardSet(set_code="TFC", name="The First Chapter", total_cards=204))
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
    db.upsert_card_record(rec)
    db.upsert_card_record(rec)
    count = db.connection.execute(
        "SELECT COUNT(*) FROM cards WHERE card_id = ?", ("TFC-001",)
    ).fetchone()[0]
    assert count == 1


def test_upsert_card_record_handles_full_name_without_subtitle(db: Database):
    """Some cards (Locations, Songs without dash separator) have full_name == name."""
    db.upsert_set(CardSet(set_code="TFC", name="The First Chapter", total_cards=204))
    rec = CardRecord(
        card_id="TFC-100",
        set_code="TFC",
        collector_number="100",
        name="Lonely",
        full_name="Lonely",  # no " - " separator
        type="Character", rarity="Common", cost=1, ink_color="Amber",
        cardmarket_id=None, cardmarket_url=None,
        cardtrader_id=None, cardtrader_url=None,
        tcgplayer_id=None, tcgplayer_url=None,
        image_url=None,
    )
    db.upsert_card_record(rec)
    row = db.connection.execute(
        "SELECT subtitle FROM cards WHERE card_id = 'TFC-100'"
    ).fetchone()
    assert row["subtitle"] is None
