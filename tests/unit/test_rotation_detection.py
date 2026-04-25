"""Rotation-aware CLIP scanning."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from lorscan.services.embeddings import EMBEDDING_DIM, CardImageIndex
from lorscan.services.visual_scan import (
    ROTATION_ANGLES,
    TileMatch,
    scan_with_clip,
    to_parsed_scan,
)


def _make_test_jpeg(tmp_path, width=900, height=900) -> str:
    """Build a 3×3 test photo: 9 distinguishable color blocks."""
    img = Image.new("RGB", (width, height))
    pixels = np.asarray(img).copy()
    cell_w = width // 3
    cell_h = height // 3
    colors = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 0),
        (0, 255, 255),
        (255, 0, 255),
        (128, 64, 32),
        (32, 128, 64),
        (64, 32, 128),
    ]
    for r in range(3):
        for c in range(3):
            pixels[r * cell_h : (r + 1) * cell_h, c * cell_w : (c + 1) * cell_w] = colors[r * 3 + c]
    img = Image.fromarray(pixels, mode="RGB")
    path = tmp_path / "test.jpg"
    img.save(path, format="JPEG", quality=90)
    return str(path)


def test_rotation_angles_constant_includes_all_four():
    assert ROTATION_ANGLES == (0, 90, 180, 270)


def test_scan_with_clip_picks_winning_rotation(tmp_path):
    """When the rotated tile produces a higher similarity, that rotation wins."""
    _make_test_jpeg(tmp_path)

    rng = np.random.default_rng(0)
    raw_emb = rng.standard_normal((1, EMBEDDING_DIM)).astype(np.float32)
    index = CardImageIndex(card_ids=["target"], embeddings=raw_emb)

    # Mock encode_images_batch to return controlled embeddings:
    # for cell #0, the 180° rotation matches "target" perfectly; others return junk.
    def fake_encode(model, preprocess, device, images):
        n = len(images)
        out = rng.standard_normal((n, EMBEDDING_DIM)).astype(np.float32)
        # batch_origins enumerates (cell_index, angle) for each cell × every angle.
        # We want cell 0 at angle 180 to closely match the target embedding.
        # Order: (0,0), (0,90), (0,180), (0,270), (1,0), (1,90), ...
        for j in range(n):
            cell_i = j // 4
            angle = ROTATION_ANGLES[j % 4]
            if cell_i == 0 and angle == 180:
                # Make this one nearly identical to the target.
                out[j] = raw_emb[0] + rng.standard_normal(EMBEDDING_DIM).astype(np.float32) * 0.001
        return out

    fake_model = (object(), object(), "cpu")
    with (
        patch("lorscan.services.visual_scan.encode_images_batch", side_effect=fake_encode),
        patch("lorscan.services.visual_scan._load_clip_model", return_value=fake_model),
    ):
        results = scan_with_clip(tmp_path / "test.jpg", index)

    cell0 = results[0]
    assert cell0.rotation_degrees == 180
    assert cell0.best is not None
    assert cell0.best.card_id == "target"


def test_scan_with_clip_default_rotation_is_zero_when_upright_wins(tmp_path):
    """If no rotation produces a meaningfully higher similarity, the default 0° wins."""
    _make_test_jpeg(tmp_path)

    rng = np.random.default_rng(42)
    target = rng.standard_normal((1, EMBEDDING_DIM)).astype(np.float32)
    index = CardImageIndex(card_ids=["upright"], embeddings=target)

    def fake_encode(model, preprocess, device, images):
        n = len(images)
        out = rng.standard_normal((n, EMBEDDING_DIM)).astype(np.float32)
        # cell 0 at angle 0 (upright) is the strongest match.
        for j in range(n):
            cell_i = j // 4
            angle = ROTATION_ANGLES[j % 4]
            if cell_i == 0 and angle == 0:
                out[j] = target[0] + rng.standard_normal(EMBEDDING_DIM).astype(np.float32) * 0.001
        return out

    fake_model = (object(), object(), "cpu")
    with (
        patch("lorscan.services.visual_scan.encode_images_batch", side_effect=fake_encode),
        patch("lorscan.services.visual_scan._load_clip_model", return_value=fake_model),
    ):
        results = scan_with_clip(tmp_path / "test.jpg", index)

    cell0 = results[0]
    assert cell0.rotation_degrees == 0
    assert cell0.best is not None
    assert cell0.best.card_id == "upright"


def test_scan_with_clip_disable_rotation_check(tmp_path):
    """check_rotations=False uses only the upright orientation (4× faster)."""
    _make_test_jpeg(tmp_path)

    rng = np.random.default_rng(0)
    target = rng.standard_normal((1, EMBEDDING_DIM)).astype(np.float32)
    index = CardImageIndex(card_ids=["x"], embeddings=target)

    captured_n = {}

    def fake_encode(model, preprocess, device, images):
        captured_n["n"] = len(images)
        return rng.standard_normal((len(images), EMBEDDING_DIM)).astype(np.float32)

    fake_model = (object(), object(), "cpu")
    with (
        patch("lorscan.services.visual_scan.encode_images_batch", side_effect=fake_encode),
        patch("lorscan.services.visual_scan._load_clip_model", return_value=fake_model),
    ):
        scan_with_clip(tmp_path / "test.jpg", index, check_rotations=False)

    # 9 cells × 1 angle = 9 images encoded. With rotations on it would be 36.
    assert captured_n["n"] == 9


def test_to_parsed_scan_includes_rotation_in_candidates_and_issues():
    from lorscan.services.embeddings import Match

    tile_matches = [
        TileMatch(
            grid_position="r1c1",
            matches=[Match("upright-card", 0.92)],
            pixel_std=120.0,
            is_empty=False,
            rotation_degrees=0,
        ),
        TileMatch(
            grid_position="r2c2",
            matches=[Match("flipped-card", 0.88)],
            pixel_std=110.0,
            is_empty=False,
            rotation_degrees=180,
        ),
    ]
    parsed = to_parsed_scan(tile_matches)

    # Upright cell: no rotation_degrees on candidate, no issue note.
    assert "rotation_degrees" not in parsed.cards[0].candidates[0]
    # Rotated cell: rotation_degrees on candidate, issue note added.
    assert parsed.cards[1].candidates[0]["rotation_degrees"] == 180
    assert any("180°" in issue for issue in parsed.issues)


def test_to_parsed_scan_skips_rotation_for_empty_cells():
    from lorscan.services.embeddings import Match

    tile_matches = [
        TileMatch(
            grid_position="r1c3",
            matches=[Match("c", 0.30)],
            pixel_std=12.0,
            is_empty=True,
            rotation_degrees=0,
        ),
    ]
    parsed = to_parsed_scan(tile_matches)
    # Empty cells get no candidates and produce no rotation issue notes.
    assert parsed.cards[0].candidates == []
    assert parsed.issues == []


# Silence unused-fixture lint
_ = pytest
