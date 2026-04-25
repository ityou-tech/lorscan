"""Recognition via the `claude` CLI subprocess.

Uses Claude Code in headless print mode (`claude -p ... --output-format json`)
which authenticates via whatever the CLI knows about — most importantly,
this includes `claude setup-token` (Max-subscription OAuth) on the
keychain, so users with a Claude Max plan can run lorscan without a
separate Anthropic API key.

The CLI handles credential discovery itself (keychain → env vars →
ANTHROPIC_API_KEY → ...), so lorscan never sees a token directly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from lorscan.services.recognition.parser import ParsedScan, ParseError, parse_response
from lorscan.services.recognition.prompt import build_system_prompt

DEFAULT_TIMEOUT_SECONDS = 600


class CliNotInstalledError(RuntimeError):
    """The `claude` CLI was not found on PATH."""


class CliInvocationError(RuntimeError):
    """`claude -p` exited non-zero. stderr is preserved on the exception."""

    def __init__(self, returncode: int, stderr: str) -> None:
        super().__init__(f"claude CLI exited with code {returncode}: {stderr.strip()[:400]}")
        self.returncode = returncode
        self.stderr = stderr


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
    cost_usd: float | None = None


def identify(
    *,
    photo_path: Path,
    model: str,
    max_budget_usd: float | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> RecognitionResult:
    """Identify Lorcana cards in a photo via the `claude` CLI subprocess.

    Args:
        photo_path: absolute or relative path to a JPEG/PNG photo on disk.
        model: model alias or full name (e.g. "claude-sonnet-4-6").
        max_budget_usd: per-call dollar cap (passed via --max-budget-usd).
        timeout_seconds: hard wall-clock cap on the subprocess.

    Returns a RecognitionResult with the parsed scan, token usage, and
    estimated cost (when the CLI provides it).

    Raises:
        FileNotFoundError: photo_path doesn't exist.
        CliNotInstalledError: the `claude` binary is not on PATH.
        CliInvocationError: the CLI exited non-zero (auth, budget, etc.).
        ParseError: the model's text response could not be parsed as JSON.
    """
    photo_abs = photo_path.expanduser().resolve()
    if not photo_abs.exists():
        raise FileNotFoundError(f"Photo not found: {photo_abs}")

    if shutil.which("claude") is None:
        raise CliNotInstalledError(
            "The `claude` CLI is not on PATH. Install Claude Code and run "
            "`claude setup-token` (for Max-subscription auth) or set "
            "ANTHROPIC_API_KEY before running lorscan."
        )

    system_prompt = build_system_prompt()
    # `@<path>` is Claude Code's syntax for referencing a local file in the
    # user message. The Read tool ingests image content directly into the
    # conversation, so the model "sees" the binder page.
    user_prompt = (
        f"@{photo_abs}\n\n"
        "Identify the cards visible in this binder page. "
        "Reply with a single JSON object matching the schema in the system "
        "prompt. No prose, no markdown fences."
    )

    cmd = [
        "claude",
        "-p",
        user_prompt,
        "--output-format",
        "json",
        "--system-prompt",
        system_prompt,
        "--allowed-tools",
        "Read",
        # `auto` lets Claude Code's classifier permit safe tool uses
        # (Read on an explicitly --add-dir'd path) without an interactive
        # prompt. `default` would prompt and hang the subprocess (no TTY).
        "--permission-mode",
        "auto",
        "--add-dir",
        str(photo_abs.parent),
        "--model",
        model,
        "--no-session-persistence",
    ]
    if max_budget_usd is not None:
        cmd.extend(["--max-budget-usd", str(max_budget_usd)])

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )

    if proc.returncode != 0:
        raise CliInvocationError(proc.returncode, proc.stderr)

    cli_output = json.loads(proc.stdout)
    response_text = str(cli_output.get("result", ""))

    usage_raw = cli_output.get("usage") or {}
    usage = TokenUsage(
        input_tokens=int(usage_raw.get("input_tokens") or 0),
        output_tokens=int(usage_raw.get("output_tokens") or 0),
        cache_read_tokens=int(usage_raw.get("cache_read_input_tokens") or 0),
        cache_creation_tokens=int(usage_raw.get("cache_creation_input_tokens") or 0),
    )
    cost_raw = cli_output.get("total_cost_usd")
    cost_usd = float(cost_raw) if cost_raw is not None else None

    request_payload = {
        "cmd": cmd,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "model": model,
    }

    try:
        parsed = parse_response(response_text)
    except ParseError:
        # The CLI doesn't expose a follow-up retry hook the way the SDK did,
        # but ParseError already carries the raw response. Surface it.
        raise

    return RecognitionResult(
        parsed=parsed,
        usage=usage,
        request_payload=request_payload,
        response_text=response_text,
        cost_usd=cost_usd,
    )
