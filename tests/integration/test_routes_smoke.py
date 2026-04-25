"""FastAPI route smoke tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from lorscan.app.main import create_app
from lorscan.config import Config
from lorscan.services.recognition.client import RecognitionResult, TokenUsage
from lorscan.services.recognition.parser import parse_response
from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet

FIXTURE = Path(__file__).parent.parent / "fixtures" / "claude" / "good-3x3.json"


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """A fully-wired FastAPI test client with seeded sets/cards in a tmp DB."""
    cfg = Config(
        anthropic_model="claude-opus-4-7",
        per_scan_budget_usd=0.50,
        monthly_budget_usd=None,
        data_dir=tmp_path,
    )
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    db.upsert_set(CardSet(set_code="TFC", name="The First Chapter", total_cards=204))
    db.upsert_set(CardSet(set_code="ROF", name="Rise of the Floodborn", total_cards=204))
    db.upsert_card(
        Card(
            card_id="tfc-127",
            set_code="TFC",
            collector_number="127",
            name="Hermes",
            subtitle="Messenger of the Gods",
            rarity="Legendary",
        )
    )
    db.close()

    app = create_app(config=cfg)
    return TestClient(app)


def test_scan_index_renders_set_dropdown_with_friendly_names(client: TestClient):
    response = client.get("/scan")
    assert response.status_code == 200
    body = response.text
    # Friendly name + code in the option label.
    assert "The First Chapter (TFC" in body
    assert "Rise of the Floodborn (ROF" in body
    # The 'any set' default.
    assert "— any set —" in body


def test_scan_index_at_root_too(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "Scan a binder page" in response.text


def test_scan_upload_with_empty_file_returns_400(client: TestClient):
    response = client.post(
        "/scan/upload",
        files={"photo": ("test.jpg", b"", "image/jpeg")},
        data={"set_code": "TFC"},
    )
    # FastAPI returns 400 (HTTPException) for the empty file.
    assert response.status_code == 400


def test_scan_upload_runs_pipeline_with_stubbed_identify(client: TestClient):
    fake_result = RecognitionResult(
        parsed=parse_response(FIXTURE.read_text()),
        usage=TokenUsage(input_tokens=1500, output_tokens=400),
        request_payload={},
        response_text=FIXTURE.read_text(),
        cost_usd=0.012,
    )

    # Build a minimal valid JPEG payload.
    import io

    from PIL import Image

    img = Image.new("RGB", (200, 200), color=(123, 45, 67))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    payload = buf.getvalue()

    with patch("lorscan.app.routes.scan.identify", return_value=fake_result):
        response = client.post(
            "/scan/upload",
            files={"photo": ("page.jpg", payload, "image/jpeg")},
            data={"set_code": "TFC"},
        )

    assert response.status_code == 200
    body = response.text
    # Cells from the fixture appear in the rendered table.
    assert "Hermes" in body
    assert "Fairy Godmother" in body
    assert "Chip the Teacup" in body
    # Friendly set name appears in the 'restricted to' chip.
    assert "The First Chapter" in body
    # Cost line.
    assert "$0.0120" in body
