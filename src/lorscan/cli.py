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

    index_p = sub.add_parser(
        "index-images",
        help="Download all catalog images and build the local CLIP embedding index for fast offline scanning.",
    )
    index_p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="(testing) only index the first N cards",
    )

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
    elif args.command == "index-images":
        cfg = load_config(env=os.environ)
        return index_images_command(config=cfg, limit=args.limit)
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

    # Validate --set against the synced catalog so typos fail loud.
    if binder_set_code:
        db_for_check = Database.connect(str(db_path or config.db_path))
        db_for_check.migrate()
        try:
            valid_codes = {s.set_code for s in db_for_check.get_sets()}
        finally:
            db_for_check.close()
        if valid_codes and binder_set_code not in valid_codes:
            close_matches = sorted(
                code for code in valid_codes if code.lower().startswith(binder_set_code[:2].lower())
            )
            hint = f" Did you mean: {', '.join(close_matches)}?" if close_matches else ""
            print(
                f"error: unknown set code '{binder_set_code}'.{hint}\n"
                f"Available: {', '.join(sorted(valid_codes)) or '(none — run lorscan sync-catalog)'}",
                file=sys.stderr,
            )
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

    header = f"{'pos':<6}{'name':<32}{'#':<6}{'hint':<5}{'conf':<8}{'match'}"
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


def index_images_command(*, config: Config, limit: int | None = None) -> int:
    """Download every catalog card image and build the local CLIP embedding index."""
    import asyncio
    import time

    from PIL import Image

    from lorscan.services.embeddings import (
        CardImageIndex,
        _load_clip_model,
        encode_images_batch,
    )
    from lorscan.services.image_cache import fetch_all

    db = Database.connect(str(config.db_path))
    db.migrate()
    try:
        rows = db.connection.execute(
            "SELECT card_id, image_url FROM cards WHERE image_url IS NOT NULL AND image_url != ''"
        ).fetchall()
    finally:
        db.close()

    cards: list[tuple[str, str]] = [(r["card_id"], r["image_url"]) for r in rows]
    if limit is not None:
        cards = cards[:limit]

    if not cards:
        print(
            "No cards in catalog yet. Run `lorscan sync-catalog` first.",
            file=sys.stderr,
        )
        return 6

    images_dir = config.cache_dir / "images"
    embeddings_path = config.data_dir / "embeddings.npz"

    # Step 1: download missing images.
    print(f"Downloading catalog images for {len(cards)} cards → {images_dir} ...")

    def progress(done: int, total: int) -> None:
        if done == total or done % 50 == 0:
            print(f"  {done}/{total}", end="\r", flush=True)

    t0 = time.time()
    fetch_results = asyncio.run(fetch_all(cards, cache_dir=images_dir, on_progress=progress))
    print()
    failures = [r for r in fetch_results if r.path is None]
    if failures:
        print(
            f"  warning: {len(failures)} image(s) failed to download "
            f"(will be skipped from the index)",
            file=sys.stderr,
        )
        for r in failures[:5]:
            print(f"    - {r.card_id}: {r.error}", file=sys.stderr)
    print(f"  ↳ image fetch took {time.time() - t0:.1f}s")

    # Step 2: load CLIP model.
    print("Loading CLIP model (ViT-B-32) ...")
    t0 = time.time()
    model, preprocess, device = _load_clip_model()
    print(f"  ↳ model on {device}, loaded in {time.time() - t0:.1f}s")

    # Step 3: encode all cached images in batches.
    print("Encoding card images ...")
    t0 = time.time()

    indexed_card_ids: list[str] = []
    images_by_card: dict[str, Path] = {
        r.card_id: r.path for r in fetch_results if r.path is not None
    }

    batch_size = 32
    embeddings_chunks: list = []
    batch_card_ids: list[str] = []
    batch_imgs: list = []
    processed = 0

    def flush_batch() -> None:
        nonlocal batch_card_ids, batch_imgs, processed
        if not batch_imgs:
            return
        emb = encode_images_batch(model, preprocess, device, batch_imgs)
        embeddings_chunks.append(emb)
        indexed_card_ids.extend(batch_card_ids)
        processed += len(batch_imgs)
        print(f"  {processed}/{len(images_by_card)}", end="\r", flush=True)
        batch_card_ids = []
        batch_imgs = []

    for card_id, path in images_by_card.items():
        try:
            img = Image.open(path)
            img.load()
        except Exception as e:
            print(f"  warning: could not open {path}: {e}", file=sys.stderr)
            continue
        batch_card_ids.append(card_id)
        batch_imgs.append(img)
        if len(batch_imgs) >= batch_size:
            flush_batch()
    flush_batch()
    print()
    print(f"  ↳ encoding took {time.time() - t0:.1f}s")

    # Step 4: assemble + save index.
    import numpy as np

    if embeddings_chunks:
        all_embeddings = np.concatenate(embeddings_chunks, axis=0)
    else:
        all_embeddings = np.zeros((0, 512), dtype=np.float32)
    index = CardImageIndex(card_ids=indexed_card_ids, embeddings=all_embeddings)
    index.save(embeddings_path)
    print(f"Wrote index → {embeddings_path}")
    print(f"Indexed {index.size} cards.")
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
