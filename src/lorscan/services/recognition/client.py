"""Anthropic Messages API call orchestration with prompt caching + retry-on-prose."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from lorscan.services.recognition.parser import ParsedScan, ParseError, parse_response
from lorscan.services.recognition.prompt import build_system_prompt, build_user_message


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass(frozen=True)
class RecognitionResult:
    parsed: ParsedScan
    usage: TokenUsage
    request_payload: dict
    response_text: str


class AnthropicClient(Protocol):
    """Minimal interface for the parts of anthropic.Anthropic we use."""

    @property
    def messages(self) -> Any: ...


def identify(
    *,
    image_bytes: bytes,
    media_type: str,
    anthropic_client: AnthropicClient,
    model: str,
    max_tokens: int = 1500,
) -> RecognitionResult:
    """Call Claude vision and return a parsed scan.

    Retries once with a strictness reminder if the first response is unparseable.
    """
    system_prompt = build_system_prompt()
    user_message = build_user_message(image_bytes=image_bytes, media_type=media_type)

    system_blocks = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    messages: list[dict] = [user_message]

    request_payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_blocks,
        "messages": messages,
    }

    response = anthropic_client.messages.create(**request_payload)
    response_text = _extract_text(response)
    usage = _extract_usage(response)

    try:
        parsed = parse_response(response_text)
        return RecognitionResult(
            parsed=parsed,
            usage=usage,
            request_payload=request_payload,
            response_text=response_text,
        )
    except ParseError:
        # One retry with stricter instruction.
        messages_retry = list(messages) + [
            {"role": "assistant", "content": response_text},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Reply with a single JSON object only. "
                            "No prose, no markdown fences. JSON only."
                        ),
                    }
                ],
            },
        ]
        retry_payload = {**request_payload, "messages": messages_retry}
        response2 = anthropic_client.messages.create(**retry_payload)
        response_text2 = _extract_text(response2)
        usage2 = _extract_usage(response2)
        parsed2 = parse_response(response_text2)
        return RecognitionResult(
            parsed=parsed2,
            usage=TokenUsage(
                input_tokens=usage.input_tokens + usage2.input_tokens,
                output_tokens=usage.output_tokens + usage2.output_tokens,
                cache_read_tokens=usage.cache_read_tokens + usage2.cache_read_tokens,
                cache_creation_tokens=usage.cache_creation_tokens + usage2.cache_creation_tokens,
            ),
            request_payload=retry_payload,
            response_text=response_text2,
        )


def _extract_text(response: Any) -> str:
    blocks = getattr(response, "content", None) or []
    parts: list[str] = []
    for block in blocks:
        kind = getattr(block, "type", None)
        if kind == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts)


def _extract_usage(response: Any) -> TokenUsage:
    u = getattr(response, "usage", None)
    if u is None:
        return TokenUsage(input_tokens=0, output_tokens=0)
    return TokenUsage(
        input_tokens=int(getattr(u, "input_tokens", 0) or 0),
        output_tokens=int(getattr(u, "output_tokens", 0) or 0),
        cache_read_tokens=int(getattr(u, "cache_read_input_tokens", 0) or 0),
        cache_creation_tokens=int(getattr(u, "cache_creation_input_tokens", 0) or 0),
    )
