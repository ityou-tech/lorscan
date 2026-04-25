"""Tile-and-CLIP scanner — local, fast, no LLM required.

Splits a binder photo into a grid of cells, embeds each cell with CLIP,
and looks up the nearest catalog match. Fully local; ~500ms total for a
3×3 page on Apple Silicon.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

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


@dataclass(frozen=True)
class TileMatch:
    """One CLIP-based result for a binder cell."""

    grid_position: str
    matches: list[Match] = field(default_factory=list)

    @property
    def best(self) -> Match | None:
        return self.matches[0] if self.matches else None

    @property
    def confidence_label(self) -> str:
        """Translate cosine similarity into a human-readable confidence."""
        if not self.matches:
            return "low"
        sim = self.matches[0].similarity
        if sim >= 0.85:
            return "high"
        if sim >= 0.70:
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


def scan_with_clip(
    photo_path: Path,
    index: CardImageIndex,
    *,
    rows: int = 3,
    cols: int = 3,
    top_k: int = 5,
    model_bundle=None,
) -> list[TileMatch]:
    """Tile a binder photo and look up each cell against the CLIP index.

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
    cell_images = [t[1] for t in tiles]
    embeddings = encode_images_batch(model, preprocess, device, cell_images)

    return [
        TileMatch(
            grid_position=tiles[i][0],
            matches=index.find_matches(embeddings[i], top_k=top_k),
        )
        for i in range(len(tiles))
    ]


def to_parsed_scan(tile_matches: list[TileMatch]) -> ParsedScan:
    """Adapt TileMatch results into the ParsedScan shape used by the rest of
    the app, so the CLIP path can flow through the same matching/persistence
    code as the LLM path. Card name + collector_number are NOT populated;
    instead we surface the matched_card_id as a candidate.
    """
    cards: list[ParsedCard] = []
    for tm in tile_matches:
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
    "TileMatch",
    "crop_grid",
    "scan_with_clip",
    "to_parsed_scan",
]
