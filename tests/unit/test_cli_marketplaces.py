"""CLI smoke tests for `lorscan marketplaces ...`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from lorscan.cli import main


def test_marketplaces_status_prints_no_sweep_yet(
    tmp_data_dir: Path, capsys
) -> None:
    rc = main(["marketplaces", "status"])
    assert rc == 0
    captured = capsys.readouterr()
    out = captured.out.lower()
    assert "no sweep" in out or "never" in out or "lorscan marketplaces refresh" in out


def test_marketplaces_refresh_invokes_sweep(
    tmp_data_dir: Path, capsys
) -> None:
    fake_result = type(
        "R",
        (),
        {
            "sweep_id": 1,
            "status": "ok",
            "listings_seen": 5,
            "listings_matched": 4,
            "errors": 0,
        },
    )()
    with patch(
        "lorscan.cli._run_marketplace_sweep",
        new=AsyncMock(return_value=fake_result),
    ) as mock_sweep:
        rc = main(["marketplaces", "refresh", "--shop", "bazaarofmagic"])
    assert rc == 0
    mock_sweep.assert_called_once()
    out = capsys.readouterr().out.lower()
    assert "5" in out
    assert "ok" in out


def test_marketplaces_refresh_returns_nonzero_on_failed_sweep(
    tmp_data_dir: Path, capsys
) -> None:
    fake_result = type(
        "R",
        (),
        {
            "sweep_id": 2,
            "status": "failed",
            "listings_seen": 0,
            "listings_matched": 0,
            "errors": 11,
        },
    )()
    with patch(
        "lorscan.cli._run_marketplace_sweep",
        new=AsyncMock(return_value=fake_result),
    ):
        rc = main(["marketplaces", "refresh"])
    assert rc != 0
    out = capsys.readouterr().out.lower()
    assert "failed" in out


def test_marketplaces_refresh_propagates_runtime_error(
    tmp_data_dir: Path, capsys
) -> None:
    """If the orchestrator raises (e.g. no categories seeded), the CLI
    surfaces the message and returns nonzero."""
    with patch(
        "lorscan.cli._run_marketplace_sweep",
        new=AsyncMock(side_effect=RuntimeError("No enabled set categories")),
    ):
        rc = main(["marketplaces", "refresh"])
    assert rc != 0
    err = capsys.readouterr().err.lower()
    assert "no enabled set categories" in err or "runtimeerror" in err


def test_marketplaces_refresh_passes_only_set_arg(
    tmp_data_dir: Path,
) -> None:
    """--set ROF should propagate to the orchestrator's only_set kwarg."""
    fake_result = type(
        "R",
        (),
        {
            "sweep_id": 3, "status": "ok", "listings_seen": 1,
            "listings_matched": 1, "errors": 0,
        },
    )()
    with patch(
        "lorscan.cli._run_marketplace_sweep",
        new=AsyncMock(return_value=fake_result),
    ) as mock_sweep:
        rc = main(["marketplaces", "refresh", "--set", "ROF"])
    assert rc == 0
    # Inspect the call kwargs.
    call_kwargs = mock_sweep.call_args.kwargs
    assert call_kwargs.get("set_code") == "ROF"
