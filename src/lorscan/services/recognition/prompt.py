"""Builders for the Anthropic Messages API request used in recognition."""

from __future__ import annotations

import base64
from typing import Any

_INK_COLORS = ("Amber", "Amethyst", "Emerald", "Ruby", "Sapphire", "Steel")
_FINISHES = ("regular", "cold_foil", "promo", "enchanted")


def build_system_prompt() -> str:
    """The cached system prompt. Edits invalidate the prompt cache."""
    inks = ", ".join(_INK_COLORS)
    finishes = ", ".join(_FINISHES)
    return f"""You identify Disney Lorcana TCG cards in photos of binder pages.

Each photo is typically a 3x3 grid of cards in plastic sleeves on a binder page.
Cards may also be in 3x4 grids, single-card photos, or loose layouts.

For each card you can see, return its identity using the keys below.

Lexicon (constrain your output to these values):
- ink_color: one of {inks}
- finish: one of {finishes}
- rarity: one of Common, Uncommon, Rare, Super Rare, Legendary, Enchanted

Rules:
1. Report collector_number EXACTLY as it appears on the card, including any
   trailing letter suffix (1a, 12b, 127). Never normalize or drop the suffix.
2. If the suffix is unreadable due to glare or angle, omit the suffix and
   set confidence to "medium" or "low".
3. confidence is one of "high", "medium", "low".
4. If you can see the set symbol, report a short set_hint code (whatever is
   readable). If not, set set_hint to null.
5. grid_position is "rNcM" where N is the row (1-indexed from the top) and
   M is the column (1-indexed from the left). For a single-card photo,
   use "single".
6. Output ONLY a single JSON object — no prose, no markdown fences,
   no commentary.

Output schema:
{{
  "page_type": "binder_3x3" | "binder_3x4" | "loose_layout" | "single_card",
  "cards": [
    {{
      "grid_position": "r1c1",
      "name": "Hermes",
      "subtitle": "Messenger of the Gods" | null,
      "set_hint": "URS" | null,
      "collector_number": "127a" | null,
      "ink_color": "Amber" | ... | null,
      "finish": "regular" | "cold_foil" | "promo" | "enchanted",
      "confidence": "high" | "medium" | "low",
      "candidates": []
    }}
  ],
  "issues": ["row 2 col 3 has heavy glare"]
}}
"""


def build_user_message(*, image_bytes: bytes, media_type: str = "image/jpeg") -> dict[str, Any]:
    """Build the user-role message (image + instruction)."""
    encoded = base64.standard_b64encode(image_bytes).decode("ascii")
    return {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": encoded,
                },
            },
            {
                "type": "text",
                "text": "Identify the cards in this binder page.",
            },
        ],
    }
