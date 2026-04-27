"""Strict marketplace listing → card_id resolver."""

from __future__ import annotations

from lorscan.services.marketplaces.base import Listing
from lorscan.services.marketplaces.matching import resolve_listing
from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet


def _seed(db: Database) -> None:
    db.upsert_set(CardSet(set_code="ROF", name="Rise of the Floodborn", total_cards=204))
    db.upsert_card(
        Card(
            card_id="rof-224",
            set_code="ROF",
            collector_number="224",
            name="Pinocchio",
            subtitle="Strings Attached",
            rarity="Enchanted",
        )
    )


def _make_listing(*, collector_number: str | None) -> Listing:
    return Listing(
        external_id="9154978",
        title="Pinocchio, Strings Attached (#224) (foil)",
        price_cents=1500,
        currency="EUR",
        in_stock=True,
        url="https://example.com/x",
        finish="foil",
        collector_number=collector_number,
    )


def test_resolves_to_card_id_on_hit(db: Database):
    _seed(db)
    card_id = resolve_listing(
        db,
        set_code="ROF",
        listing=_make_listing(collector_number="224"),
    )
    assert card_id == "rof-224"


def test_falls_back_to_name_when_collector_number_missing(db: Database):
    """When collector_number is absent, the name-based fallback resolves the
    listing via the parsed title (Pinocchio is unique in the seeded set)."""
    _seed(db)
    card_id = resolve_listing(
        db,
        set_code="ROF",
        listing=_make_listing(collector_number=None),
    )
    assert card_id == "rof-224"


def test_returns_none_when_no_catalog_match(db: Database):
    """Strict miss + name-fallback miss → None."""
    _seed(db)
    listing = Listing(
        external_id="9154978",
        title="Some Unknown Card (foil)",
        price_cents=1500,
        currency="EUR",
        in_stock=True,
        url="https://example.com/x",
        finish="foil",
        collector_number="999",
    )
    card_id = resolve_listing(db, set_code="ROF", listing=listing)
    assert card_id is None


def test_returns_none_when_set_unknown(db: Database):
    _seed(db)
    # Same collector number, but the set isn't in our catalog.
    card_id = resolve_listing(
        db,
        set_code="ZZZ",
        listing=_make_listing(collector_number="224"),
    )
    assert card_id is None


def _seed_rich(db: Database) -> None:
    """Catalog with multiple ROF cards covering the matching cases."""
    db.upsert_set(CardSet(set_code="ROF", name="Rise of the Floodborn", total_cards=204))
    # Yzma has TWO cards in ROF — name alone is ambiguous, subtitle resolves it.
    db.upsert_card(Card(card_id="rof-yzma-1", set_code="ROF", collector_number="50",
                        name="Yzma", subtitle="Without Beauty Sleep", rarity="Common"))
    db.upsert_card(Card(card_id="rof-yzma-2", set_code="ROF", collector_number="51",
                        name="Yzma", subtitle="Scary Beyond All Reason", rarity="Rare"))
    # Zero to Hero is a unique song name — no subtitle.
    db.upsert_card(Card(card_id="rof-zth", set_code="ROF", collector_number="100",
                        name="Zero to Hero", subtitle=None, rarity="Uncommon"))


def _make_listing_for(title: str, *, collector_number: str | None = None) -> Listing:
    return Listing(
        external_id="x",
        title=title,
        price_cents=100,
        currency="EUR",
        in_stock=True,
        url="https://example.com/x",
        finish="foil" if "foil" in title else "regular",
        collector_number=collector_number,
    )


def test_name_fallback_matches_unique_song_name(db: Database):
    _seed_rich(db)
    card_id = resolve_listing(
        db, set_code="ROF", listing=_make_listing_for("Zero to Hero (foil)"),
    )
    assert card_id == "rof-zth"


def test_name_fallback_disambiguates_by_subtitle(db: Database):
    _seed_rich(db)
    yzma_a = resolve_listing(
        db, set_code="ROF",
        listing=_make_listing_for("Yzma, Without Beauty Sleep (foil)"),
    )
    yzma_b = resolve_listing(
        db, set_code="ROF",
        listing=_make_listing_for("Yzma, Scary Beyond All Reason (foil)"),
    )
    assert yzma_a == "rof-yzma-1"
    assert yzma_b == "rof-yzma-2"


def test_name_fallback_returns_none_on_ambiguous_no_subtitle(db: Database):
    """If the title has no subtitle but multiple cards share the name, drop."""
    _seed_rich(db)
    card_id = resolve_listing(
        db, set_code="ROF", listing=_make_listing_for("Yzma (foil)"),
    )
    assert card_id is None


def test_name_fallback_strips_errata_and_finish_suffixes(db: Database):
    _seed_rich(db)
    db.upsert_card(Card(
        card_id="rof-bucky", set_code="ROF", collector_number="42",
        name="Bucky", subtitle="Squirrel Squeak Tutor", rarity="Common",
    ))
    card_id = resolve_listing(
        db, set_code="ROF",
        listing=_make_listing_for(
            "Bucky, Squirrel Squeak Tutor (errata version) (foil)"
        ),
    )
    assert card_id == "rof-bucky"


def test_strict_match_still_wins_when_collector_number_present(db: Database):
    """If collector_number is set and matches, we don't fall through to name."""
    _seed_rich(db)
    db.upsert_card(Card(
        card_id="rof-pin", set_code="ROF", collector_number="224",
        name="Pinocchio", subtitle="Strings Attached", rarity="Enchanted",
    ))
    card_id = resolve_listing(
        db, set_code="ROF",
        listing=_make_listing_for(
            "Pinocchio, Strings Attached (#224) (foil)",
            collector_number="224",
        ),
    )
    assert card_id == "rof-pin"


def test_name_fallback_returns_none_when_no_match_in_set(db: Database):
    _seed_rich(db)
    card_id = resolve_listing(
        db, set_code="ROF", listing=_make_listing_for("Mickey Mouse (foil)"),
    )
    assert card_id is None
