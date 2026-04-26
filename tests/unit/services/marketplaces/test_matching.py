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


def test_returns_none_when_collector_number_missing(db: Database):
    _seed(db)
    card_id = resolve_listing(
        db,
        set_code="ROF",
        listing=_make_listing(collector_number=None),
    )
    assert card_id is None


def test_returns_none_when_no_catalog_match(db: Database):
    _seed(db)
    card_id = resolve_listing(
        db,
        set_code="ROF",
        listing=_make_listing(collector_number="999"),
    )
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
