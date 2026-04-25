"""Recognition client: orchestrates prompt → SDK call → parser."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from lorscan.services.recognition.client import RecognitionResult, identify

FIXTURE = Path(__file__).parent.parent / "fixtures" / "claude" / "good-3x3.json"


class FakeAnthropicMessage:
    def __init__(self, text: str, input_tokens: int, output_tokens: int,
                 cache_read_tokens: int = 0, cache_creation_tokens: int = 0):
        self.content = [type("TextBlock", (), {"type": "text", "text": text})()]
        self.usage = type("Usage", (), {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read_tokens,
            "cache_creation_input_tokens": cache_creation_tokens,
        })()


def test_identify_calls_sdk_with_cache_control_and_returns_parsed_result():
    fake_response_text = FIXTURE.read_text()
    fake_message = FakeAnthropicMessage(
        text=fake_response_text, input_tokens=1500, output_tokens=400,
    )

    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_message

    result = identify(
        image_bytes=b"\xff\xd8\xff fake jpeg",
        media_type="image/jpeg",
        anthropic_client=fake_client,
        model="claude-sonnet-4-6",
    )

    assert isinstance(result, RecognitionResult)
    assert result.parsed.page_type == "binder_3x3"
    assert len(result.parsed.cards) == 3
    assert result.usage.input_tokens == 1500
    assert result.usage.output_tokens == 400

    create_call = fake_client.messages.create.call_args
    kwargs = create_call.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    # System prompt must be in the cached form (list of blocks with cache_control).
    system = kwargs["system"]
    assert isinstance(system, list) and len(system) == 1
    assert system[0]["type"] == "text"
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    # User message must be present.
    messages = kwargs["messages"]
    assert messages[0]["role"] == "user"


def test_identify_retries_once_on_unparseable_response():
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        FakeAnthropicMessage(text="here is the result, not JSON", input_tokens=100, output_tokens=50),
        FakeAnthropicMessage(text=FIXTURE.read_text(), input_tokens=80, output_tokens=400),
    ]

    result = identify(
        image_bytes=b"\xff\xd8\xff",
        media_type="image/jpeg",
        anthropic_client=fake_client,
        model="claude-sonnet-4-6",
    )

    assert len(result.parsed.cards) == 3
    assert fake_client.messages.create.call_count == 2

    # Second call must include the strictness reminder in the messages list.
    second_call = fake_client.messages.create.call_args_list[1]
    msgs = second_call.kwargs["messages"]
    last = msgs[-1]
    flat_text = json.dumps(last)
    assert "JSON only" in flat_text or "no markdown" in flat_text.lower()
