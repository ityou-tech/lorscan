"""Recognition response parser: strict JSON, lenient extraction, error taxonomy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lorscan.services.recognition.parser import (
    ParsedScan,
    ParseError,
    parse_response,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "claude"


def test_parse_valid_response():
    raw = (FIXTURES / "good-3x3.json").read_text()
    parsed = parse_response(raw)
    assert isinstance(parsed, ParsedScan)
    assert parsed.page_type == "binder_3x3"
    assert len(parsed.cards) == 3
    first = parsed.cards[0]
    assert first.grid_position == "r1c1"
    assert first.name == "Hermes"
    assert first.collector_number == "127"
    assert first.confidence == "high"


def test_parse_strips_markdown_fences():
    raw = "```json\n" + (FIXTURES / "good-3x3.json").read_text() + "\n```"
    parsed = parse_response(raw)
    assert len(parsed.cards) == 3


def test_parse_extracts_first_json_object_when_surrounded_by_prose():
    payload = json.loads((FIXTURES / "good-3x3.json").read_text())
    raw = "Sure! " + json.dumps(payload) + "\nHope that helps."
    parsed = parse_response(raw)
    assert len(parsed.cards) == 3


def test_parse_raises_on_total_garbage():
    raw = (FIXTURES / "malformed.txt").read_text()
    with pytest.raises(ParseError):
        parse_response(raw)


def test_parse_normalizes_missing_optional_fields():
    minimal = json.dumps(
        {
            "page_type": "single_card",
            "cards": [
                {
                    "grid_position": "single",
                    "name": "Mickey",
                    "confidence": "high",
                }
            ],
        }
    )
    parsed = parse_response(minimal)
    card = parsed.cards[0]
    assert card.name == "Mickey"
    assert card.subtitle is None
    assert card.collector_number is None
    assert card.set_hint is None
    assert card.ink_color is None
    assert card.finish == "regular"  # default
    assert card.candidates == []


def test_parse_raises_on_missing_required_fields():
    bad = json.dumps({"cards": [{"name": "Mickey"}]})  # no page_type, no confidence
    with pytest.raises(ParseError):
        parse_response(bad)
