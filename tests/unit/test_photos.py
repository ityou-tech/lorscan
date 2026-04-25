"""Photo service: hashing, saving, normalizing for the API."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from lorscan.services.photos import (
    hash_bytes,
    normalize_for_api,
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


def test_normalize_for_api_downscales_large_image():
    big = _make_test_jpeg(3000, 2000)
    normalized = normalize_for_api(big)
    img = Image.open(io.BytesIO(normalized))
    assert max(img.size) <= 1568


def test_normalize_for_api_preserves_small_image():
    small = _make_test_jpeg(800, 600)
    normalized = normalize_for_api(small)
    img = Image.open(io.BytesIO(normalized))
    assert img.size == (800, 600)


def test_normalize_for_api_strips_exif():
    # Synthesize an image with EXIF.
    img = Image.new("RGB", (1000, 1000), color=(10, 20, 30))
    buf = io.BytesIO()
    exif_data = img.getexif()
    exif_data[0x0112] = 6  # Orientation
    img.save(buf, format="JPEG", quality=90, exif=exif_data.tobytes())
    src = buf.getvalue()
    out = normalize_for_api(src)
    out_img = Image.open(io.BytesIO(out))
    assert out_img.getexif() == {} or len(out_img.getexif()) == 0
