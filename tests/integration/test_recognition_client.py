"""Recognition client (subprocess-based): orchestrates `claude -p` + parser."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from lorscan.services.recognition.client import (
    CliInvocationError,
    CliNotInstalledError,
    RecognitionResult,
    identify,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "claude" / "good-3x3.json"


def _fake_completed(
    stdout: str, *, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["claude"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _fake_cli_payload(
    *,
    response_text: str,
    input_tokens: int = 1500,
    output_tokens: int = 400,
    cost_usd: float = 0.012,
) -> str:
    return json.dumps(
        {
            "result": response_text,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
            "total_cost_usd": cost_usd,
        }
    )


def test_identify_runs_claude_subprocess_with_expected_flags(tmp_path: Path):
    photo = tmp_path / "binder.jpg"
    photo.write_bytes(b"\xff\xd8\xff fake jpeg")

    payload = _fake_cli_payload(response_text=FIXTURE.read_text())

    with (
        patch(
            "lorscan.services.recognition.client.shutil.which",
            return_value="/usr/local/bin/claude",
        ),
        patch(
            "lorscan.services.recognition.client.subprocess.run",
            return_value=_fake_completed(payload),
        ) as mock_run,
    ):
        result = identify(photo_path=photo, model="claude-sonnet-4-6")

    assert isinstance(result, RecognitionResult)
    assert result.parsed.page_type == "binder_3x3"
    assert len(result.parsed.cards) == 3
    assert result.usage.input_tokens == 1500
    assert result.usage.output_tokens == 400
    assert result.cost_usd == 0.012

    (call,) = mock_run.call_args_list
    cmd = call.args[0]
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "--output-format" in cmd and cmd[cmd.index("--output-format") + 1] == "json"
    assert "--system-prompt" in cmd
    assert "--allowed-tools" in cmd and cmd[cmd.index("--allowed-tools") + 1] == "Read"
    assert "--add-dir" in cmd
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "claude-sonnet-4-6"
    assert "--no-session-persistence" in cmd
    assert "--permission-mode" in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "auto"
    user_prompt = cmd[cmd.index("-p") + 1]
    assert user_prompt.startswith(f"@{photo.resolve()}")


def test_identify_passes_max_budget_when_set(tmp_path: Path):
    photo = tmp_path / "binder.jpg"
    photo.write_bytes(b"\xff\xd8\xff fake")
    payload = _fake_cli_payload(response_text=FIXTURE.read_text())

    with (
        patch(
            "lorscan.services.recognition.client.shutil.which",
            return_value="/usr/local/bin/claude",
        ),
        patch(
            "lorscan.services.recognition.client.subprocess.run",
            return_value=_fake_completed(payload),
        ) as mock_run,
    ):
        identify(photo_path=photo, model="claude-sonnet-4-6", max_budget_usd=0.50)

    cmd = mock_run.call_args.args[0]
    assert "--max-budget-usd" in cmd
    assert cmd[cmd.index("--max-budget-usd") + 1] == "0.5"


def test_identify_raises_when_cli_not_installed(tmp_path: Path):
    photo = tmp_path / "binder.jpg"
    photo.write_bytes(b"\xff\xd8\xff fake")

    with (
        patch("lorscan.services.recognition.client.shutil.which", return_value=None),
        pytest.raises(CliNotInstalledError),
    ):
        identify(photo_path=photo, model="claude-sonnet-4-6")


def test_identify_raises_when_subprocess_fails(tmp_path: Path):
    photo = tmp_path / "binder.jpg"
    photo.write_bytes(b"\xff\xd8\xff fake")

    failing = _fake_completed("", returncode=1, stderr="auth failed")
    with (
        patch(
            "lorscan.services.recognition.client.shutil.which",
            return_value="/usr/local/bin/claude",
        ),
        patch(
            "lorscan.services.recognition.client.subprocess.run",
            return_value=failing,
        ),
        pytest.raises(CliInvocationError, match="auth failed"),
    ):
        identify(photo_path=photo, model="claude-sonnet-4-6")


def test_identify_raises_when_photo_missing(tmp_path: Path):
    missing = tmp_path / "does-not-exist.jpg"
    with pytest.raises(FileNotFoundError):
        identify(photo_path=missing, model="claude-sonnet-4-6")
