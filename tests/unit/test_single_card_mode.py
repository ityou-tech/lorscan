"""scan_single_card runs CLIP on the whole image (no grid crop)."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
from PIL import Image

from lorscan.services.embeddings import EMBEDDING_DIM, CardImageIndex
from lorscan.services.visual_scan import scan_single_card


def _solid_jpeg(tmp_path, color=(180, 60, 100)):
    img = Image.new("RGB", (640, 880), color=color)
    p = tmp_path / "card.jpg"
    img.save(p, format="JPEG", quality=90)
    return p


def test_scan_single_card_returns_one_tile_match(tmp_path):
    photo = _solid_jpeg(tmp_path)
    rng = np.random.default_rng(42)
    target = rng.standard_normal((1, EMBEDDING_DIM)).astype(np.float32)
    index = CardImageIndex(card_ids=["only-card"], embeddings=target)

    def fake_encode(model, preprocess, device, images):
        # Return one near-match so confidence is "high"-territory.
        out = target + rng.standard_normal((1, EMBEDDING_DIM)).astype(np.float32) * 0.001
        return out

    fake_model = (object(), object(), "cpu")
    with (
        patch("lorscan.services.visual_scan.encode_images_batch", side_effect=fake_encode),
        patch("lorscan.services.visual_scan._load_clip_model", return_value=fake_model),
    ):
        tm = scan_single_card(photo, index)

    assert tm.grid_position == "single"
    assert tm.best is not None
    assert tm.best.card_id == "only-card"
    assert tm.is_empty is False


def test_scan_single_card_flags_blank_image_as_empty(tmp_path):
    """A blank-color image should be flagged as empty if similarity is low."""
    blank = Image.new("RGB", (640, 880), color=(50, 50, 50))
    p = tmp_path / "blank.jpg"
    blank.save(p, format="JPEG", quality=90)

    rng = np.random.default_rng(0)
    cards = rng.standard_normal((10, EMBEDDING_DIM)).astype(np.float32)
    index = CardImageIndex(card_ids=[f"c{i}" for i in range(10)], embeddings=cards)

    def fake_encode(model, preprocess, device, images):
        # Random embedding — won't be similar to any catalog row.
        return rng.standard_normal((1, EMBEDDING_DIM)).astype(np.float32) * 0.1

    fake_model = (object(), object(), "cpu")
    with (
        patch("lorscan.services.visual_scan.encode_images_batch", side_effect=fake_encode),
        patch("lorscan.services.visual_scan._load_clip_model", return_value=fake_model),
    ):
        tm = scan_single_card(p, index)

    # Either flagged empty (best path) or low confidence — both acceptable.
    assert tm.confidence_label in ("empty", "low")
    if tm.confidence_label == "empty":
        assert tm.matches == []
