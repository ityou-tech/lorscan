"""Suffix-aware matching algorithm — full branch coverage."""
from __future__ import annotations

import pytest

from lorscan.services.matching import MatchResult, match_card
from lorscan.services.recognition.parser import ParsedCard
from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet


def _seed_catalog(db: Database):
    db.upsert_set(CardSet(set_code="1", name="TFC", total_cards=204))
    db.upsert_set(CardSet(set_code="2", name="ROF", total_cards=204))
    db.upsert_set(CardSet(set_code="X", name="Adventure", total_cards=27))

    db.upsert_card(Card(card_id="tfc-127", set_code="1", collector_number="127",
                        name="Mickey Mouse", subtitle="Brave Little Tailor",
                        rarity="Legendary"))
    db.upsert_card(Card(card_id="tfc-12", set_code="1", collector_number="12",
                        name="Fairy Godmother", rarity="Common"))
    db.upsert_card(Card(card_id="rof-12", set_code="2", collector_number="12",
                        name="Fairy Godmother", rarity="Uncommon"))
    db.upsert_card(Card(card_id="x-1a", set_code="X", collector_number="1a",
                        name="Story", subtitle="Path A", rarity="Common"))
    db.upsert_card(Card(card_id="x-1b", set_code="X", collector_number="1b",
                        name="Story", subtitle="Path B", rarity="Common"))


@pytest.fixture()
def seeded_db(db: Database) -> Database:
    _seed_catalog(db)
    return db


def _claude(name: str | None = None, set_hint: str | None = None,
            collector: str | None = None, confidence: str = "high",
            subtitle: str | None = None) -> ParsedCard:
    return ParsedCard(
        grid_position="r1c1", name=name, subtitle=subtitle, set_hint=set_hint,
        collector_number=collector, ink_color=None, finish="regular",
        confidence=confidence, candidates=[],
    )


def test_collector_number_exact_match_with_set_hint(seeded_db: Database):
    claude = _claude(name="Mickey Mouse", set_hint="1", collector="127")
    result = match_card(claude, db=seeded_db)
    assert isinstance(result, MatchResult)
    assert result.matched_card_id == "tfc-127"
    assert result.match_method == "collector_number"
    assert result.confidence == "high"  # not demoted
    assert result.candidates == []


def test_suffix_preserved_when_distinct(seeded_db: Database):
    a = match_card(_claude(name="Story", set_hint="X", collector="1a"), db=seeded_db)
    b = match_card(_claude(name="Story", set_hint="X", collector="1b"), db=seeded_db)
    assert a.matched_card_id == "x-1a"
    assert b.matched_card_id == "x-1b"


def test_name_set_fallback_when_collector_unreadable(seeded_db: Database):
    claude = _claude(name="Mickey Mouse", set_hint="1", collector=None,
                     subtitle="Brave Little Tailor")
    result = match_card(claude, db=seeded_db)
    assert result.matched_card_id == "tfc-127"
    assert result.match_method == "name+set"
    assert result.confidence == "medium"  # demoted from high


def test_ambiguous_suffix_when_set_known_but_collector_missing(seeded_db: Database):
    # Both 1a and 1b share name "Story" in set X — ambiguous.
    claude = _claude(name="Story", set_hint="X", collector=None)
    result = match_card(claude, db=seeded_db)
    assert result.matched_card_id is None
    assert result.match_method == "ambiguous_suffix"
    assert {c["card_id"] for c in result.candidates} == {"x-1a", "x-1b"}


def test_name_only_cross_set_match(seeded_db: Database):
    # "Mickey Mouse" exists only once in the catalog → unique match.
    claude = _claude(name="Mickey Mouse", set_hint=None, collector=None)
    result = match_card(claude, db=seeded_db)
    assert result.matched_card_id == "tfc-127"
    assert result.match_method == "name_only"
    assert result.confidence == "low"


def test_unmatched_when_name_appears_in_multiple_sets(seeded_db: Database):
    # "Fairy Godmother" exists in sets 1 and 2 → no unique cross-set match.
    claude = _claude(name="Fairy Godmother", set_hint=None, collector=None)
    result = match_card(claude, db=seeded_db)
    assert result.matched_card_id is None
    assert result.match_method == "unmatched"


def test_unmatched_when_nothing_known(seeded_db: Database):
    claude = _claude(name=None, set_hint=None, collector=None)
    result = match_card(claude, db=seeded_db)
    assert result.matched_card_id is None
    assert result.match_method == "unmatched"


def test_binder_set_overrides_claude_set_hint(seeded_db: Database):
    """If the parent scan has a binder rule, that set wins over claude_set_hint."""
    claude = _claude(name="Fairy Godmother", set_hint="1", collector="12")
    # Caller supplies binder_set_code="2" — binder rule forces the lookup into set 2.
    result = match_card(claude, db=seeded_db, binder_set_code="2")
    assert result.matched_card_id == "rof-12"
    assert result.match_method == "collector_number"
