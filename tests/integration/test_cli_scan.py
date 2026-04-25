"""End-to-end: lorscan scan <photo> identifies cards via stubbed Claude + matching."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lorscan.cli import scan_command
from lorscan.config import Config
from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet

FIXTURE = Path(__file__).parent.parent / "fixtures" / "claude" / "good-3x3.json"


class FakeAnthropicMessage:
    def __init__(self, text: str):
        self.content = [type("TB", (), {"type": "text", "text": text})()]
        self.usage = type("U", (), {
            "input_tokens": 1500, "output_tokens": 400,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
        })()


@pytest.fixture()
def seeded_db_path(tmp_path: Path) -> Path:
    db_path = tmp_path / "lorscan.db"
    database = Database.connect(str(db_path))
    database.migrate()
    database.upsert_set(CardSet(set_code="1", name="TFC", total_cards=204))
    database.upsert_card(Card(
        card_id="tfc-127", set_code="1", collector_number="127",
        name="Hermes", subtitle="Messenger of the Gods", rarity="Legendary",
    ))
    database.upsert_card(Card(
        card_id="tfc-12", set_code="1", collector_number="12",
        name="Fairy Godmother", rarity="Common",
    ))
    database.upsert_card(Card(
        card_id="tfc-45", set_code="1", collector_number="45",
        name="Chip the Teacup", rarity="Common",
    ))
    database.close()
    return db_path


def test_scan_command_prints_grid_table(
    capsys, tmp_path: Path, seeded_db_path: Path
):
    # Synthesize a tiny "photo" — content doesn't matter; the SDK is stubbed.
    photo = tmp_path / "binder-page.jpg"
    photo.write_bytes(b"\xff\xd8\xff fake jpeg payload")

    fake_anthropic = MagicMock()
    fake_anthropic.messages.create.return_value = FakeAnthropicMessage(
        text=FIXTURE.read_text()
    )

    config = Config(
        anthropic_api_key="sk-ant-test",
        anthropic_model="claude-sonnet-4-6",
        per_scan_budget_usd=0.50,
        monthly_budget_usd=None,
        data_dir=tmp_path,
    )

    with patch("lorscan.cli._build_anthropic_client", return_value=fake_anthropic), \
         patch("lorscan.cli.normalize_for_api", return_value=photo.read_bytes()):
        rc = scan_command(photo_path=photo, config=config, db_path=seeded_db_path)

    assert rc == 0
    captured = capsys.readouterr()
    assert "Hermes" in captured.out
    assert "Fairy Godmother" in captured.out
    assert "Chip the Teacup" in captured.out
    # Each row should show the matched card's collector number.
    assert "127" in captured.out
    assert "tfc-127" in captured.out or "MATCHED" in captured.out
