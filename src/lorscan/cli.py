"""lorscan CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
from pathlib import Path

from lorscan.config import Config, load_config
from lorscan.services.catalog import sync_catalog
from lorscan.services.embeddings import CardImageIndex
from lorscan.services.photos import ensure_supported_format
from lorscan.services.visual_scan import scan_with_clip
from lorscan.storage.db import Database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lorscan", description="Lorcana collection manager.")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="Identify cards in a photo (local CLIP).")
    scan_p.add_argument("photo", type=Path, help="Path to a binder-page photo.")

    diag_p = sub.add_parser(
        "diag",
        help="Diagnose recognition: show whether card-boundary detection fires and "
        "compare CLIP top-5 with vs. without the warped crop.",
    )
    diag_p.add_argument("photo", type=Path, help="Path to a single-card photo.")
    diag_p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Where to save the detected crop (default: <photo>.detected.png)",
    )

    sub.add_parser("sync-catalog", help="Sync card catalog from lorcana-api.com.")

    index_p = sub.add_parser(
        "index-images",
        help="Download all catalog images and build the local CLIP embedding index.",
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
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto-reload on file changes (default: on; use --no-reload to disable)",
    )

    mp_p = sub.add_parser("marketplaces", help="Scrape & query marketplace stock.")
    mp_sub = mp_p.add_subparsers(dest="mp_command", required=True)

    refresh_p = mp_sub.add_parser("refresh", help="Run a full sweep across enabled shops.")
    refresh_p.add_argument("--shop", default=None, help="Limit to one shop slug")
    refresh_p.add_argument(
        "--set",
        dest="set_code",
        default=None,
        help="Limit to one set code (e.g. ROF)",
    )

    mp_sub.add_parser("status", help="Print last-sweep summary per shop.")

    sub.add_parser("version", help="Print version and exit.")

    args = parser.parse_args(argv)

    if args.command == "scan":
        cfg = load_config(env=os.environ)
        return scan_command(photo_path=args.photo, config=cfg)
    elif args.command == "diag":
        cfg = load_config(env=os.environ)
        return diag_command(photo_path=args.photo, out_path=args.out, config=cfg)
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
        return serve_command(
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
    elif args.command == "marketplaces":
        cfg = load_config(env=os.environ)
        if args.mp_command == "refresh":
            return marketplaces_refresh_command(
                config=cfg, shop_slug=args.shop, set_code=args.set_code,
            )
        elif args.mp_command == "status":
            return marketplaces_status_command(config=cfg)
        else:
            raise AssertionError(f"unhandled mp_command: {args.mp_command!r}")
    return 2


def scan_command(*, photo_path: Path, config: Config, db_path: Path | None = None) -> int:
    """Run the local CLIP scan against a single photo and print the results."""
    if not photo_path.exists():
        print(f"error: photo not found: {photo_path}", file=sys.stderr)
        return 2

    embeddings_path = config.data_dir / "embeddings.npz"
    if not embeddings_path.exists():
        print(
            "error: CLIP index not built. Run `lorscan index-images` first.",
            file=sys.stderr,
        )
        return 6

    try:
        with ensure_supported_format(photo_path) as scan_path:
            if scan_path != photo_path:
                print(f"Transcoded {photo_path.suffix} → JPEG.")
            index = CardImageIndex.load(embeddings_path)
            tile_matches = scan_with_clip(scan_path, index)
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    db_file = db_path if db_path is not None else config.db_path
    db = Database.connect(str(db_file))
    db.migrate()

    print(f"\nScanned: {photo_path.name}")
    print(f"Cards detected: {len(tile_matches)}\n")

    header = f"{'pos':<6}{'name':<32}{'#':<6}{'set':<5}{'conf':<8}{'match'}"
    print(header)
    print("-" * len(header))

    try:
        for tm in tile_matches:
            best = tm.best
            conf = tm.confidence_label
            if best is not None and conf in ("high", "medium"):
                card = db.get_card_by_id(best.card_id)
                if card is None:
                    name = "(unknown)"
                    col = "?"
                    set_code = "—"
                    match_str = best.card_id
                else:
                    name = (card.name or "?")[:30]
                    if card.subtitle:
                        name = f"{name[:18]} — {card.subtitle[:11]}"
                    col = card.collector_number
                    set_code = card.set_code
                    match_str = f"{best.card_id} ({best.similarity:.2f})"
            else:
                name = "?"
                col = "?"
                set_code = "—"
                match_str = "(low confidence)"
            print(f"{tm.grid_position:<6}{name:<32}{col:<6}{set_code:<5}{conf:<8}{match_str}")
    finally:
        db.close()
    return 0


def diag_command(*, photo_path: Path, out_path: Path | None, config: Config) -> int:
    """Compare CLIP top-5 with vs. without card-boundary detection on a real photo.

    Prints whether `detect_and_warp_card` fired, saves the warped crop for
    visual inspection, and shows the top-5 catalog matches for each path so
    we can see whether detection is helping, hurting, or being skipped.
    """
    from PIL import Image, ImageOps

    from lorscan.services.card_detection import detect_and_warp_card
    from lorscan.services.embeddings import _load_clip_model

    if not photo_path.exists():
        print(f"error: photo not found: {photo_path}", file=sys.stderr)
        return 2

    embeddings_path = config.data_dir / "embeddings.npz"
    if not embeddings_path.exists():
        print(
            "error: CLIP index not built. Run `lorscan index-images` first.",
            file=sys.stderr,
        )
        return 6

    with ensure_supported_format(photo_path) as scan_path:
        if scan_path != photo_path:
            print(f"Transcoded {photo_path.suffix} → JPEG.")
        original = Image.open(scan_path)
        original.load()
        original = ImageOps.exif_transpose(original)
        if original.mode != "RGB":
            original = original.convert("RGB")

    print(f"\nPhoto: {photo_path.name}  ({original.size[0]}×{original.size[1]})")

    detected = detect_and_warp_card(original)
    if detected is None:
        print("Detection: ✗ no card boundary found (would fall back to full frame)")
    else:
        print(f"Detection: ✓ found card → warped to {detected.size[0]}×{detected.size[1]}")
        save_to = out_path or photo_path.with_suffix(photo_path.suffix + ".detected.png")
        detected.save(save_to)
        print(f"  saved warped crop → {save_to}")

    _dump_detection_debug(original, photo_path)

    index = CardImageIndex.load(embeddings_path)
    print("Loading CLIP model ...")
    model, preprocess, device = _load_clip_model()
    print(f"  ↳ on {device}")

    db = Database.connect(str(config.db_path))
    db.migrate()
    try:
        _print_diag_top5(
            label="raw frame ",
            image=original,
            model=model,
            preprocess=preprocess,
            device=device,
            index=index,
            db=db,
        )
        if detected is not None:
            _print_diag_top5(
                label="detected  ",
                image=detected,
                model=model,
                preprocess=preprocess,
                device=device,
                index=index,
                db=db,
            )
    finally:
        db.close()
    return 0


def _dump_detection_debug(pil_image, photo_path: Path) -> None:
    """Save edge map + contour overlay for visual inspection.

    These let us see what the pipeline is actually working with — if Canny
    finds no edges, no min-area tweaking will help; if edges are good but
    contours don't form closed quads, the problem is in approxPolyDP.
    """
    import cv2
    from PIL import Image

    from lorscan.services.card_detection import _build_edge_map, _pil_to_bgr

    bgr = _pil_to_bgr(pil_image)
    h, w = bgr.shape[:2]
    edges = _build_edge_map(bgr)
    edges_path = photo_path.with_suffix(photo_path.suffix + ".edges.png")
    Image.fromarray(edges).save(edges_path)
    print(f"  saved edge map → {edges_path}")

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    overlay = bgr.copy()
    if contours:
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        kept = 0
        for c in contours[:30]:
            area = cv2.contourArea(c)
            pct = area / (w * h)
            if pct < 0.005:
                break
            color = (0, 255, 0) if pct >= 0.02 else (0, 165, 255)
            cv2.drawContours(overlay, [c], -1, color, 3)
            peri = cv2.arcLength(c, True)
            best_corners = None
            for ef in (0.02, 0.03, 0.04, 0.05, 0.06):
                ap = cv2.approxPolyDP(c, ef * peri, True)
                if len(ap) == 4:
                    best_corners = 4
                    break
                if best_corners is None or len(ap) < best_corners:
                    best_corners = len(ap)
            corners = best_corners or 0
            x, y, _, _ = cv2.boundingRect(c)
            cv2.putText(
                overlay,
                f"{corners}c {pct * 100:.1f}%",
                (x, max(20, y - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )
            kept += 1
        print(f"  drew {kept} contours (green ≥2% area, orange 0.5-2%)")
    overlay_rgb = cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB)
    overlay_path = photo_path.with_suffix(photo_path.suffix + ".contours.png")
    Image.fromarray(overlay_rgb).save(overlay_path)
    print(f"  saved contour overlay → {overlay_path}")


def _print_diag_top5(
    *,
    label: str,
    image,
    model,
    preprocess,
    device: str,
    index: CardImageIndex,
    db: Database,
) -> None:
    from lorscan.services.embeddings import encode_images_batch

    emb = encode_images_batch(model, preprocess, device, [image])[0]
    matches = index.find_matches(emb, top_k=5)
    print(f"\nTop-5 ({label}):")
    print(f"  {'sim':<6}{'card_id':<14}{'name'}")
    print(f"  {'-' * 5} {'-' * 13} {'-' * 30}")
    for m in matches:
        card = db.get_card_by_id(m.card_id)
        name = "(unknown)" if card is None else (card.name or "?")[:30]
        sub = "" if card is None or not card.subtitle else f" — {card.subtitle[:20]}"
        print(f"  {m.similarity:<6.3f}{m.card_id:<14}{name}{sub}")


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
    import time

    from PIL import Image

    from lorscan.services.embeddings import (
        DEFAULT_MODEL_NAME,
        EMBEDDING_DIM,
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
    overrides_dir = config.overrides_dir
    embeddings_path = config.data_dir / "embeddings.npz"

    print(f"Downloading catalog images for {len(cards)} cards → {images_dir} ...")
    if overrides_dir.is_dir():
        n_overrides = sum(
            1 for p in overrides_dir.iterdir() if p.is_file() and p.stat().st_size > 0
        )
        if n_overrides:
            print(f"  using {n_overrides} override image(s) from {overrides_dir}")

    def progress(done: int, total: int) -> None:
        if done == total or done % 50 == 0:
            print(f"  {done}/{total}", end="\r", flush=True)

    t0 = time.time()
    fetch_results = asyncio.run(
        fetch_all(
            cards,
            cache_dir=images_dir,
            overrides_dir=overrides_dir,
            on_progress=progress,
        )
    )
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
        print(
            f"    drop a replacement image at {overrides_dir}/<card_id>.jpg to include it",
            file=sys.stderr,
        )
    print(f"  ↳ image fetch took {time.time() - t0:.1f}s")

    print(f"Loading CLIP model ({DEFAULT_MODEL_NAME}) ...")
    t0 = time.time()
    model, preprocess, device = _load_clip_model()
    print(f"  ↳ model on {device}, loaded in {time.time() - t0:.1f}s")

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

    import numpy as np

    if embeddings_chunks:
        all_embeddings = np.concatenate(embeddings_chunks, axis=0)
    else:
        all_embeddings = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
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


def marketplaces_refresh_command(
    *,
    config: Config,
    shop_slug: str | None,
    set_code: str | None,
) -> int:
    """Sweep enabled shops for current stock and store the listings."""
    db = Database.connect(str(config.db_path))
    db.migrate()
    try:
        # Upsert the bundled TOML before sweeping so adding a new set is
        # just a TOML edit + re-run.
        from lorscan.services.marketplaces.seed import load_set_map

        seed_path = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "bazaarofmagic_set_map.toml"
        )
        if seed_path.exists():
            mp = db.get_marketplace_by_slug("bazaarofmagic")
            if mp is not None:
                for entry in load_set_map(seed_path):
                    try:
                        db.upsert_set_category(
                            marketplace_id=mp["id"],
                            set_code=entry.set_code,
                            category_id=entry.category_id,
                            category_path=entry.category_path,
                        )
                    except sqlite3.IntegrityError:
                        # set_code not in the catalog yet — silently skip;
                        # a future `lorscan sync-catalog` will fix it.
                        print(
                            f"  warning: skipping unknown set {entry.set_code!r} "
                            f"(run `lorscan sync-catalog` first)",
                            file=sys.stderr,
                        )
        else:
            print(
                f"warning: seed file not found at {seed_path} — "
                f"marketplace_set_categories will not be auto-populated. "
                f"If running from source, check data/bazaarofmagic_set_map.toml; "
                f"if pip-installed, this is a known packaging gap.",
                file=sys.stderr,
            )

        try:
            result = asyncio.run(
                _run_marketplace_sweep(db, shop_slug=shop_slug, set_code=set_code)
            )
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    finally:
        db.close()

    print(
        f"Sweep #{result.sweep_id}: {result.status} — "
        f"{result.listings_matched}/{result.listings_seen} listings matched, "
        f"{result.errors} errors."
    )
    return 0 if result.status in ("ok", "partial") else 1


async def _run_marketplace_sweep(
    db: Database,
    *,
    shop_slug: str | None,
    set_code: str | None,
):
    """Thin async wrapper so tests can patch this single symbol."""
    from lorscan.services.marketplaces.bazaarofmagic import BazaarAdapter
    from lorscan.services.marketplaces.orchestrator import run_sweep

    if shop_slug not in (None, "bazaarofmagic"):
        raise ValueError(f"unknown shop: {shop_slug!r}")
    return await run_sweep(
        db,
        adapter=BazaarAdapter(),
        base_url="https://www.bazaarofmagic.eu",
        only_set=set_code,
    )


def marketplaces_status_command(*, config: Config) -> int:
    """Print one line per known marketplace summarizing the last sweep."""
    db = Database.connect(str(config.db_path))
    db.migrate()
    try:
        mp = db.get_marketplace_by_slug("bazaarofmagic")
        if mp is None:
            print("No marketplaces configured.")
            return 0
        sweep = db.get_latest_finished_sweep(mp["id"])
        if sweep is None:
            print(
                f"{mp['display_name']}: no sweep yet. "
                f"Run `lorscan marketplaces refresh`."
            )
            return 0
        print(
            f"{mp['display_name']}: last sweep at {sweep['finished_at']} — "
            f"status={sweep['status']}, "
            f"matched={sweep['listings_matched']}/{sweep['listings_seen']}, "
            f"errors={sweep['errors']}."
        )
    finally:
        db.close()
    return 0
