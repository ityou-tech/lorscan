"""Domain types for a scan result.

Used to be split between `services/recognition/parser.py` (Parsed*) and
`services/matching.py` (MatchResult). Now that recognition is purely visual
(CLIP embeddings, see `services/visual_scan.py`), these types live in one
neutral module that doesn't carry assumptions about how a result was produced.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedCard:
    """One card observed in a scanned photo.

    For CLIP scans, only `grid_position`, `confidence`, and `candidates`
    are populated; the text fields stay None.
    """

    grid_position: str
    name: str | None = None
    subtitle: str | None = None
    set_hint: str | None = None
    collector_number: str | None = None
    ink_color: str | None = None
    finish: str = "regular"
    confidence: str = "low"  # 'high' | 'medium' | 'low'
    candidates: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedScan:
    """The full result of scanning one photo."""

    page_type: str
    cards: list[ParsedCard]
    issues: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MatchResult:
    """How one ParsedCard maps to a catalog row (if at all)."""

    matched_card_id: str | None
    match_method: str
    # 'clip_visual' | 'clip_low_confidence' (the only methods now)
    confidence: str
    candidates: list[dict] = field(default_factory=list)


__all__ = ["MatchResult", "ParsedCard", "ParsedScan"]
