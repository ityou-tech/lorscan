"""Load the hand-curated per-set category map from TOML."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SetMapEntry:
    set_code: str
    category_id: str
    category_path: str


def load_set_map(path: Path) -> list[SetMapEntry]:
    """Parse a TOML seed file into a list of SetMapEntry rows.

    Returns [] if the file has no `[[set]]` blocks (empty file or unrelated content).
    """
    data = tomllib.loads(path.read_text())
    entries = []
    for raw in data.get("set", []):
        entries.append(
            SetMapEntry(
                set_code=str(raw["code"]),
                category_id=str(raw["category_id"]),
                category_path=str(raw["category_path"]),
            )
        )
    return entries
