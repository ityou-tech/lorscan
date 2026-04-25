"""Credential-prefix dispatch in the CLI's Anthropic client builder."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from lorscan.cli import _build_anthropic_client


def test_oauth_token_uses_auth_token_kwarg():
    fake_anthropic_cls = MagicMock()
    with patch("anthropic.Anthropic", fake_anthropic_cls):
        _build_anthropic_client("sk-ant-oat01-EXAMPLE")
    fake_anthropic_cls.assert_called_once_with(auth_token="sk-ant-oat01-EXAMPLE")


def test_api_key_uses_api_key_kwarg():
    fake_anthropic_cls = MagicMock()
    with patch("anthropic.Anthropic", fake_anthropic_cls):
        _build_anthropic_client("sk-ant-api03-EXAMPLE")
    fake_anthropic_cls.assert_called_once_with(api_key="sk-ant-api03-EXAMPLE")


def test_unknown_prefix_treated_as_api_key():
    """Defensive: unknown prefix defaults to api_key (most common case)."""
    fake_anthropic_cls = MagicMock()
    with patch("anthropic.Anthropic", fake_anthropic_cls):
        _build_anthropic_client("some-other-token")
    fake_anthropic_cls.assert_called_once_with(api_key="some-other-token")
