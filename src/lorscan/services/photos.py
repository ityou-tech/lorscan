"""Photo service: hashing, saving, in-memory normalization for the API."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image

MAX_LONG_EDGE_PX = 1568  # Anthropic's recommended max for vision input
NORMALIZED_QUALITY = 85


def hash_bytes(payload: bytes) -> str:
    """Return the lowercase sha256 hex digest of payload."""
    return hashlib.sha256(payload).hexdigest()


def save_original(payload: bytes, *, photos_dir: Path, extension: str) -> Path:
    """Write payload to <photos_dir>/<sha256>.<extension>. Idempotent."""
    photos_dir.mkdir(parents=True, exist_ok=True)
    digest = hash_bytes(payload)
    path = photos_dir / f"{digest}.{extension.lstrip('.')}"
    if not path.exists():
        path.write_bytes(payload)
    return path


def normalize_for_api(payload: bytes) -> bytes:
    """Build a normalized derivative for the Anthropic vision API.

    - Downscales long edge to MAX_LONG_EDGE_PX if larger.
    - Strips EXIF.
    - Re-encodes JPEG @ NORMALIZED_QUALITY.
    """
    src = Image.open(io.BytesIO(payload))
    src.load()

    if src.mode not in ("RGB", "L"):
        src = src.convert("RGB")

    long_edge = max(src.size)
    if long_edge > MAX_LONG_EDGE_PX:
        scale = MAX_LONG_EDGE_PX / long_edge
        new_size = (int(src.size[0] * scale), int(src.size[1] * scale))
        src = src.resize(new_size, Image.Resampling.LANCZOS)

    out = io.BytesIO()
    # exif=b"" strips EXIF; subsampling=2 is JPEG default; optimize for size.
    src.save(out, format="JPEG", quality=NORMALIZED_QUALITY, optimize=True, exif=b"")
    return out.getvalue()
