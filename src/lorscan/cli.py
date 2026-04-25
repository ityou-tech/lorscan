"""lorscan CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import os
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
    serve_p.add_argument(
        "--https",
        action="store_true",
        help=(
            "Serve over HTTPS using a self-signed cert generated under "
            "~/.lorscan/. Required for phone-as-webcam over the LAN — "
            "modern browsers block camera access on plain http:// for "
            "non-localhost origins."
        ),
    )

    sub.add_parser("version", help="Print version and exit.")

    args = parser.parse_args(argv)

    if args.command == "scan":
        cfg = load_config(env=os.environ)
        return scan_command(photo_path=args.photo, config=cfg)
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
            https=args.https,
        )
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


def serve_command(*, host: str, port: int, reload: bool, https: bool = False) -> int:
    """Run the FastAPI web UI via uvicorn, optionally over self-signed HTTPS."""
    import uvicorn

    cfg = load_config(env=os.environ)

    kwargs: dict = {
        "host": host,
        "port": port,
        "reload": reload,
        "factory": True,
    }

    if https:
        from lorscan.services.cert import ensure_self_signed_cert
        from lorscan.services.network import detect_lan_ip

        cert_path, key_path = ensure_self_signed_cert(cfg.data_dir)
        kwargs["ssl_certfile"] = str(cert_path)
        kwargs["ssl_keyfile"] = str(key_path)
        scheme = "https"
        # When binding 0.0.0.0, also surface the LAN URL for the phone QR.
        lan_ip = detect_lan_ip()
        print(f"Starting lorscan web UI at {scheme}://{host}:{port} ...")
        if host in ("0.0.0.0", "::"):
            print(f"  · phone-accessible: {scheme}://{lan_ip}:{port}/scan/webcam")
        print(f"  · self-signed cert: {cert_path}")
        print(
            "  · Phones will show a security warning on first connect — accept "
            "it once and the camera will work."
        )
    else:
        print(f"Starting lorscan web UI at http://{host}:{port} ...")
        if host == "0.0.0.0":
            print(
                "  · note: --host 0.0.0.0 without --https means phones on the LAN "
                "won't be able to use their camera (browsers block camera access "
                "over plain http:// for non-localhost origins). Add --https to "
                "enable phone-as-webcam."
            )

    uvicorn.run("lorscan.app.main:create_app", **kwargs)
    return 0


def index_images_command(*, config: Config, limit: int | None = None) -> int:
    """Download every catalog card image and build the local CLIP embedding index."""
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

    print("Loading CLIP model (ViT-B-32) ...")
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
