"""Download LorcanaJSON's allCards.json once per sync.

The whole catalogue is a single static JSON file (~5–15 MB). We don't
do incremental sync; the cost of a full refetch is well under 30 s on
a typical home connection and the file's metadata.formatVersion makes
schema-change detection trivial later if we want it.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

LORCANA_JSON_URL = "https://lorcanajson.org/files/current/en/allCards.json"
log = logging.getLogger(__name__)


async def fetch_all_cards(client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Fetch the full LorcanaJSON allCards.json payload.

    Caller may pass a pre-configured `httpx.AsyncClient` (for testing
    via `respx`); otherwise a fresh one is created and closed.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=60.0)
    try:
        log.info("Fetching LorcanaJSON: %s", LORCANA_JSON_URL)
        response = await client.get(LORCANA_JSON_URL)
        response.raise_for_status()
        payload = response.json()
        log.info(
            "LorcanaJSON: %d cards, format v%s",
            len(payload.get("cards", [])),
            payload.get("metadata", {}).get("formatVersion", "?"),
        )
        return payload
    finally:
        if own_client:
            await client.aclose()
