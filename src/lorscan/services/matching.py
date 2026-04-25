"""Suffix-aware card matching against the local catalog.

Implements the algorithm in spec §4.3:
1. collector_number exact match (suffix preserved) when set is known
2. name+set fallback (with subtitle disambig)
3. cross-set name-only fallback
4. unmatched
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lorscan.services.recognition.parser import ParsedCard
from lorscan.storage.db import Database
from lorscan.storage.models import Card

_CONFIDENCE_DEMOTION = {"high": "medium", "medium": "low", "low": "low"}


@dataclass(frozen=True)
class MatchResult:
    matched_card_id: str | None
    match_method: str
    # 'collector_number' | 'name+set' | 'name_only' | 'ambiguous_suffix' | 'unmatched'
    confidence: str
    candidates: list[dict] = field(default_factory=list)


def match_card(
    claude_card: ParsedCard,
    *,
    db: Database,
    binder_set_code: str | None = None,
) -> MatchResult:
    """Match a single ParsedCard against the catalog.

    The 'known set' precedence is: binder_set_code → claude_card.set_hint → none.
    """
    known_set = binder_set_code or claude_card.set_hint
    confidence = claude_card.confidence

    # 1. collector_number + known_set
    if claude_card.collector_number and known_set:
        card = db.get_card_by_collector_number(known_set, claude_card.collector_number)
        if card is not None:
            return MatchResult(
                matched_card_id=card.card_id,
                match_method="collector_number",
                confidence=confidence,
            )

    # 2. name + known_set
    if claude_card.name and known_set:
        rows = db.search_cards_by_name(claude_card.name, set_code=known_set)
        if claude_card.subtitle:
            filtered = [c for c in rows if c.subtitle == claude_card.subtitle]
            if len(filtered) == 1:
                return MatchResult(
                    matched_card_id=filtered[0].card_id,
                    match_method="name+set",
                    confidence=_CONFIDENCE_DEMOTION[confidence],
                )
            elif len(filtered) > 1:
                return MatchResult(
                    matched_card_id=None,
                    match_method="ambiguous_suffix",
                    confidence=confidence,
                    candidates=[_card_summary(c) for c in filtered],
                )
        if len(rows) == 1:
            return MatchResult(
                matched_card_id=rows[0].card_id,
                match_method="name+set",
                confidence=_CONFIDENCE_DEMOTION[confidence],
            )
        if len(rows) > 1:
            return MatchResult(
                matched_card_id=None,
                match_method="ambiguous_suffix",
                confidence=confidence,
                candidates=[_card_summary(c) for c in rows],
            )

    # 3. name-only cross-set (no known_set)
    if claude_card.name:
        rows = db.search_cards_by_name(claude_card.name)
        # 3a. If subtitle is also known, try filtering by it.
        if claude_card.subtitle:
            filtered = [c for c in rows if c.subtitle == claude_card.subtitle]
            if len(filtered) == 1:
                return MatchResult(
                    matched_card_id=filtered[0].card_id,
                    match_method="name_only",
                    confidence="low",
                )
            elif len(filtered) > 1:
                return MatchResult(
                    matched_card_id=None,
                    match_method="ambiguous_suffix",
                    confidence=confidence,
                    candidates=[_card_summary(c) for c in filtered],
                )
        # 3b. Title-only: unique → match. Multiple → surface as candidates so
        # the user can see lorscan recognized the card and disambiguate manually.
        if len(rows) == 1:
            return MatchResult(
                matched_card_id=rows[0].card_id,
                match_method="name_only",
                confidence="low",
            )
        if len(rows) > 1:
            return MatchResult(
                matched_card_id=None,
                match_method="ambiguous_suffix",
                confidence=confidence,
                candidates=[_card_summary(c) for c in rows],
            )

    # 4. unmatched (no name, or no rows for this name at all)
    return MatchResult(
        matched_card_id=None,
        match_method="unmatched",
        confidence=confidence,
    )


def _card_summary(c: Card) -> dict:
    return {
        "card_id": c.card_id,
        "set_code": c.set_code,
        "collector_number": c.collector_number,
        "name": c.name,
        "subtitle": c.subtitle,
    }
