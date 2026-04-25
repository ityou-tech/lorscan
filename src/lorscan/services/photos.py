"""Photo service: hashing, saving, in-memory normalization for the API."""

from __future__ import annotations

import contextlib
import hashlib
import io
import tempfile
from collections.abc import Iterator
from pathlib import Path

from PIL import Image

# Register HEIF/HEIC support. iPhone photos default to HEIC, which Claude
# vision does not accept directly — we have to transcode to JPEG before
# sending. pillow-heif registers the format as a Pillow plugin.
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover — pillow-heif is in deps; only triggers in dev
    pass

MAX_LONG_EDGE_PX = 1568  # Anthropic's recommended max for vision input
NORMALIZED_QUALITY = 85
JPEG_TRANSCODE_QUALITY = 92

# Image formats Claude vision accepts directly. Anything else (notably
# HEIC/HEIF from iPhones) must be transcoded to JPEG first.
SUPPORTED_FOR_VISION = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


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


@contextlib.contextmanager
def ensure_supported_format(photo_path: Path) -> Iterator[Path]:
    """Yield a Path to an image Claude vision can process directly.

    If the input is already in a supported format (JPEG, PNG, GIF, WEBP),
    yields the original path unchanged.

    If the input is HEIC/HEIF (iPhone default), transcodes to a temporary
    JPEG and yields its path. The temp file is deleted on exit.

    Raises:
        ValueError: extension not recognized as a supported or convertible
            image format.
    """
    suffix = photo_path.suffix.lower()
    if suffix in SUPPORTED_FOR_VISION:
        yield photo_path
        return

    if suffix in (".heic", ".heif"):
        with tempfile.NamedTemporaryFile(prefix="lorscan-", suffix=".jpg", delete=False) as tf:
            temp_path = Path(tf.name)
        try:
            img = Image.open(photo_path)
            img.load()
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(temp_path, format="JPEG", quality=JPEG_TRANSCODE_QUALITY, optimize=True)
            yield temp_path
        finally:
            temp_path.unlink(missing_ok=True)
        return

    raise ValueError(
        f"Unsupported image format: {suffix!r}. "
        f"Use one of {sorted(SUPPORTED_FOR_VISION | {'.heic', '.heif'})}."
    )


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
