"""Card boundary detection + perspective warp.

Strategy: synthesize images where we know the card's true position and shape,
then verify the detector finds it (or correctly rejects it). Real photos are
covered by the higher-level scan tests.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from lorscan.services.card_detection import (
    CANONICAL_CARD_HEIGHT,
    CANONICAL_CARD_WIDTH,
    detect_and_warp_card,
)


def _draw_card_rect(
    canvas_size: tuple[int, int],
    card_box: tuple[int, int, int, int],
    bg: tuple[int, int, int] = (20, 20, 20),
    fg: tuple[int, int, int] = (220, 220, 220),
) -> Image.Image:
    """Paint a light card-shaped rectangle on a dark background."""
    img = Image.new("RGB", canvas_size, color=bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle(card_box, fill=fg)
    return img


def test_returns_none_for_uniform_image():
    """No edges → no contours → no card found."""
    img = Image.new("RGB", (640, 880), color=(60, 60, 60))
    assert detect_and_warp_card(img) is None


def test_finds_portrait_card_on_dark_background():
    """Bright 5:7 portrait rectangle on dark background → detected and warped."""
    # 800×1100 canvas, card at (200, 150)-(560, 950) → 360×800, ratio ≈ 0.45
    # Adjust to land in the 0.55-0.95 portrait band: 360×600 (ratio 0.6).
    canvas = (800, 1100)
    box = (200, 200, 560, 800)  # 360w × 600h, ratio 0.60 → portrait
    img = _draw_card_rect(canvas, box)

    warped = detect_and_warp_card(img)
    assert warped is not None
    assert warped.size == (CANONICAL_CARD_WIDTH, CANONICAL_CARD_HEIGHT)


def test_finds_landscape_card_and_rotates_to_portrait():
    """A landscape-oriented card (rotated 90°) is rotated back to portrait."""
    canvas = (1100, 800)
    # 600w × 360h → ratio 1.67, in landscape band [1/0.95, 1/0.55] = [1.05, 1.82]
    box = (200, 200, 800, 560)
    img = _draw_card_rect(canvas, box)

    warped = detect_and_warp_card(img)
    assert warped is not None
    # Output is always portrait-oriented.
    assert warped.size == (CANONICAL_CARD_WIDTH, CANONICAL_CARD_HEIGHT)


def test_rejects_squarish_shape():
    """A near-square rectangle is not card-shaped → reject."""
    canvas = (800, 800)
    box = (200, 200, 600, 600)  # 400×400, ratio 1.0 → outside both bands
    img = _draw_card_rect(canvas, box)

    assert detect_and_warp_card(img) is None


def test_warped_card_preserves_card_pixels():
    """The warped output should be mostly bright (card color), not background."""
    canvas = (800, 1100)
    box = (200, 200, 560, 800)
    img = _draw_card_rect(canvas, box, bg=(15, 15, 15), fg=(230, 230, 230))

    warped = detect_and_warp_card(img)
    assert warped is not None
    arr = np.asarray(warped)
    # Center 50% of the warped image should be dominated by card color (>180),
    # not background (<50). Sample center patch to avoid edge artifacts.
    h, w = arr.shape[:2]
    center = arr[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4]
    assert center.mean() > 180.0
