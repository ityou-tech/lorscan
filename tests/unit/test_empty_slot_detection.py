"""Empty-slot detection in the visual_scan pipeline."""

from __future__ import annotations

from PIL import Image

from lorscan.services.embeddings import Match
from lorscan.services.visual_scan import (
    EMPTY_SIMILARITY_HARD,
    EMPTY_SIMILARITY_SOFT,
    EMPTY_VARIANCE_THRESHOLD,
    TileMatch,
    _is_empty_tile,
    _tile_pixel_std,
    to_parsed_scan,
)


def test_uniform_tile_has_low_pixel_std():
    """A flat, single-color image — like an empty plastic sleeve — has low std."""
    flat = Image.new("RGB", (200, 280), color=(50, 50, 50))
    std = _tile_pixel_std(flat)
    assert std < 1.0  # essentially zero


def test_high_contrast_tile_has_high_pixel_std():
    """An image with strong color contrast has much higher std than a flat image."""
    import numpy as np

    # Half-and-half black/white image. After downsampling, std stays ~127.
    arr = np.zeros((280, 200, 3), dtype=np.uint8)
    arr[:140, :, :] = 255
    img = Image.fromarray(arr, mode="RGB")
    std = _tile_pixel_std(img)
    # A flat image is ~0; this should be an order of magnitude higher.
    assert std > 50


def test_is_empty_returns_true_for_very_low_similarity():
    """Hard floor: similarity below EMPTY_SIMILARITY_HARD = empty regardless of variance."""
    assert _is_empty_tile(top_similarity=0.30, pixel_std=200.0) is True
    assert _is_empty_tile(top_similarity=EMPTY_SIMILARITY_HARD - 0.01, pixel_std=200.0) is True


def test_is_empty_returns_true_for_low_sim_and_flat_image():
    """Soft path: moderately low similarity + flat → empty."""
    assert _is_empty_tile(top_similarity=0.50, pixel_std=20.0) is True


def test_is_empty_returns_false_for_low_sim_but_high_variance():
    """A card we can't identify (different art, foreign card) is not "empty"."""
    assert _is_empty_tile(top_similarity=0.50, pixel_std=80.0) is False


def test_is_empty_returns_false_for_high_similarity():
    """A confident match isn't empty even if the image happens to be flat."""
    assert _is_empty_tile(top_similarity=0.90, pixel_std=10.0) is False


def test_thresholds_are_consistent():
    """The hard threshold must be stricter than the soft threshold."""
    assert EMPTY_SIMILARITY_HARD < EMPTY_SIMILARITY_SOFT


def test_tilematch_confidence_label_returns_empty_when_flagged():
    tm = TileMatch(
        grid_position="r1c3",
        matches=[Match("some-card", 0.42)],
        pixel_std=15.0,
        is_empty=True,
    )
    assert tm.confidence_label == "empty"


def test_tilematch_confidence_label_falls_back_to_similarity_when_not_empty():
    tm = TileMatch(
        grid_position="r1c1",
        matches=[Match("c1", 0.92)],
        pixel_std=120.0,
        is_empty=False,
    )
    assert tm.confidence_label == "high"


def test_to_parsed_scan_marks_empty_cells_with_no_candidates():
    tile_matches = [
        TileMatch(
            grid_position="r1c1",
            matches=[Match("good-card", 0.91)],
            pixel_std=120.0,
            is_empty=False,
        ),
        TileMatch(
            grid_position="r1c2",
            matches=[Match("noisy-card", 0.50)],
            pixel_std=15.0,
            is_empty=True,
        ),
    ]
    parsed = to_parsed_scan(tile_matches)
    assert parsed.cards[0].confidence == "high"
    assert len(parsed.cards[0].candidates) == 1

    assert parsed.cards[1].confidence == "empty"
    # Empty cells don't surface candidates — UX-wise we don't want to suggest
    # cards for slots that have no card.
    assert parsed.cards[1].candidates == []


def test_default_empty_variance_threshold_within_expected_range():
    """Sanity: cards typically have std > 50, sleeves < 30. Threshold sits between."""
    assert 25.0 < EMPTY_VARIANCE_THRESHOLD < 55.0
