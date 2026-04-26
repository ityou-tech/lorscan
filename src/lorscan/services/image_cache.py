"""Local cache of catalog card images.

Fetches each card's `image_url` once and saves to:
    ~/.lorscan/cache/images/<card_id>.<ext>

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
from dataclasses import dataclass
from pathlib import Path

import httpx

DEFAULT_CONCURRENCY = 16
DEFAULT_TIMEOUT_SECONDS = 30
OVERRIDE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".avif")


@dataclass(frozen=True)
class FetchResult:
    card_id: str
    path: Path | None
    error: str | None = None
    from_override: bool = False


def cache_path_for(card_id: str, image_url: str, *, cache_dir: Path) -> Path:
    """Pick the local cache path for a card. Suffix derived from URL."""
    suffix = Path(image_url.split("?")[0]).suffix.lower() or ".png"
    safe_id = card_id.replace("/", "_").replace("\\", "_")
    return cache_dir / f"{safe_id}{suffix}"


def find_override(card_id: str, *, overrides_dir: Path) -> Path | None:
    """Return a user-supplied override image for `card_id` if one exists."""
    if not overrides_dir.is_dir():
        return None
    safe_id = card_id.replace("/", "_").replace("\\", "_")
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
