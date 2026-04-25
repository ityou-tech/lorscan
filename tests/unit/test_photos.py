"""Photo service: hashing, saving, format normalization."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from lorscan.services.photos import (
    ensure_supported_format,
    hash_bytes,
    save_original,
)


def _make_test_jpeg(width: int, height: int) -> bytes:
    """Build a tiny RGB JPEG of the requested dimensions."""
    img = Image.new("RGB", (width, height), color=(123, 45, 67))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_hash_bytes_is_deterministic():
    payload = b"hello world"
    assert hash_bytes(payload) == hash_bytes(payload)
    assert hash_bytes(payload) != hash_bytes(b"hello, world")
    assert len(hash_bytes(payload)) == 64  # sha256 hex


def test_save_original_writes_content_addressed_file(tmp_path: Path):
    payload = b"binary photo bytes"
    path = save_original(payload, photos_dir=tmp_path, extension="jpg")
    assert path.exists()
    assert path.parent == tmp_path
    assert path.read_bytes() == payload
    assert path.stem == hash_bytes(payload)
    assert path.suffix == ".jpg"


def test_save_original_dedupes_same_bytes(tmp_path: Path):
    payload = b"same exact bytes"
    p1 = save_original(payload, photos_dir=tmp_path, extension="jpg")
    p2 = save_original(payload, photos_dir=tmp_path, extension="jpg")
    assert p1 == p2
    assert len(list(tmp_path.iterdir())) == 1


def test_ensure_supported_format_passes_through_jpeg(tmp_path: Path):
    jpg = tmp_path / "photo.jpg"
    jpg.write_bytes(_make_test_jpeg(100, 100))
    with ensure_supported_format(jpg) as scan_path:
        assert scan_path == jpg
        assert scan_path.exists()


def test_ensure_supported_format_passes_through_png(tmp_path: Path):
    png = tmp_path / "photo.png"
    img = Image.new("RGB", (50, 50), color=(0, 128, 255))
    img.save(png, format="PNG")
    with ensure_supported_format(png) as scan_path:
        assert scan_path == png


def test_ensure_supported_format_rejects_unknown_extension(tmp_path: Path):
    weird = tmp_path / "photo.bmp"
    weird.write_bytes(b"")
    with (
        pytest.raises(ValueError, match="Unsupported image format"),
        ensure_supported_format(weird),
    ):
        pass


def test_ensure_supported_format_converts_heic_to_jpeg(tmp_path: Path):
    """HEIC input is transcoded to a JPEG sibling that persists, so the
    detail page can render it (browsers can't display HEIC)."""
    heic = tmp_path / "photo.heic"
    # Build a tiny HEIC by writing a JPEG and saving via Pillow as HEIF.
    img = Image.new("RGB", (50, 50), color=(200, 100, 50))
    img.save(heic, format="HEIF")
    assert heic.exists()

    preview_path = None
    with ensure_supported_format(heic) as scan_path:
        assert scan_path != heic
        assert scan_path.suffix == ".jpg"
        assert scan_path.exists()
        # The resulting file is a valid JPEG.
        out = Image.open(scan_path)
        assert out.format == "JPEG"
        preview_path = scan_path

    # Preview is persisted alongside the original (used by the detail
    # page to render the photo above the binder grid).
    assert preview_path is not None
    assert preview_path.exists()
    assert preview_path.parent == heic.parent
    # Original is untouched.
    assert heic.exists()


def test_ensure_supported_format_reuses_existing_heic_preview(tmp_path: Path):
    """Re-running on the same HEIC reuses the previously-written preview."""
    from lorscan.services.photos import jpeg_preview_path

    heic = tmp_path / "photo.heic"
    Image.new("RGB", (50, 50), color=(200, 100, 50)).save(heic, format="HEIF")

    with ensure_supported_format(heic) as first_path:
        first_mtime = first_path.stat().st_mtime_ns

    # The preview is at a deterministic path
    assert jpeg_preview_path(heic).exists()

    with ensure_supported_format(heic) as second_path:
        second_mtime = second_path.stat().st_mtime_ns

    assert first_path == second_path
    # Should not have been re-written.
    assert first_mtime == second_mtime
