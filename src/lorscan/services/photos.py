"""Photo service: hashing, saving, format normalization (HEIC→JPEG)."""

from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Iterator
from pathlib import Path

from PIL import Image

# Register HEIF/HEIC support. iPhone photos default to HEIC, which Pillow
# (and downstream consumers like CLIP's preprocessor) doesn't read natively.
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover — pillow-heif is in deps
    pass

JPEG_TRANSCODE_QUALITY = 92

# Image formats every downstream consumer can handle directly. HEIC/HEIF
# get transcoded; anything else is rejected.
SUPPORTED_FOR_PROCESSING = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


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


def jpeg_preview_path(photo_path: Path) -> Path:
    """Return the path the JPEG sibling would live at for an HEIC original.

    For non-HEIC input, returns the input itself — there's nothing to
    transcode, the browser can already render it.
    """
    if photo_path.suffix.lower() in (".heic", ".heif"):
        return photo_path.with_suffix(photo_path.suffix + ".preview.jpg")
    return photo_path


@contextlib.contextmanager
def ensure_supported_format(photo_path: Path) -> Iterator[Path]:
    """Yield a Path to an image in a directly-processable format.

    If the input is already JPEG/PNG/GIF/WEBP, yields the original path.
    If the input is HEIC/HEIF, transcodes to a JPEG saved next to the
    original (`<photo>.preview.jpg`) and yields that. The preview is
    persisted, not deleted, so the detail page can render the photo —
    browsers can't display HEIC, so the JPEG is the only viable preview.
    Re-running on the same input is idempotent: if the preview already
    exists it's reused.

    Raises:
        ValueError: extension not recognized as a supported or convertible
            image format.
    """
    suffix = photo_path.suffix.lower()
    if suffix in SUPPORTED_FOR_PROCESSING:
        yield photo_path
        return

    if suffix in (".heic", ".heif"):
        preview = jpeg_preview_path(photo_path)
        if not preview.exists():
            img = Image.open(photo_path)
            img.load()
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(preview, format="JPEG", quality=JPEG_TRANSCODE_QUALITY, optimize=True)
        yield preview
        return

    raise ValueError(
        f"Unsupported image format: {suffix!r}. "
        f"Use one of {sorted(SUPPORTED_FOR_PROCESSING | {'.heic', '.heif'})}."
    )
