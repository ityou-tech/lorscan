"""FastAPI route smoke tests (CLIP-only path)."""

from __future__ import annotations

import io
import re
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lorscan.app.main import create_app
from lorscan.config import Config
from lorscan.services.embeddings import EMBEDDING_DIM, CardImageIndex
from lorscan.services.scan_result import ParsedCard, ParsedScan
from lorscan.services.visual_scan import TileMatch
from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet


def _make_jpeg(width: int = 100, height: int = 100, color=(123, 45, 67)) -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _seed_db(cfg: Config) -> None:
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


def _write_fake_index(cfg: Config) -> None:
    """Write a tiny CLIP index file so the route's index-presence check passes."""
    index = CardImageIndex(
        card_ids=["tfc-127"],
        embeddings=np.random.default_rng(0).standard_normal((1, EMBEDDING_DIM)).astype(np.float32),
    )
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    index.save(cfg.data_dir / "embeddings.npz")


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    cfg = Config(
        anthropic_model="claude-opus-4-7",
        per_scan_budget_usd=0.50,
        monthly_budget_usd=None,
        data_dir=tmp_path,
    )
    _seed_db(cfg)
    _write_fake_index(cfg)
    app = create_app(config=cfg)
    return TestClient(app)


@pytest.fixture()
def client_no_index(tmp_path: Path) -> TestClient:
    cfg = Config(
        anthropic_model="claude-opus-4-7",
        per_scan_budget_usd=0.50,
        monthly_budget_usd=None,
        data_dir=tmp_path,
    )
    _seed_db(cfg)
    app = create_app(config=cfg)
    return TestClient(app)


def test_scan_index_renders(client: TestClient):
    response = client.get("/scan")
    assert response.status_code == 200
    assert "Scan a binder page" in response.text


def test_scan_index_warns_when_index_missing(client_no_index: TestClient):
    response = client_no_index.get("/scan")
    assert response.status_code == 200
    body = response.text
    assert "Index not built yet" in body or "lorscan index-images" in body


def test_scan_index_at_root_too(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "Scan a binder page" in response.text


def test_scan_upload_with_empty_file_returns_400(client: TestClient):
    response = client.post(
        "/scan/upload",
        files={"photo": ("test.jpg", b"", "image/jpeg")},
    )
    assert response.status_code == 400


def _fake_tile_matches() -> list[TileMatch]:
    """Stub CLIP results: 9 cells, each pointing to tfc-127 with high confidence."""
    from lorscan.services.embeddings import Match

    return [
        TileMatch(grid_position=f"r{r + 1}c{c + 1}", matches=[Match("tfc-127", 0.92)])
        for r in range(3)
        for c in range(3)
    ]


def test_scan_upload_runs_clip_path(client: TestClient):
    payload = _make_jpeg(200, 200)

    with patch(
        "lorscan.app.routes.scan.scan_with_clip",
        return_value=_fake_tile_matches(),
    ):
        response = client.post(
            "/scan/upload",
            files={"photo": ("page.jpg", payload, "image/jpeg")},
        )

    assert response.status_code == 200
    body = response.text
    # The seeded card name appears via the matched_card lookup.
    assert "Hermes" in body
    assert "Messenger of the Gods" in body
    assert "tfc-127" in body
    assert "clip_visual" in body
    # No leftover LLM noise.
    assert "Tokens" not in body
    assert "$0." not in body


def test_scan_upload_without_index_shows_helpful_error(client_no_index: TestClient):
    payload = _make_jpeg()
    response = client_no_index.post(
        "/scan/upload",
        files={"photo": ("page.jpg", payload, "image/jpeg")},
    )
    assert response.status_code == 400
    assert "lorscan index-images" in response.text


def test_collection_index_empty_state(client: TestClient):
    response = client.get("/collection")
    assert response.status_code == 200
    assert "No cards yet" in response.text


def test_missing_index_renders_set_progress(client: TestClient):
    response = client.get("/missing")
    assert response.status_code == 200
    body = response.text
    assert "The First Chapter" in body
    assert "Rise of the Floodborn" in body


def test_scan_apply_adds_matched_cards_to_collection(client: TestClient):
    payload = _make_jpeg(200, 200, color=(0, 0, 0))

    with patch(
        "lorscan.app.routes.scan.scan_with_clip",
        return_value=_fake_tile_matches(),
    ):
        upload_response = client.post(
            "/scan/upload",
            files={"photo": ("page.jpg", payload, "image/jpeg")},
        )
    assert upload_response.status_code == 200

    body = upload_response.text
    match = re.search(r'action="/scan/(\d+)/apply"', body)
    assert match, "Expected an apply form in the results page"
    scan_id = int(match.group(1))

    apply_response = client.post(f"/scan/{scan_id}/apply", follow_redirects=False)
    assert apply_response.status_code == 303

    coll_response = client.get("/collection")
    assert "No cards yet" not in coll_response.text
    assert "Hermes" in coll_response.text


def _import_unused_to_silence_lint() -> None:
    """Keep ParsedCard/ParsedScan imports referenced for future tests."""
    _ = ParsedCard
    _ = ParsedScan
