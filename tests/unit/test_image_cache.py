"""Tests for the catalog image cache + manual override path."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pytest
from PIL import Image

from lorscan.services.image_cache import (
    cache_path_for,
    fetch_all,
    find_override,
)


def _png_bytes(color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    img = Image.new("RGB", (8, 8), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_cache_path_for_uses_url_suffix(tmp_path: Path):
    p = cache_path_for("WHI-102", "https://example.com/x.jpg?v=1", cache_dir=tmp_path)
    assert p == tmp_path / "WHI-102.jpg"


def test_find_override_returns_first_matching_extension(tmp_path: Path):
    (tmp_path / "WHI-102.jpg").write_bytes(_png_bytes())
    (tmp_path / "WHI-102.png").write_bytes(_png_bytes())  # second priority
    found = find_override("WHI-102", overrides_dir=tmp_path)
    # OVERRIDE_EXTENSIONS lists .jpg before .png, so jpg wins.
    assert found == tmp_path / "WHI-102.jpg"


def test_find_override_returns_none_when_directory_missing(tmp_path: Path):
    assert find_override("WHI-102", overrides_dir=tmp_path / "does-not-exist") is None


def test_find_override_ignores_zero_byte_files(tmp_path: Path):
    (tmp_path / "WHI-102.jpg").write_bytes(b"")
    assert find_override("WHI-102", overrides_dir=tmp_path) is None


def test_fetch_all_prefers_override_and_skips_network(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    overrides_dir = tmp_path / "overrides"
    overrides_dir.mkdir()
    (overrides_dir / "WHI-102.jpg").write_bytes(_png_bytes())

    # A bogus URL — if this were ever fetched the test would fail with a
    # connection error or the FetchResult would carry an error string.
    cards = [("WHI-102", "https://does-not-resolve.invalid/whi102.jpg")]
    results = asyncio.run(
        fetch_all(cards, cache_dir=cache_dir, overrides_dir=overrides_dir)
    )

    assert len(results) == 1
    r = results[0]
    assert r.error is None
    assert r.path == overrides_dir / "WHI-102.jpg"
    assert r.from_override is True
    # Override must NOT have been copied into the cache dir — the indexer
    # opens whatever path the FetchResult points to, no copy needed.
    assert not (cache_dir / "WHI-102.jpg").exists()


def test_fetch_all_override_wins_over_existing_cached_download(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    overrides_dir = tmp_path / "overrides"
    overrides_dir.mkdir()
    (cache_dir / "WHI-102.jpg").write_bytes(_png_bytes(color=(255, 0, 0)))
    (overrides_dir / "WHI-102.jpg").write_bytes(_png_bytes(color=(0, 255, 0)))

    cards = [("WHI-102", "https://example.com/whi102.jpg")]
    results = asyncio.run(
        fetch_all(cards, cache_dir=cache_dir, overrides_dir=overrides_dir)
    )

    assert results[0].path == overrides_dir / "WHI-102.jpg"
    assert results[0].from_override is True


@pytest.mark.parametrize("ext", [".jpg", ".png", ".webp", ".avif"])
def test_find_override_supports_common_image_formats(tmp_path: Path, ext: str):
    target = tmp_path / f"WIN-169{ext}"
    target.write_bytes(b"\x00\x01\x02\x03")
    assert find_override("WIN-169", overrides_dir=tmp_path) == target
