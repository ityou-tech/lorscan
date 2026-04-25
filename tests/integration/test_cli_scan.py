"""End-to-end: lorscan scan <photo> identifies cards via stubbed Claude + matching."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from lorscan.cli import scan_command
from lorscan.config import Config
from lorscan.services.recognition.client import RecognitionResult, TokenUsage
from lorscan.services.recognition.parser import parse_response
from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet

FIXTURE = Path(__file__).parent.parent / "fixtures" / "claude" / "good-3x3.json"


@pytest.fixture()
def seeded_db_path(tmp_path: Path) -> Path:
    db_path = tmp_path / "lorscan.db"
    database = Database.connect(str(db_path))
    database.migrate()
    database.upsert_set(CardSet(set_code="1", name="TFC", total_cards=204))
    database.upsert_card(
        Card(
            card_id="tfc-127",
            set_code="1",
            collector_number="127",
            name="Hermes",
            subtitle="Messenger of the Gods",
            rarity="Legendary",
        )
    )
    database.upsert_card(
        Card(
            card_id="tfc-12",
            set_code="1",
            collector_number="12",
            name="Fairy Godmother",
            rarity="Common",
        )
    )
    database.upsert_card(
        Card(
            card_id="tfc-45",
            set_code="1",
            collector_number="45",
            name="Chip the Teacup",
            rarity="Common",
        )
    )
    database.close()
    return db_path


def _fake_recognition_result() -> RecognitionResult:
    parsed = parse_response(FIXTURE.read_text())
    return RecognitionResult(
        parsed=parsed,
        usage=TokenUsage(input_tokens=1500, output_tokens=400),
        request_payload={"cmd": ["claude", "-p", "..."]},
        response_text=FIXTURE.read_text(),
        cost_usd=0.012,
    )


def test_scan_command_prints_grid_table(capsys, tmp_path: Path, seeded_db_path: Path):
    photo = tmp_path / "binder-page.jpg"
    photo.write_bytes(b"\xff\xd8\xff fake jpeg payload")

    config = Config(
        anthropic_api_key="unused-with-cli-path",
        anthropic_model="claude-sonnet-4-6",
        per_scan_budget_usd=0.50,
        monthly_budget_usd=None,
        data_dir=tmp_path,
    )

    with patch("lorscan.cli.identify", return_value=_fake_recognition_result()):
        rc = scan_command(photo_path=photo, config=config, db_path=seeded_db_path)

    assert rc == 0
    captured = capsys.readouterr()
    assert "Hermes" in captured.out
    assert "Fairy Godmother" in captured.out
    assert "Chip the Teacup" in captured.out
    assert "127" in captured.out
    assert "tfc-127" in captured.out
    assert "Cost: $0.0120" in captured.out


def test_scan_command_handles_missing_photo(capsys, tmp_path: Path, seeded_db_path: Path):
    config = Config(
        anthropic_api_key="unused",
        anthropic_model="claude-sonnet-4-6",
        per_scan_budget_usd=0.50,
        monthly_budget_usd=None,
        data_dir=tmp_path,
    )
    rc = scan_command(
        photo_path=tmp_path / "missing.jpg",
        config=config,
        db_path=seeded_db_path,
    )
    assert rc == 2
    assert "photo not found" in capsys.readouterr().err
