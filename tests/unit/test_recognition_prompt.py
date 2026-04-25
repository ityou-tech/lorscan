"""Recognition prompts: snapshot-tested system + user message builders."""
from __future__ import annotations

import base64

from syrupy.assertion import SnapshotAssertion

from lorscan.services.recognition.prompt import (
    build_system_prompt,
    build_user_message,
)


def test_system_prompt_snapshot(snapshot: SnapshotAssertion):
    """Snapshot-test the entire system prompt. Drift breaks cache + recognition."""
    prompt = build_system_prompt()
    assert prompt == snapshot


def test_system_prompt_contains_required_lexicon():
    prompt = build_system_prompt()
    # Lexicon membership tests — these are robust to wording changes.
    for ink in ("Amber", "Amethyst", "Emerald", "Ruby", "Sapphire", "Steel"):
        assert ink in prompt
    for finish in ("regular", "cold_foil", "promo", "enchanted"):
        assert finish in prompt
    # Suffix preservation rule must be present verbatim.
    assert "exactly as it appears" in prompt.lower() or "exact" in prompt.lower()
    assert "1a" in prompt or "letter suffix" in prompt.lower()


def test_user_message_includes_image_and_instruction():
    image_bytes = b"\xff\xd8\xff fake jpeg"
    msg = build_user_message(image_bytes=image_bytes, media_type="image/jpeg")

    assert msg["role"] == "user"
    content = msg["content"]
    assert isinstance(content, list)
    # First block: the image.
    assert content[0]["type"] == "image"
    assert content[0]["source"]["type"] == "base64"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert content[0]["source"]["data"] == base64.standard_b64encode(image_bytes).decode("ascii")
    # Second block: the text instruction.
    assert content[1]["type"] == "text"
    assert "binder" in content[1]["text"].lower() or "identify" in content[1]["text"].lower()
