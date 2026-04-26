"""Plain dataclasses for domain types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CardSet:
    set_code: str
    name: str
    total_cards: int
    released_on: str | None = None
    icon_url: str | None = None


@dataclass(frozen=True)
class Card:
    card_id: str
    set_code: str
    collector_number: str
    name: str
    rarity: str
    subtitle: str | None = None
    ink_color: str | None = None
    cost: int | None = None
    inkable: bool | None = None
    card_type: str | None = None
    body_text: str | None = None
    image_url: str | None = None
    api_payload: str = "{}"


@dataclass(frozen=True)
class CollectionItem:
    card_id: str
    finish: str
    quantity: int
    finish_label: str | None = None
    notes: str | None = None
    id: int | None = None


@dataclass(frozen=True)
class Binder:
    name: str
    set_code: str | None = None
    finish: str | None = None
    notes: str | None = None
    id: int | None = None
