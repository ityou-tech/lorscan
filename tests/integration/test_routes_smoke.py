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
    # Seed one ROF card too so the binder view (which iterates only over
    # sets with at least one catalog card) actually renders both sets.
    db.upsert_card(
        Card(
            card_id="rof-001",
            set_code="ROF",
            collector_number="1",
            name="Pinocchio",
            subtitle="Wooden Rascal",
            rarity="Common",
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


def test_scan_upload_runs_clip_path_and_redirects(client: TestClient):
    """POST /scan/upload runs CLIP, persists results, and 303s to /scan/<id>."""
    payload = _make_jpeg(200, 200)

    with patch(
        "lorscan.app.routes.scan.scan_with_clip",
        return_value=_fake_tile_matches(),
    ):
        response = client.post(
            "/scan/upload",
            files={"photo": ("page.jpg", payload, "image/jpeg")},
            follow_redirects=False,
        )

    # POST/Redirect/GET — refresh-safe.
    assert response.status_code == 303
    assert response.headers["location"].startswith("/scan/")

    # Following the redirect, the detail page renders the matched cards.
    detail = client.get(response.headers["location"])
    assert detail.status_code == 200
    body = detail.text
    assert "Hermes" in body
    assert "Messenger of the Gods" in body
    # The binder grid renders set+collector ("TFC-127"). Old code emitted
    # the bare card_id ("tfc-127") in a separate column — match either form
    # so the test isn't sensitive to label-formatting changes.
    assert "tfc-127" in body.lower()
    # The binder-grid layout exists and the matched card has the right state.
    assert "binder-grid" in body
    assert "binder-cell--matched" in body
    assert "Tokens" not in body
    assert "$0." not in body


def test_scan_upload_dedupes_re_uploads(client: TestClient):
    """Re-uploading the same photo redirects to the existing scan without
    re-running CLIP, and does not accumulate duplicate scan_results."""
    payload = _make_jpeg(200, 200)
    fake_tiles = _fake_tile_matches()

    with patch(
        "lorscan.app.routes.scan.scan_with_clip",
        return_value=fake_tiles,
    ) as scan_mock:
        # First upload: actually runs CLIP.
        r1 = client.post(
            "/scan/upload",
            files={"photo": ("page.jpg", payload, "image/jpeg")},
            follow_redirects=False,
        )
        # Second upload of the same bytes: should NOT re-run CLIP.
        r2 = client.post(
            "/scan/upload",
            files={"photo": ("page.jpg", payload, "image/jpeg")},
            follow_redirects=False,
        )

    assert r1.status_code == 303
    assert r2.status_code == 303
    # First upload lands on /scan/<id>; the duplicate gets a ?duplicate=1
    # marker so the detail page can surface a "re-upload" banner — but both
    # point at the same scan id, which is what dedup means here.
    assert r1.headers["location"].startswith("/scan/")
    assert r2.headers["location"] == f"{r1.headers['location']}?duplicate=1"
    # CLIP only ran once.
    assert scan_mock.call_count == 1

    # Detail page still has exactly 9 cells — no duplicates from the second upload.
    detail = client.get(r1.headers["location"])
    assert detail.status_code == 200
    # Each grid_position appears exactly once in the binder grid.
    for r in range(3):
        for c in range(3):
            pos = f"r{r + 1}c{c + 1}"
            # The position label sits inside a <span class="binder-pos">.
            occurrences = detail.text.count(f'class="binder-pos">{pos}<')
            assert occurrences == 1, (
                f"Expected exactly one cell for {pos} but found {occurrences}"
            )


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


def test_collection_renders_marketplace_badge(client: TestClient):
    """When a matched in-stock listing exists, /collection shows a price badge
    on the corresponding empty pocket."""
    from datetime import UTC, datetime

    cfg = client.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        mp = db.get_marketplace_by_slug("bazaarofmagic")
        # rof-001 is seeded by _seed_db at the top of this file (Pinocchio Wooden Rascal).
        db.upsert_listing(
            marketplace_id=mp["id"],
            external_id="9999",
            card_id="rof-001",
            finish="regular",
            price_cents=400,
            currency="EUR",
            in_stock=True,
            url="https://www.bazaarofmagic.eu/nl-NL/p/x/9999",
            title="Pinocchio (#1)",
            fetched_at=datetime.now(UTC).isoformat(),
        )
    finally:
        db.close()

    response = client.get("/collection")
    assert response.status_code == 200
    body = response.text
    # Price formatted Dutch-style (€4,00) AND link to the product page.
    assert "€4,00" in body, "Expected Dutch-format €4,00"
    assert 'href="https://www.bazaarofmagic.eu/nl-NL/p/x/9999"' in body
    assert 'target="_blank"' in body
    # The shop name appears.
    assert "Bazaar" in body


def test_collection_header_shows_cards_needed_stat(client: TestClient):
    """Page header gains 'X cards needed' meta-stat (catalog total - distinct owned)."""
    response = client.get("/collection")
    assert response.status_code == 200
    body = response.text
    assert "cards needed" in body
    assert "sets unfinished" in body


def test_collection_header_shows_refreshed_at_when_sweep_done(client: TestClient):
    """If a sweep has run, the page header shows the refreshed-at line."""
    cfg = client.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        mp = db.get_marketplace_by_slug("bazaarofmagic")
        sweep_id = db.start_marketplace_sweep(mp["id"])
        db.finish_marketplace_sweep(
            sweep_id, listings_seen=10, listings_matched=8, errors=0, status="ok",
        )
    finally:
        db.close()

    response = client.get("/collection")
    body = response.text
    assert "Marketplace data refreshed" in body or "refreshed" in body.lower()


def test_collection_header_shows_closest_strip_when_applicable(client: TestClient):
    """Closest-to-complete strip renders when at least one set is in 50-99% range."""
    from lorscan.storage.models import Card, CardSet
    cfg = client.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        # Seed a small set with 2 cards, then own 1 of them = 50% completion.
        db.upsert_set(CardSet(set_code="MINI", name="Mini Set", total_cards=2))
        db.upsert_card(Card(
            card_id="mini-1", set_code="MINI", collector_number="1",
            name="A", subtitle=None, rarity="Common",
        ))
        db.upsert_card(Card(
            card_id="mini-2", set_code="MINI", collector_number="2",
            name="B", subtitle=None, rarity="Common",
        ))
        db.upsert_collection_item(card_id="mini-1", quantity_delta=1)
    finally:
        db.close()

    response = client.get("/collection")
    body = response.text
    assert "closest" in body.lower() or "Closest" in body
    assert "Mini Set" in body


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
            follow_redirects=False,
        )
    assert upload_response.status_code == 303

    # /scan/<id> is the redirect target.
    location = upload_response.headers["location"]
    match = re.match(r"/scan/(\d+)$", location)
    assert match, f"Unexpected redirect target: {location}"
    scan_id = int(match.group(1))

    apply_response = client.post(f"/scan/{scan_id}/apply", follow_redirects=False)
    assert apply_response.status_code == 303

    coll_response = client.get("/collection")
    assert "No cards yet" not in coll_response.text
    assert "Hermes" in coll_response.text


def test_collection_renders_scan_cta_even_when_badges_exist(client: TestClient):
    """When collection is empty but listings exist, the 'Go to Scan' CTA
    must still be visible — empty-state should not be hidden by badges."""
    from datetime import UTC, datetime

    cfg = client.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        mp = db.get_marketplace_by_slug("bazaarofmagic")
        db.upsert_listing(
            marketplace_id=mp["id"],
            external_id="9999",
            card_id="rof-001",
            finish="regular",
            price_cents=400,
            currency="EUR",
            in_stock=True,
            url="https://www.bazaarofmagic.eu/nl-NL/p/x/9999",
            title="Pinocchio (#1)",
            fetched_at=datetime.now(UTC).isoformat(),
        )
    finally:
        db.close()

    response = client.get("/collection")
    body = response.text
    assert "No cards yet" in body
    assert "Go to Scan" in body
    assert "€4,00" in body


def _import_unused_to_silence_lint() -> None:
    """Keep ParsedCard/ParsedScan imports referenced for future tests."""
    _ = ParsedCard
    _ = ParsedScan
