"""Strict JSON parsing of Claude's recognition response."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

VALID_FINISHES = {"regular", "cold_foil", "promo", "enchanted"}
VALID_CONFIDENCES = {"high", "medium", "low"}
VALID_PAGE_TYPES = {"binder_3x3", "binder_3x4", "loose_layout", "single_card"}


class ParseError(ValueError):
    """The model's response could not be parsed into a ParsedScan."""


@dataclass(frozen=True)
class ParsedCard:
    grid_position: str
    name: str | None
    subtitle: str | None
    set_hint: str | None
    collector_number: str | None
    ink_color: str | None
    finish: str
    confidence: str
    candidates: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedScan:
    page_type: str
    cards: list[ParsedCard]
    issues: list[str] = field(default_factory=list)


def parse_response(raw: str) -> ParsedScan:
    """Parse a Claude response string into a ParsedScan.

    Tolerant of: leading/trailing prose, ```json fences. Rejects: garbage
    that doesn't contain a JSON object.
    """
    payload = _extract_json(raw)
    if payload is None:
        raise ParseError("No JSON object found in response.")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise ParseError(f"Invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ParseError("Top-level JSON must be an object.")

    page_type = data.get("page_type")
    if page_type not in VALID_PAGE_TYPES:
        raise ParseError(f"Invalid or missing page_type: {page_type!r}")

    cards_raw = data.get("cards")
    if not isinstance(cards_raw, list):
        raise ParseError("Missing 'cards' array.")

    cards = [_parse_card(item) for item in cards_raw]
    issues = data.get("issues") or []
    if not isinstance(issues, list):
        issues = []

    return ParsedScan(page_type=page_type, cards=cards, issues=list(issues))


def _parse_card(item: dict) -> ParsedCard:
    if not isinstance(item, dict):
        raise ParseError("Card entry must be an object.")
    grid_position = item.get("grid_position")
    if not isinstance(grid_position, str):
        raise ParseError("Card missing required string 'grid_position'.")
    confidence = item.get("confidence")
    if confidence not in VALID_CONFIDENCES:
        raise ParseError(f"Invalid or missing confidence: {confidence!r}")

    finish = item.get("finish") or "regular"
    if finish not in VALID_FINISHES:
        finish = "regular"

    candidates = item.get("candidates") or []
    if not isinstance(candidates, list):
        candidates = []

    return ParsedCard(
        grid_position=grid_position,
        name=item.get("name"),
        subtitle=item.get("subtitle"),
        set_hint=item.get("set_hint"),
        collector_number=(str(item["collector_number"])
                          if item.get("collector_number") is not None else None),
        ink_color=item.get("ink_color"),
        finish=finish,
        confidence=confidence,
        candidates=candidates,
    )


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _extract_json(raw: str) -> str | None:
    """Return the JSON object substring from raw, or None if not found."""
    raw = raw.strip()
    if not raw:
        return None

    # Strip markdown code fence if present.
    fence_match = _FENCE_RE.search(raw)
    if fence_match:
        raw = fence_match.group(1).strip()

    # If the whole string looks like JSON already, use it.
    if raw.startswith("{") and raw.endswith("}"):
        return raw

    # Otherwise, find the first balanced { ... } substring.
    start = raw.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start:i + 1]
    return None
