"""lorscan CLI entry point."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from lorscan.config import Config, load_config
from lorscan.services.matching import match_card
from lorscan.services.recognition.client import (
    CliInvocationError,
    CliNotInstalledError,
    identify,
)
from lorscan.storage.db import Database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lorscan", description="Lorcana collection manager.")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="Identify cards in a photo.")
    scan_p.add_argument("photo", type=Path, help="Path to a binder-page photo.")

    sync_p = sub.add_parser("sync-catalog", help="Sync card catalog from lorcana-api.com.")
    _ = sync_p

    version_p = sub.add_parser("version", help="Print version and exit.")
    _ = version_p

    args = parser.parse_args(argv)

    if args.command == "scan":
        cfg = load_config(env=os.environ)
        return scan_command(photo_path=args.photo, config=cfg)
    elif args.command == "version":
        from lorscan import __version__

        print(__version__)
        return 0
    elif args.command == "sync-catalog":
        print("sync-catalog: not yet wired in Plan 1; coming in Plan 2.", file=sys.stderr)
        return 2
    return 2


def scan_command(
    *,
    photo_path: Path,
    config: Config,
    db_path: Path | None = None,
) -> int:
    """Run the recognition + matching pipeline against a single photo."""
    if not photo_path.exists():
        print(f"error: photo not found: {photo_path}", file=sys.stderr)
        return 2

    try:
        result = identify(
            photo_path=photo_path,
            model=config.anthropic_model,
            max_budget_usd=config.per_scan_budget_usd,
        )
    except CliNotInstalledError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    except CliInvocationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 4

    db_file = db_path if db_path is not None else config.db_path
    db = Database.connect(str(db_file))
    db.migrate()

    print(f"\nScanned: {photo_path.name}")
    print(f"Page type: {result.parsed.page_type}")
    print(f"Cards detected: {len(result.parsed.cards)}\n")

    header = f"{'pos':<6}{'name':<32}{'#':<6}{'set':<5}{'conf':<8}{'match'}"
    print(header)
    print("-" * len(header))

    for card in result.parsed.cards:
        match = match_card(card, db=db)
        match_str = match.matched_card_id if match.matched_card_id else f"({match.match_method})"
        name = (card.name or "?")[:30]
        col = card.collector_number or "?"
        set_hint = card.set_hint or "-"
        print(
            f"{card.grid_position:<6}{name:<32}{col:<6}{set_hint:<5}{card.confidence:<8}{match_str}"
        )

    if result.parsed.issues:
        print("\nIssues reported by the model:")
        for issue in result.parsed.issues:
            print(f"  - {issue}")

    print(
        f"\nTokens — input: {result.usage.input_tokens}, "
        f"output: {result.usage.output_tokens}, "
        f"cache_read: {result.usage.cache_read_tokens}"
    )
    if result.cost_usd is not None:
        print(f"Cost: ${result.cost_usd:.4f}")

    db.close()
    return 0
