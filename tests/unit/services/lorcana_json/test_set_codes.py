"""LorcanaJSON numeric set-code → lorscan 3-letter code map."""

from __future__ import annotations

import pytest

from lorscan.services.lorcana_json.set_codes import (
    LORCANA_JSON_SET_CODE_MAP,
    to_lorscan_set_code,
)


def test_known_sets_round_trip():
    """Numeric set codes map to the 3-letter codes lorscan uses for card_ids.

    Order follows the official Ravensburger numbering, NOT alphabetical
    or release-date-within-year. Confirmed against
    https://lorcanajson.org and Ravensburger's set list.
    """
    assert to_lorscan_set_code("1") == "TFC"   # The First Chapter
    assert to_lorscan_set_code("2") == "ROF"   # Rise of the Floodborn
    assert to_lorscan_set_code("3") == "ITI"   # Into the Inklands
    assert to_lorscan_set_code("4") == "URS"   # Ursula's Return
    assert to_lorscan_set_code("5") == "SSK"   # Shimmering Skies
    assert to_lorscan_set_code("6") == "AZS"   # Azurite Sea
    assert to_lorscan_set_code("7") == "ARI"   # Archazia's Island
    assert to_lorscan_set_code("8") == "ROJ"   # Reign of Jafar
    assert to_lorscan_set_code("9") == "FAB"   # Fabled
    assert to_lorscan_set_code("10") == "WHI"  # Whispers in the Well
    assert to_lorscan_set_code("11") == "WIN"  # Winterspell
    assert to_lorscan_set_code("12") == "WUN"  # Wilds Unknown


def test_illumineers_quest_passthrough():
    """Q1 etc. are already friendly codes; pass through unchanged."""
    assert to_lorscan_set_code("Q1") == "Q1"


def test_unknown_set_raises():
    with pytest.raises(KeyError):
        to_lorscan_set_code("99999")


def test_map_is_bijective():
    """Each 3-letter code must map back to exactly one numeric code."""
    inverse: dict[str, str] = {}
    for numeric, friendly in LORCANA_JSON_SET_CODE_MAP.items():
        assert friendly not in inverse, f"Duplicate friendly code: {friendly}"
        inverse[friendly] = numeric
