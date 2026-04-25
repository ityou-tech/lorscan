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
from PIL import Image

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


@dataclass(frozen=True)
class TileMatch:
    """One CLIP-based result for a binder cell."""

    grid_position: str
    matches: list[Match] = field(default_factory=list)
    pixel_std: float = 0.0  # visual flatness, used for empty-slot detection
    is_empty: bool = False
    rotation_degrees: int = 0  # which rotation gave the top similarity (0/90/180/270)

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


ROTATION_ANGLES = (0, 90, 180, 270)


def scan_with_clip(
    photo_path: Path,
    index: CardImageIndex,
    *,
    rows: int = 3,
    cols: int = 3,
    top_k: int = 5,
    model_bundle=None,
    check_rotations: bool = True,
) -> list[TileMatch]:
    """Tile a binder photo, run each cell through CLIP, and detect empty slots.

    When `check_rotations` is True (default), each non-empty tile is also
    encoded at 90°/180°/270° and the rotation with the highest top-similarity
    wins. This catches:
      - Cards stored upside-down (180° wins)
      - Lorcana Location cards which are designed landscape and stored
        sideways in portrait sleeves (90° / 270° wins)

    `model_bundle` is an optional (model, preprocess, device) tuple to avoid
    reloading the model on repeated calls. If None, loads once internally.
    """
    if model_bundle is None:
        model, preprocess, device = _load_clip_model()
    else:
        model, preprocess, device = model_bundle

    image = Image.open(photo_path)
    image.load()
    if image.mode != "RGB":
        image = image.convert("RGB")

    tiles = crop_grid(image, rows=rows, cols=cols)

    # Pre-compute each tile's pixel-std (cheap) so we can skip rotation
    # checks for tiles that look empty.
    tile_stds: list[float] = [_tile_pixel_std(t) for _, t in tiles]

    angles = ROTATION_ANGLES if check_rotations else (0,)

    # Build the full batch: every non-skipped tile × every angle.
    batch_imgs: list[Image.Image] = []
    batch_origins: list[tuple[int, int]] = []  # (cell_index, angle)
    for i, (_, tile_img) in enumerate(tiles):
        for angle in angles:
            if angle == 0:
                batch_imgs.append(tile_img)
            else:
                batch_imgs.append(tile_img.rotate(angle, expand=True))
            batch_origins.append((i, angle))

    embeddings = encode_images_batch(model, preprocess, device, batch_imgs)

    # For each cell, find the rotation with the highest top-similarity.
    per_cell_best: dict[int, tuple[int, list[Match]]] = {}
    for j, (cell_i, angle) in enumerate(batch_origins):
        matches = index.find_matches(embeddings[j], top_k=top_k)
        if not matches:
            continue
        prev = per_cell_best.get(cell_i)
        if prev is None or matches[0].similarity > prev[1][0].similarity:
            per_cell_best[cell_i] = (angle, matches)

    results: list[TileMatch] = []
    for i, (grid_pos, _) in enumerate(tiles):
        std = tile_stds[i]
        best_angle, best_matches = per_cell_best.get(i, (0, []))
        top_sim = best_matches[0].similarity if best_matches else 0.0
        empty = _is_empty_tile(top_sim, std)
        # If we decided "empty", reset rotation to 0 and clear matches —
        # we don't want to suggest cards or rotations for an empty slot.
        if empty:
            best_angle = 0
            best_matches = []
        results.append(
            TileMatch(
                grid_position=grid_pos,
                matches=best_matches,
                pixel_std=std,
                is_empty=empty,
                rotation_degrees=best_angle,
            )
        )
    return results


def to_parsed_scan(tile_matches: list[TileMatch]) -> ParsedScan:
    """Adapt TileMatch results into the ParsedScan shape used by the rest of
    the app. Empty cells are flagged via confidence='empty'.

    Rotation: for non-zero rotations the candidates list carries a
    `rotation_degrees` key on its first entry, and `issues` gets a
    descriptive note so the user sees it.
    """
    cards: list[ParsedCard] = []
    issues: list[str] = []
    for tm in tile_matches:
        if tm.is_empty:
            candidates: list[dict] = []
        else:
            candidates = [{"card_id": m.card_id, "similarity": m.similarity} for m in tm.matches]
            if tm.rotation_degrees != 0 and candidates:
                candidates[0]["rotation_degrees"] = tm.rotation_degrees
                issues.append(
                    f"{tm.grid_position}: card best matches at {tm.rotation_degrees}° rotation"
                )
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
    return ParsedScan(page_type=f"binder_{len(tile_matches)}x", cards=cards, issues=issues)


__all__ = [
    "DEFAULT_INSET_PCT",
    "EMPTY_SIMILARITY_HARD",
    "EMPTY_SIMILARITY_SOFT",
    "EMPTY_VARIANCE_THRESHOLD",
    "TileMatch",
    "crop_grid",
    "scan_with_clip",
    "to_parsed_scan",
]
