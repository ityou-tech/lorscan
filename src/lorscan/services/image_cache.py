"""Local cache of catalog card images.

Fetches each card's `image_url` once and saves to:
    ~/.lorscan/cache/images/<card_id>.<url_hash>.<ext>

The `<url_hash>` is a short hash of the image URL — when the catalog
gives the same `card_id` a different URL on a later sync (e.g. a stale
promo URL gets replaced with the correct main-set URL), the cache key
changes and the next fetch redownloads instead of silently serving the
old bytes. Old-format files (or files under any earlier URL hash) are
purged on first re-fetch.

Manual overrides (any image format Pillow can read) take precedence:
    ~/.lorscan/overrides/<card_id>.<ext>

The override path exists because the upstream catalog occasionally hands
out URLs whose content-hash points to nothing (publisher-side bug). When
that happens the indexer would otherwise silently skip the card and any
binder slot containing it would be misclassified as its closest neighbor
in art space — much worse than emitting "empty cell". Dropping a JPG/PNG
into the overrides directory gets the card back into the embedding index.

Used by:
- The CLIP indexer (Phase A) to embed every card image.
- The web UI (Phase C) to display catalog thumbnails in the binder
  visualization without going to the network on every page render.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from dataclasses import dataclass
from pathlib import Path

import httpx

DEFAULT_CONCURRENCY = 16
DEFAULT_TIMEOUT_SECONDS = 30
OVERRIDE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".avif")
URL_HASH_LEN = 8


def _safe_id(card_id: str) -> str:
    return card_id.replace("/", "_").replace("\\", "_")


def _url_hash(image_url: str) -> str:
    return hashlib.sha256(image_url.encode("utf-8")).hexdigest()[:URL_HASH_LEN]


@dataclass(frozen=True)
class FetchResult:
    card_id: str
    path: Path | None
    error: str | None = None
    from_override: bool = False


def cache_path_for(card_id: str, image_url: str, *, cache_dir: Path) -> Path:
    """Pick the local cache path for a card.

    The filename embeds a short hash of `image_url` as
    `<card_id>.<hash>.<ext>`. When the catalog hands the same `card_id` a
    different URL on a later sync (a recovered upstream typo, a new
    main-set URL replacing a stale promo URL, etc.), the cache key
    changes — so the file-existence check in `_fetch_one` misses and
    forces a re-download instead of silently returning the old bytes.

    The previous scheme keyed on `card_id` alone, which let stale promo
    art masquerade as main-set art indefinitely once it was cached.
    """
    suffix = Path(image_url.split("?")[0]).suffix.lower() or ".png"
    return cache_dir / f"{_safe_id(card_id)}.{_url_hash(image_url)}{suffix}"


def _purge_stale_cache_files(card_id: str, *, keep: Path, cache_dir: Path) -> None:
    """Remove leftover cache files for `card_id` whose URL hash differs
    from `keep` (or that pre-date the URL-hash naming scheme entirely).
    Quietly ignores filesystem races and missing parent dirs."""
    if not cache_dir.is_dir():
        return
    for stale in cache_dir.glob(f"{_safe_id(card_id)}.*"):
        if stale == keep:
            continue
        with contextlib.suppress(OSError):
            stale.unlink()


def find_override(card_id: str, *, overrides_dir: Path) -> Path | None:
    """Return a user-supplied override image for `card_id` if one exists.

    Overrides are keyed by `card_id` only (no URL hash) — they're authored
    by humans dropping files into the overrides dir, so there's no URL to
    track and the simpler `<card_id>.<ext>` layout matches what users
    type."""
    if not overrides_dir.is_dir():
        return None
    safe_id = _safe_id(card_id)
    for ext in OVERRIDE_EXTENSIONS:
        candidate = overrides_dir / f"{safe_id}{ext}"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


async def _fetch_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    card_id: str,
    image_url: str,
    *,
    cache_dir: Path,
    overrides_dir: Path | None = None,
) -> FetchResult:
    if overrides_dir is not None:
        override = find_override(card_id, overrides_dir=overrides_dir)
        if override is not None:
            return FetchResult(card_id=card_id, path=override, from_override=True)
    target = cache_path_for(card_id, image_url, cache_dir=cache_dir)
    if target.exists() and target.stat().st_size > 0:
        return FetchResult(card_id=card_id, path=target)
    async with sem:
        try:
            resp = await client.get(image_url)
            resp.raise_for_status()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(resp.content)
            _purge_stale_cache_files(card_id, keep=target, cache_dir=cache_dir)
            return FetchResult(card_id=card_id, path=target)
        except Exception as e:
            return FetchResult(card_id=card_id, path=None, error=str(e))


async def fetch_all(
    cards: list[tuple[str, str]],
    *,
    cache_dir: Path,
    overrides_dir: Path | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    on_progress=None,
) -> list[FetchResult]:
    """Fetch every (card_id, image_url) pair into the local cache.

    Skips cards whose target file already exists. Returns one FetchResult
    per input. Progress callback (if given) is called with (done, total)
    after each completion. If `overrides_dir` is given and a file matching
    `<card_id>.<ext>` is present there, that file is used instead of the
    URL — overrides win even when a download already exists.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)
    results: list[FetchResult] = []
    timeout = httpx.Timeout(DEFAULT_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        coros = [
            _fetch_one(
                client, sem, card_id, url, cache_dir=cache_dir, overrides_dir=overrides_dir
            )
            for card_id, url in cards
        ]
        total = len(coros)
        for done, fut in enumerate(asyncio.as_completed(coros), start=1):
            r = await fut
            results.append(r)
            if on_progress is not None:
                on_progress(done, total)
    return results


__all__ = ["FetchResult", "OVERRIDE_EXTENSIONS", "cache_path_for", "fetch_all", "find_override"]
