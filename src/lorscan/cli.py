"""lorscan CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from lorscan.config import Config, load_config
from lorscan.services.catalog import sync_catalog
from lorscan.services.matching import match_card
from lorscan.services.photos import ensure_supported_format
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
    scan_p.add_argument(
        "--set",
        dest="set_code",
        default=None,
        help=(
            "Restrict matching to this Lorcana set code (e.g. 'TFC', 'SSK', 'ARI'). "
            "Use when you know all cards in the photo are from one set — "
            "drops candidate counts dramatically."
        ),
    )

    sync_p = sub.add_parser("sync-catalog", help="Sync card catalog from lorcana-api.com.")
    _ = sync_p

    serve_p = sub.add_parser("serve", help="Run the local web UI on http://localhost:<port>.")
    serve_p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    serve_p.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    serve_p.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload on file changes (dev mode)",
    )

    version_p = sub.add_parser("version", help="Print version and exit.")
    _ = version_p

    args = parser.parse_args(argv)

    if args.command == "scan":
        cfg = load_config(env=os.environ)
        return scan_command(
            photo_path=args.photo,
            config=cfg,
            binder_set_code=args.set_code,
        )
    elif args.command == "version":
        from lorscan import __version__

        print(__version__)
        return 0
    elif args.command == "sync-catalog":
        cfg = load_config(env=os.environ)
        return sync_catalog_command(config=cfg)
    elif args.command == "serve":
        return serve_command(host=args.host, port=args.port, reload=args.reload)
    return 2


def scan_command(
    *,
    photo_path: Path,
    config: Config,
    db_path: Path | None = None,
    binder_set_code: str | None = None,
) -> int:
    """Run the recognition + matching pipeline against a single photo."""
    if not photo_path.exists():
        print(f"error: photo not found: {photo_path}", file=sys.stderr)
        return 2

    try:
        with ensure_supported_format(photo_path) as scan_path:
            if scan_path != photo_path:
                print(f"Transcoded {photo_path.suffix} → JPEG for Claude vision compatibility.")
            result = identify(
                photo_path=scan_path,
                model=config.anthropic_model,
                max_budget_usd=config.per_scan_budget_usd,
            )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
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
    if binder_set_code:
        print(f"Restricting matches to set: {binder_set_code}")
    print(f"Page type: {result.parsed.page_type}")
    print(f"Cards detected: {len(result.parsed.cards)}\n")

    # Match each card once and remember the result for both the table and the
    # ambiguous-candidates breakdown below.
    cell_matches = [
        (c, match_card(c, db=db, binder_set_code=binder_set_code)) for c in result.parsed.cards
    ]

    header = f"{'pos':<6}{'name':<32}{'#':<6}{'set':<5}{'conf':<8}{'match'}"
    print(header)
    print("-" * len(header))

    for card, match in cell_matches:
        if match.matched_card_id:
            match_str = match.matched_card_id
        elif match.match_method == "ambiguous_suffix":
            match_str = f"(ambiguous: {len(match.candidates)} candidates)"
        else:
            match_str = f"({match.match_method})"
        name = (card.name or "?")[:30]
        col = card.collector_number or "?"
        set_hint = card.set_hint or "-"
        print(
            f"{card.grid_position:<6}{name:<32}{col:<6}{set_hint:<5}{card.confidence:<8}{match_str}"
        )

    # If any cells were ambiguous, list the candidates inline so the user
    # can see what lorscan recognized and pick manually later.
    ambiguous_cells = [(c, m) for c, m in cell_matches if m.match_method == "ambiguous_suffix"]
    if ambiguous_cells:
        print("\nAmbiguous matches (catalog has multiple cards with this name):")
        for card, m in ambiguous_cells:
            print(f"  {card.grid_position} '{card.name}' →")
            for cand in m.candidates[:5]:
                sub = f" — {cand['subtitle']}" if cand.get("subtitle") else ""
                print(f"    [{cand['set_code']}/{cand['collector_number']}] {cand['name']}{sub}")
            if len(m.candidates) > 5:
                print(f"    ... and {len(m.candidates) - 5} more")

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


def serve_command(*, host: str, port: int, reload: bool) -> int:
    """Run the FastAPI web UI via uvicorn."""
    import uvicorn

    print(f"Starting lorscan web UI at http://{host}:{port} ...")
    uvicorn.run(
        "lorscan.app.main:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )
    return 0


def sync_catalog_command(*, config: Config) -> int:
    """Sync the master Lorcana catalog from lorcana-api.com into the local DB."""
    db = Database.connect(str(config.db_path))
    db.migrate()

    print(f"Syncing catalog from {config.catalog_api_base} ...")
    try:
        result = asyncio.run(sync_catalog(db, base_url=config.catalog_api_base))
    except Exception as e:
        print(f"error: catalog sync failed: {e}", file=sys.stderr)
        db.close()
        return 5

    print(f"Done. {result.cards_synced} cards across {result.sets_synced} sets.")
    db.close()
    return 0
