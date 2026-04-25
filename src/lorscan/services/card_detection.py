"""Card boundary detection + perspective correction.

When a user holds a card to a webcam or phone camera, the card occupies
only 30–50% of the frame; the rest is table, binder, hand, etc. CLIP
embeddings of the WHOLE frame compare poorly to clean studio catalog
images of just the card. This module isolates the card before encoding.

Algorithm (the standard pipeline used by every open-source MTG/Pokemon/
Yu-Gi-Oh scanner):

1. Grayscale + Gaussian blur → Canny edge detection
2. Dilate edges to close small gaps
3. Find external contours, sort by area
4. Approximate each candidate to a polygon; keep 4-corner ones
5. Filter by aspect ratio (Lorcana cards are ~5:7 portrait)
6. Largest passing quadrilateral wins
7. Order corners (TL/TR/BR/BL), perspective-warp to a canonical 320×448 crop

If no candidate is found we return None and the caller falls back to the
full frame. Graceful degradation — never block scanning on detection.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

# Lorcana cards are ~63 × 88 mm — aspect ratio 0.716. Allow ±15% for
# perspective skew (cards rarely sit perfectly square to the camera).
LORCANA_ASPECT_LOW = 0.55
LORCANA_ASPECT_HIGH = 0.95
# Also accept landscape (90°-rotated) for Locations or hand-tilted cards.
LANDSCAPE_ASPECT_LOW = 1 / LORCANA_ASPECT_HIGH
LANDSCAPE_ASPECT_HIGH = 1 / LORCANA_ASPECT_LOW

CANONICAL_CARD_WIDTH = 320
CANONICAL_CARD_HEIGHT = 448  # 320 × 7/5


def _order_corners(pts: np.ndarray) -> np.ndarray:
    """Order four 2D points as (top-left, top-right, bottom-right, bottom-left).

    Standard trick: TL has the smallest x+y sum, BR the largest;
    TR has the smallest y-x diff, BL the largest.
    """
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1).flatten()
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def detect_and_warp_card(pil_image: Image.Image) -> Image.Image | None:
    """Find the card in an image and return a perspective-corrected crop.

    Returns None if no plausible card boundary is detected; callers should
    fall back to the full frame.
    """
    if pil_image.mode != "RGB":
        pil_image = pil_image.convert("RGB")
    rgb = np.array(pil_image)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]
    frame_area = w * h

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 40, 140)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    for contour in contours[:10]:
        area = cv2.contourArea(contour)
        # Skip very small noise and frame-filling contours (the latter is usually
        # the page itself, not a card on it).
        if area < frame_area * 0.05:
            break  # contours are sorted descending, no need to continue
        if area > frame_area * 0.95:
            continue

        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.025 * peri, True)
        if len(approx) != 4:
            continue

        rect = _order_corners(approx.reshape(4, 2).astype("float32"))
        tl, tr, br, bl = rect
        width_top = np.linalg.norm(tr - tl)
        width_bottom = np.linalg.norm(br - bl)
        height_left = np.linalg.norm(bl - tl)
        height_right = np.linalg.norm(br - tr)
        max_w = max(width_top, width_bottom)
        max_h = max(height_left, height_right)
        if max_w == 0 or max_h == 0:
            continue
        ratio = max_w / max_h
        portrait = LORCANA_ASPECT_LOW <= ratio <= LORCANA_ASPECT_HIGH
        landscape = LANDSCAPE_ASPECT_LOW <= ratio <= LANDSCAPE_ASPECT_HIGH
        if not (portrait or landscape):
            continue

        # If the detected card is landscape-shaped (rotated 90°), swap so the
        # canonical output is always portrait.
        if landscape:
            rect = np.array([rect[3], rect[0], rect[1], rect[2]], dtype="float32")

        dst = np.array(
            [
                [0, 0],
                [CANONICAL_CARD_WIDTH - 1, 0],
                [CANONICAL_CARD_WIDTH - 1, CANONICAL_CARD_HEIGHT - 1],
                [0, CANONICAL_CARD_HEIGHT - 1],
            ],
            dtype="float32",
        )
        m = cv2.getPerspectiveTransform(rect, dst)
        warped_bgr = cv2.warpPerspective(
            bgr, m, (CANONICAL_CARD_WIDTH, CANONICAL_CARD_HEIGHT)
        )
        warped_rgb = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2RGB)
        return Image.fromarray(warped_rgb)

    return None


__all__ = [
    "CANONICAL_CARD_HEIGHT",
    "CANONICAL_CARD_WIDTH",
    "LORCANA_ASPECT_HIGH",
    "LORCANA_ASPECT_LOW",
    "detect_and_warp_card",
]
