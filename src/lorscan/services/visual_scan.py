"""Tile-and-CLIP scanner — local, fast, no LLM required.

Splits a binder photo into a grid of cells, embeds each cell with CLIP,
and looks up the nearest catalog match. Fully local; ~500ms total for a
3×3 page on Apple Silicon.

Empty-slot detection: each tile is also cheaply analyzed for visual
"flatness" (low pixel std-dev = uniform plastic sleeve). Combined with a
low max-similarity score, this distinguishes "empty sleeve" from "card
we can't identify" — important for the misplacement-detection workflow
in Phase C, where empty slots are expected, not anomalies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from lorscan.services.card_detection import detect_and_warp_card
from lorscan.services.embeddings import (
    CardImageIndex,
    Match,
    _load_clip_model,
    encode_images_batch,
)
from lorscan.services.scan_result import ParsedCard, ParsedScan

# Lorcana cards have a portrait aspect ratio (~5:7). Binder pages are typically
# 3×3 with even spacing; we crop with a tiny inset so we don't accidentally
# include neighboring sleeves.
DEFAULT_INSET_PCT = 0.02

# Empty-slot detection thresholds (see _is_empty_tile).
EMPTY_SIMILARITY_HARD = 0.45  # very low → almost certainly not a known card
EMPTY_SIMILARITY_SOFT = 0.55  # combined with low variance → empty
EMPTY_VARIANCE_THRESHOLD = 35.0  # 0–255 std-dev. Cards typically > 50.

# Confidence thresholds.
HIGH_CONFIDENCE_SIM = 0.85
MEDIUM_CONFIDENCE_SIM = 0.70


def _tile_pixel_std(tile: Image.Image, *, sample_size: int = 64) -> float:
    """Cheap visual-flatness signal. Empty sleeves are uniform color → low std.

    Downsamples to `sample_size`×`sample_size` first so the cost is constant
    regardless of input resolution.
    """
    small = tile.convert("RGB").resize((sample_size, sample_size), Image.Resampling.BILINEAR)
    arr = np.asarray(small, dtype=np.float32)
    return float(arr.std())


def _is_empty_tile(top_similarity: float, pixel_std: float) -> bool:
    """Return True if a tile likely contains no card.

    Two paths to True:
      - Very low similarity (no catalog card looks remotely like this), OR
      - Moderately low similarity AND visually flat (sleeve color, no art).
    """
    if top_similarity < EMPTY_SIMILARITY_HARD:
        return True
    return top_similarity < EMPTY_SIMILARITY_SOFT and pixel_std < EMPTY_VARIANCE_THRESHOLD


def _four_rotations(image: Image.Image) -> list[Image.Image]:
    """Return [0°, 90°, 180°, 270°] rotations of an image.

    Used to make CLIP recognition rotation-invariant: minAreaRect and
    `_order_corners` can't reliably tell which corner of a card is the
    "top", so we let the catalog match itself vote — the correct rotation
    has by far the highest similarity to the right card.
    """
    return [
        image,
        image.transpose(Image.Transpose.ROTATE_90),
        image.transpose(Image.Transpose.ROTATE_180),
        image.transpose(Image.Transpose.ROTATE_270),
    ]


def _best_rotation_match(
    image: Image.Image,
    *,
    model,
    preprocess,
    device: str,
    index: CardImageIndex,
    top_k: int,
    allowed_card_ids: set[str] | None = None,
) -> list[Match]:
    """Encode all 4 rotations of `image`, return the top-k from the best one.

    "Best" = the rotation whose top-1 catalog similarity is highest. This
    handles cards photographed sideways or upside-down without requiring
    the user to pre-orient them.
    """
    embeddings = encode_images_batch(model, preprocess, device, _four_rotations(image))
    best_matches: list[Match] = []
    best_sim = -1.0
    for emb in embeddings:
        candidates = index.find_matches(
            emb, top_k=top_k, allowed_card_ids=allowed_card_ids
        )
        sim = candidates[0].similarity if candidates else 0.0
        if sim > best_sim:
            best_sim = sim
            best_matches = candidates
    return best_matches


@dataclass(frozen=True)
class TileMatch:
    """One CLIP-based result for a binder cell."""

    grid_position: str
    matches: list[Match] = field(default_factory=list)
    pixel_std: float = 0.0  # visual flatness, used for empty-slot detection
    is_empty: bool = False

    @property
    def best(self) -> Match | None:
        return self.matches[0] if self.matches else None

    @property
    def confidence_label(self) -> str:
        """Translate cosine similarity into a human-readable confidence.

        Returns one of: 'high', 'medium', 'low', 'empty'.
        """
        if self.is_empty:
            return "empty"
        if not self.matches:
            return "low"
        sim = self.matches[0].similarity
        if sim >= HIGH_CONFIDENCE_SIM:
            return "high"
        if sim >= MEDIUM_CONFIDENCE_SIM:
            return "medium"
        return "low"


def crop_grid(
    image: Image.Image,
    *,
    rows: int = 3,
    cols: int = 3,
    inset_pct: float = DEFAULT_INSET_PCT,
) -> list[tuple[str, Image.Image]]:
    """Crop a binder photo into rows×cols cells.

    Returns a list of (grid_position, cell_image) tuples in row-major order
    (r1c1, r1c2, ..., rNcM). A small inset trims sleeve edges so the catalog
    image is the dominant content per cell.
    """
    w, h = image.size
    cell_w = w / cols
    cell_h = h / rows
    inset_x = cell_w * inset_pct
    inset_y = cell_h * inset_pct

    tiles: list[tuple[str, Image.Image]] = []
    for r in range(rows):
        for c in range(cols):
            x0 = int(c * cell_w + inset_x)
            y0 = int(r * cell_h + inset_y)
            x1 = int((c + 1) * cell_w - inset_x)
            y1 = int((r + 1) * cell_h - inset_y)
            tile = image.crop((x0, y0, x1, y1))
            tiles.append((f"r{r + 1}c{c + 1}", tile))
    return tiles


def scan_single_image(
    image: Image.Image,
    index: CardImageIndex,
    *,
    grid_position: str = "single",
    top_k: int = 5,
    model_bundle=None,
    allowed_card_ids: set[str] | None = None,
) -> TileMatch:
    """Run single-card CLIP matching on an in-memory Image.

    Used by both `scan_single_card` (for whole-photo single-card scans)
    and the per-cell rescan endpoint, which feeds in a tile cropped from
    a larger binder photo.
    """
    if model_bundle is None:
        model, preprocess, device = _load_clip_model()
    else:
        model, preprocess, device = model_bundle

    if image.mode != "RGB":
        image = image.convert("RGB")

    # Isolate the card from the background so CLIP encodes art, not
    # table/hand. If detection fails, fall back to the full frame.
    detected = detect_and_warp_card(image)
    encode_img = detected if detected is not None else image

    matches = _best_rotation_match(
        encode_img,
        model=model,
        preprocess=preprocess,
        device=device,
        index=index,
        top_k=top_k,
        allowed_card_ids=allowed_card_ids,
    )
    top_sim = matches[0].similarity if matches else 0.0
    std = _tile_pixel_std(encode_img)
    empty = _is_empty_tile(top_sim, std)
    if empty:
        matches = []
    return TileMatch(
        grid_position=grid_position,
        matches=matches,
        pixel_std=std,
        is_empty=empty,
    )


def scan_single_card(
    photo_path: Path,
    index: CardImageIndex,
    *,
    top_k: int = 5,
    model_bundle=None,
    allowed_card_ids: set[str] | None = None,
) -> TileMatch:
    """Scan a photo as a single card (no grid cropping)."""
    image = Image.open(photo_path)
    image.load()
    # Honor the EXIF orientation tag so the buffer matches what the user
    # sees in the browser — without this, phone photos with orientation 6/8
    # crop in the wrong order and the binder grid renders transposed.
    image = ImageOps.exif_transpose(image)
    return scan_single_image(
        image,
        index,
        grid_position="single",
        top_k=top_k,
        model_bundle=model_bundle,
        allowed_card_ids=allowed_card_ids,
    )


def _orient_for_grid(image: Image.Image, *, rows: int, cols: int) -> Image.Image:
    """Rotate the image so its aspect ratio is closer to the expected
    grid aspect (rows:cols of card-shaped cells).

    A 3×3 grid of Lorcana cards is portrait-shaped (3×5 wide by 3×7 tall =
    15:21 = ~0.71). If the user shoots the binder with the phone held
    sideways the resulting image is landscape — cells then crop as
    landscape rectangles, slicing each card vertically. Detecting the
    misorientation by aspect ratio and rotating once before cropping
    fixes the grid mapping.

    EXIF orientation must already have been applied. We only handle the
    common 90° rotation case here; 180° flips are rare for top-down
    photos and would require content-based detection.
    """
    target_aspect = (cols * 5) / (rows * 7)  # cards are 5:7 portrait
    image_aspect = image.width / image.height
    # If the image is significantly more landscape than the target (>1.1×),
    # rotate it 90°. The direction is somewhat arbitrary — the per-tile
    # rotation step inside `_best_rotation_match` recovers card matches
    # regardless of whether we picked CW or CCW.
    if image_aspect > target_aspect * 1.4:
        return image.rotate(-90, expand=True)
    return image


def scan_with_clip(
    photo_path: Path,
    index: CardImageIndex,
    *,
    rows: int = 3,
    cols: int = 3,
    top_k: int = 5,
    model_bundle=None,
    allowed_card_ids: set[str] | None = None,
    auto_rotate: bool = True,
) -> list[TileMatch]:
    """Tile a binder photo, run each cell through CLIP, and detect empty slots.

    `auto_rotate=True` flips landscape photos to portrait so the 3×3
    crop maps onto the binder's natural orientation. Set False if the
    caller already handled rotation (e.g. user-specified override).
    """
    if model_bundle is None:
        model, preprocess, device = _load_clip_model()
    else:
        model, preprocess, device = model_bundle

    image = Image.open(photo_path)
    image.load()
    # Honor the EXIF orientation tag so the buffer matches what the user
    # sees in the browser — without this, phone photos with orientation 6/8
    # crop in the wrong order and the binder grid renders transposed.
    image = ImageOps.exif_transpose(image)
    if image.mode != "RGB":
        image = image.convert("RGB")
    if auto_rotate:
        image = _orient_for_grid(image, rows=rows, cols=cols)

    tiles = crop_grid(image, rows=rows, cols=cols)
    # Per-tile boundary detection corrects perspective skew (binder photos are
    # rarely perfectly top-down). Falls back to the raw tile when detection
    # can't find a clean quadrilateral — common for empty sleeves.
    cell_images: list[Image.Image] = []
    for _, tile_img in tiles:
        warped = detect_and_warp_card(tile_img)
        cell_images.append(warped if warped is not None else tile_img)

    # Batch all 4 rotations of every cell into a single CLIP forward pass —
    # 4N images, one model call. Much faster than per-cell loops on MPS/CUDA.
    rotated_batch: list[Image.Image] = []
    for img in cell_images:
        rotated_batch.extend(_four_rotations(img))
    embeddings = encode_images_batch(model, preprocess, device, rotated_batch)

    results: list[TileMatch] = []
    for i, (grid_pos, _) in enumerate(tiles):
        encoded_img = cell_images[i]
        # Pick the rotation whose top-1 catalog match is strongest.
        best_matches: list[Match] = []
        best_sim = -1.0
        for r in range(4):
            cand = index.find_matches(
                embeddings[i * 4 + r],
                top_k=top_k,
                allowed_card_ids=allowed_card_ids,
            )
            sim = cand[0].similarity if cand else 0.0
            if sim > best_sim:
                best_sim = sim
                best_matches = cand
        std = _tile_pixel_std(encoded_img)
        empty = _is_empty_tile(best_sim if best_matches else 0.0, std)
        if empty:
            best_matches = []
        results.append(
            TileMatch(
                grid_position=grid_pos,
                matches=best_matches,
                pixel_std=std,
                is_empty=empty,
            )
        )
    return results


def to_parsed_scan(tile_matches: list[TileMatch]) -> ParsedScan:
    """Adapt TileMatch results into the ParsedScan shape used by the rest of
    the app. Empty cells are flagged via confidence='empty'.
    """
    cards: list[ParsedCard] = []
    for tm in tile_matches:
        if tm.is_empty:
            candidates: list[dict] = []
        else:
            candidates = [{"card_id": m.card_id, "similarity": m.similarity} for m in tm.matches]
        cards.append(
            ParsedCard(
                grid_position=tm.grid_position,
                name=None,
                subtitle=None,
                set_hint=None,
                collector_number=None,
                ink_color=None,
                finish="regular",
                confidence=tm.confidence_label,
                candidates=candidates,
            )
        )
    return ParsedScan(page_type=f"binder_{len(tile_matches)}x", cards=cards, issues=[])


__all__ = [
    "DEFAULT_INSET_PCT",
    "EMPTY_SIMILARITY_HARD",
    "EMPTY_SIMILARITY_SOFT",
    "EMPTY_VARIANCE_THRESHOLD",
    "TileMatch",
    "crop_grid",
    "scan_single_card",
    "scan_with_clip",
    "to_parsed_scan",
]
