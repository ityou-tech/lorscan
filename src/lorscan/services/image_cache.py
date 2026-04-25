"""Local cache of catalog card images.

Fetches each card's `image_url` once and saves to:
    ~/.lorscan/cache/images/<card_id>.<ext>

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


@dataclass(frozen=True)
class FetchResult:
    card_id: str
    path: Path | None
    error: str | None = None


def cache_path_for(card_id: str, image_url: str, *, cache_dir: Path) -> Path:
    """Pick the local cache path for a card. Suffix derived from URL."""
    suffix = Path(image_url.split("?")[0]).suffix.lower() or ".png"
    safe_id = card_id.replace("/", "_").replace("\\", "_")
    return cache_dir / f"{safe_id}{suffix}"


async def _fetch_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    card_id: str,
    image_url: str,
    *,
    cache_dir: Path,
) -> FetchResult:
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
    concurrency: int = DEFAULT_CONCURRENCY,
    on_progress=None,
) -> list[FetchResult]:
    """Fetch every (card_id, image_url) pair into the local cache.

    Skips cards whose target file already exists. Returns one FetchResult
    per input. Progress callback (if given) is called with (done, total)
    after each completion.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)
    results: list[FetchResult] = []
    timeout = httpx.Timeout(DEFAULT_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        coros = [
            _fetch_one(client, sem, card_id, url, cache_dir=cache_dir) for card_id, url in cards
        ]
        total = len(coros)
        for done, fut in enumerate(asyncio.as_completed(coros), start=1):
            r = await fut
            results.append(r)
            if on_progress is not None:
                on_progress(done, total)
    return results


__all__ = ["FetchResult", "cache_path_for", "fetch_all"]
