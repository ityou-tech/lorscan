"""Card boundary detection + perspective correction.

When a user holds a card to a webcam or phone camera, the card occupies
only 30–50% of the frame; the rest is table, binder, hand, etc. CLIP
embeddings of the WHOLE frame compare poorly to clean studio catalog
images of just the card. This module isolates the card before encoding.

Algorithm (the standard pipeline used by every open-source MTG/Pokemon/
Yu-Gi-Oh scanner):

1. Grayscale + CLAHE (rescues edge contrast in dim/uneven lighting)
2. Gaussian blur → Canny edge detection (auto-thresholded via image median)
3. Dilate edges to close small gaps
4. Find external contours, sort by area
5. Approximate each candidate to a polygon; keep 4-corner ones
6. Filter by aspect ratio (Lorcana cards are ~5:7 portrait, also accept
   landscape for Locations / 90°-rotated cards)
7. Order corners (TL/TR/BR/BL), perspective-warp to a canonical 320×448 crop

`detect_and_warp_card` returns the largest passing quadrilateral — used by
single-card mode where we expect one card filling the frame.

`detect_all_cards` returns every passing quadrilateral — used by binder /
multi-card scenarios where one frame contains many cards.

If no candidate is found we return None / [] and the caller falls back to
the full frame. Graceful degradation — never block scanning on detection.
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

# Default min/max contour area as fraction of total frame area. Defaults are
# tuned for "one card mostly fills the frame" (single-card mode); callers in
# binder/multi-card mode pass smaller min_area_pct to find all cards in a grid.
DEFAULT_MIN_AREA_PCT = 0.02  # 2% — handles 3×3 binder shots
DEFAULT_MAX_AREA_PCT = 0.95

# How tightly the contour must fill its rotated bounding box (extent ratio)
# for us to accept it as a card. Real cards have extent ~0.95-1.0; ragged
# blobs like clothing or hands fall below 0.85. This is what saves the
# minAreaRect fallback from accepting non-card shapes.
MIN_EXTENT_RATIO = 0.85


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


def _build_edge_map(bgr: np.ndarray) -> np.ndarray:
    """Convert BGR → robust edge map.

    CLAHE rescues contrast in dim/uneven lighting (table edges + sleeves vs.
    dark binder spine). Auto-Canny picks thresholds from the image median
    instead of fixed 40/140 — works across many lighting conditions without
    tuning.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    blurred = cv2.GaussianBlur(enhanced, (5, 5), 0)
    median = float(np.median(blurred))
    sigma = 0.33
    lower = int(max(0, (1.0 - sigma) * median))
    upper = int(min(255, (1.0 + sigma) * median))
    edges = cv2.Canny(blurred, lower, upper)
    # Dilate just enough to close 1-pixel gaps from compression / motion blur,
    # but NOT enough to merge adjacent cards in a binder (which fuses all 9
    # cards into one giant blob and breaks per-card detection).
    return cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)


def _approx_4_corners(contour: np.ndarray) -> np.ndarray | None:
    """Try several epsilons until approxPolyDP returns a 4-corner polygon.

    Lorcana cards have rounded corners + sleeve glare that resist a fixed
    epsilon — sweeping a few values gives us the cleanest perspective
    correction when one happens to fit, while still letting the caller
    fall back to minAreaRect when nothing fits.
    """
    peri = cv2.arcLength(contour, True)
    for epsilon_factor in (0.02, 0.03, 0.04, 0.05, 0.06):
        approx = cv2.approxPolyDP(contour, epsilon_factor * peri, True)
        if len(approx) == 4:
            return approx.reshape(4, 2).astype("float32")
    return None


def _warp_quadrilateral(bgr: np.ndarray, contour: np.ndarray) -> Image.Image | None:
    """Validate a contour as card-shaped, then perspective-warp to canonical.

    First tries approxPolyDP (true 4-corner perspective correction); falls
    back to minAreaRect (rotation-only) if no epsilon gives 4 corners. The
    extent check (contour area vs. rotated-bbox area) rejects irregular
    blobs like clothing or hands — without it, the minAreaRect fallback
    happily wraps any large shape as a "card".
    """
    contour_area = float(cv2.contourArea(contour))
    min_rect = cv2.minAreaRect(contour)
    box_w, box_h = min_rect[1]
    box_area = float(box_w * box_h)
    if box_area <= 0:
        return None
    extent = contour_area / box_area
    if extent < MIN_EXTENT_RATIO:
        return None

    corners = _approx_4_corners(contour)
    if corners is None:
        corners = cv2.boxPoints(min_rect).astype("float32")

    rect = _order_corners(corners)
    tl, tr, br, bl = rect
    max_w = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    max_h = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    if max_w == 0 or max_h == 0:
        return None
    ratio = float(max_w / max_h)
    portrait = LORCANA_ASPECT_LOW <= ratio <= LORCANA_ASPECT_HIGH
    landscape = LANDSCAPE_ASPECT_LOW <= ratio <= LANDSCAPE_ASPECT_HIGH
    if not (portrait or landscape):
        return None

    # A landscape detection is just a portrait card rotated 90°. Roll the
    # corners so the canonical warp output is always portrait.
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
    warped_bgr = cv2.warpPerspective(bgr, m, (CANONICAL_CARD_WIDTH, CANONICAL_CARD_HEIGHT))
    warped_rgb = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(warped_rgb)


def _pil_to_bgr(pil_image: Image.Image) -> np.ndarray:
    if pil_image.mode != "RGB":
        pil_image = pil_image.convert("RGB")
    rgb = np.array(pil_image)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def detect_and_warp_card(
    pil_image: Image.Image,
    *,
    min_area_pct: float = DEFAULT_MIN_AREA_PCT,
    max_area_pct: float = DEFAULT_MAX_AREA_PCT,
) -> Image.Image | None:
    """Find the largest plausible card in an image and return a warped crop.

    Returns None if no plausible card boundary is detected; callers should
    fall back to the full frame.
    """
    bgr = _pil_to_bgr(pil_image)
    h, w = bgr.shape[:2]
    frame_area = w * h
    edges = _build_edge_map(bgr)

    # RETR_LIST (not RETR_EXTERNAL) so we descend into binder pages — each card
    # inside a binder forms a closed contour internal to the page outline; using
    # RETR_EXTERNAL would only return the page itself.
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    for contour in contours[:20]:
        area = cv2.contourArea(contour)
        if area < frame_area * min_area_pct:
            break  # sorted descending — nothing smaller will pass either
        if area > frame_area * max_area_pct:
            continue
        warped = _warp_quadrilateral(bgr, contour)
        if warped is not None:
            return warped
    return None


def detect_all_cards(
    pil_image: Image.Image,
    *,
    min_area_pct: float = DEFAULT_MIN_AREA_PCT,
    max_area_pct: float = DEFAULT_MAX_AREA_PCT,
    max_cards: int = 12,
) -> list[Image.Image]:
    """Find every plausible card in an image and return warped crops.

    Used by binder / multi-card workflows where one frame contains many
    cards (e.g. a 3×3 binder page captured by phone webcam). Returns crops
    in descending area order; empty list if nothing matches.
    """
    bgr = _pil_to_bgr(pil_image)
    h, w = bgr.shape[:2]
    frame_area = w * h
    edges = _build_edge_map(bgr)

    # RETR_LIST (not RETR_EXTERNAL) so we descend into binder pages — each card
    # inside a binder forms a closed contour internal to the page outline; using
    # RETR_EXTERNAL would only return the page itself.
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []

    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    results: list[Image.Image] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < frame_area * min_area_pct:
            break
        if area > frame_area * max_area_pct:
            continue
        warped = _warp_quadrilateral(bgr, contour)
        if warped is not None:
            results.append(warped)
            if len(results) >= max_cards:
                break
    return results


__all__ = [
    "CANONICAL_CARD_HEIGHT",
    "CANONICAL_CARD_WIDTH",
    "DEFAULT_MAX_AREA_PCT",
    "DEFAULT_MIN_AREA_PCT",
    "LORCANA_ASPECT_HIGH",
    "LORCANA_ASPECT_LOW",
    "detect_all_cards",
    "detect_and_warp_card",
]
