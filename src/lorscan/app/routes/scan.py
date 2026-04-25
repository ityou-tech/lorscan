"""Scan upload + review routes (CLIP-only).

The web UI is now exclusively driven by local CLIP visual matching.
The earlier LLM (Claude vision via the `claude` CLI) path was removed
when CLIP proved sufficient — see commit history for context.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from lorscan.services.embeddings import CardImageIndex
from lorscan.services.photos import (
    ensure_supported_format,
    hash_bytes,
    jpeg_preview_path,
)
from lorscan.services.scan_result import MatchResult, ParsedCard
from lorscan.services.sets import LORCANA_RELEASE_ORDER, release_sort_key
from lorscan.services.visual_scan import (
    scan_single_card,
    scan_with_clip,
    to_parsed_scan,
)
from lorscan.storage.db import Database
from lorscan.storage.models import Card

router = APIRouter()


@dataclass(frozen=True)
class CellRow:
    """One row in the scan-results table."""

    card: ParsedCard
    match: MatchResult
    scan_result_id: int | None = None
    matched_card: Card | None = None
    # Cached lookup of {card_id: Card} for every candidate. Lets the
    # template render a friendly name in the correction dropdown without
    # a per-row DB query.
    candidate_cards: dict[str, Card] = field(default_factory=dict)


@dataclass(frozen=True)
class ScanRunResult:
    """Outcome of running CLIP on an uploaded photo."""

    scan_id: int
    duplicate: bool  # True if we returned an existing completed scan
    error: str | None = None  # set on user-visible failures


def _run_clip_scan_for_payload(
    payload: bytes,
    filename: str,
    *,
    cfg,
    db: Database,
    set_filter: str | None = None,
    mode: str = "grid",
) -> ScanRunResult:
    """Persist the photo, run CLIP, store results.

    Idempotent: if the photo's sha256 already maps to a completed scan, we
    return its id with duplicate=True and skip the CLIP run entirely.

    `set_filter`: optional set_code (e.g. "ROF") restricting catalog
    matches to that set.

    `mode`:
      - "grid" (default): 3×3 binder-page scan
      - "single": treat the whole photo as one card
    """
    cfg.photos_dir.mkdir(parents=True, exist_ok=True)

    digest = hash_bytes(payload)
    suffix = Path(filename).suffix.lower() or ".jpg"
    saved_path = cfg.photos_dir / f"{digest}{suffix}"
    if not saved_path.exists():
        saved_path.write_bytes(payload)

    existing = db.get_scan_by_photo_hash(digest)
    if existing is not None and existing["status"] == "completed":
        return ScanRunResult(scan_id=int(existing["id"]), duplicate=True)

    scan_id = db.insert_scan(photo_hash=digest, photo_path=str(saved_path))
    db.delete_scan_results(scan_id)

    embeddings_path = cfg.data_dir / "embeddings.npz"
    if not embeddings_path.exists():
        msg = "CLIP index not built. Run `lorscan index-images` first."
        db.update_scan_failed(scan_id, error_message=msg)
        return ScanRunResult(scan_id=scan_id, duplicate=False, error=msg)

    try:
        with ensure_supported_format(saved_path) as scan_path:
            index = CardImageIndex.load(embeddings_path)
            allowed_ids = (
                _card_ids_in_set(db, set_filter) if set_filter else None
            )
            if mode == "single":
                tile_matches = [
                    scan_single_card(
                        scan_path, index, allowed_card_ids=allowed_ids
                    )
                ]
            else:
                tile_matches = scan_with_clip(
                    scan_path, index, allowed_card_ids=allowed_ids
                )
            parsed_scan = to_parsed_scan(tile_matches)
    except (ValueError, FileNotFoundError) as e:
        db.update_scan_failed(scan_id, error_message=str(e))
        return ScanRunResult(scan_id=scan_id, duplicate=False, error=str(e))

    db.update_scan_completed(
        scan_id,
        api_request_payload=None,
        api_response_payload=None,
        cost_usd=None,
    )
    for c in parsed_scan.cards:
        best_id = c.candidates[0]["card_id"] if c.candidates else None
        if c.confidence == "empty":
            method = "empty_slot"
            matched_id = None
        elif best_id and c.confidence in ("high", "medium"):
            method = "clip_visual"
            matched_id = best_id
        else:
            method = "clip_low_confidence"
            matched_id = None

        db.insert_scan_result(
            scan_id=scan_id,
            grid_position=c.grid_position,
            claude_name=None,
            claude_subtitle=None,
            claude_collector_number=None,
            claude_set_hint=None,
            claude_ink_color=None,
            claude_finish=c.finish,
            confidence=c.confidence,
            matched_card_id=matched_id,
            match_method=method,
            candidates=c.candidates or None,
        )

    return ScanRunResult(scan_id=scan_id, duplicate=False)


@router.get("/", response_class=HTMLResponse)
@router.get("/scan", response_class=HTMLResponse)
async def scan_index(request: Request) -> HTMLResponse:
    """Scan upload page + recent scans list."""
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        recent = db.get_recent_scans(limit=8)
        all_sets = [
            dict(r)
            for r in db.connection.execute(
                "SELECT set_code, name, total_cards FROM sets"
            ).fetchall()
        ]
        completion = sorted(
            [dict(r) for r in db.get_set_completion()],
            key=lambda r: release_sort_key(r["set_code"]),
        )
    finally:
        db.close()

    main_sets, other_sets = _split_sets_for_dropdown(all_sets)
    progress = _build_progress_summary(completion)

    embeddings_path = cfg.data_dir / "embeddings.npz"
    clip_index_ready = embeddings_path.exists()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="scan/index.html",
        context={
            "recent_scans": recent,
            "clip_index_ready": clip_index_ready,
            "main_sets": main_sets,
            "other_sets": other_sets,
            "progress": progress,
        },
    )


def _build_progress_summary(completion: list[dict]) -> dict:
    """Aggregate per-set completion into a single dashboard summary.

    Each row gets a `pct` field (0-100) for the progress bar, plus a
    `chapter` index (None for supplementary sets). The aggregate totals
    cover only main sets so the headline number reflects the canonical
    Lorcana progression, not promo/adventure cards.
    """
    rows: list[dict] = []
    main_total = 0
    main_owned = 0
    for r in completion:
        chapter = LORCANA_RELEASE_ORDER.index(r["set_code"]) + 1 if r[
            "set_code"
        ] in LORCANA_RELEASE_ORDER else None
        total = r["total_cards"] or 0
        owned = r["owned"] or 0
        pct = round(owned / total * 100, 1) if total else 0
        rows.append({**r, "chapter": chapter, "pct": pct})
        if chapter is not None:
            main_total += total
            main_owned += owned
    return {
        "rows": rows,
        "main_total": main_total,
        "main_owned": main_owned,
        "main_pct": round(main_owned / main_total * 100, 1) if main_total else 0,
    }


def _parse_candidates(raw: str | None) -> list[dict]:
    """Decode the JSON candidates blob from a scan_result row.

    Returns [] for rows from before migration 006 — those just don't
    get an inline correction dropdown, the rest of the page works fine.
    """
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return decoded if isinstance(decoded, list) else []


def _split_sets_for_dropdown(
    sets: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Split sets into (release-ordered main sets, leftover supplementary sets).

    Main sets are prefixed with their release-order index ("1.", "2.", ...).
    Anything outside `LORCANA_RELEASE_ORDER` (e.g., the Adventure Set 99,
    promo printings) lands in `other_sets`, sorted by name. The template
    renders a divider between the two groups.
    """
    by_code = {s["set_code"]: s for s in sets}
    main: list[dict] = []
    for idx, code in enumerate(LORCANA_RELEASE_ORDER, start=1):
        s = by_code.pop(code, None)
        if s is None:
            continue
        main.append({**s, "label": f"{idx}. {s['name']} ({code} · {s['total_cards']} cards)"})
    others = sorted(by_code.values(), key=lambda s: s["name"])
    others = [
        {**s, "label": f"{s['name']} ({s['set_code']} · {s['total_cards']} cards)"}
        for s in others
    ]
    return main, others


def _card_ids_in_set(db: Database, set_code: str) -> set[str]:
    """Return every catalog card_id belonging to a set, used as an
    allow-list when restricting CLIP matches to a known set."""
    rows = db.connection.execute(
        "SELECT card_id FROM cards WHERE set_code = ?", (set_code,)
    ).fetchall()
    return {r["card_id"] for r in rows}


@router.post("/scan/upload")
async def scan_upload(
    request: Request,
    photo: Annotated[UploadFile, File(...)],
    set_code: Annotated[str, Form()] = "",
    mode: Annotated[str, Form()] = "grid",
) -> RedirectResponse:
    """File-upload form: scan + redirect to /scan/<id> (POST/Redirect/GET).

    Optional `set_code` restricts CLIP matches to a single set, useful
    when you know the binder page is from one set and want to avoid
    cross-set false positives.
    """
    if not photo.filename:
        raise HTTPException(400, "No file uploaded.")

    cfg = request.app.state.config
    payload = await photo.read()
    if not payload:
        raise HTTPException(400, "Uploaded file is empty.")

    set_filter = set_code.strip() or None
    scan_mode = "single" if mode == "single" else "grid"
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        result = _run_clip_scan_for_payload(
            payload,
            photo.filename,
            cfg=cfg,
            db=db,
            set_filter=set_filter,
            mode=scan_mode,
        )
    finally:
        db.close()

    if result.error:
        templates = request.app.state.templates
        return templates.TemplateResponse(  # type: ignore[return-value]
            request=request,
            name="scan/error.html",
            context={"error": result.error},
            status_code=400,
        )

    return RedirectResponse(url=f"/scan/{result.scan_id}", status_code=303)


@router.get("/scan/{scan_id}", response_class=HTMLResponse)
async def scan_detail(request: Request, scan_id: int) -> HTMLResponse:
    """Re-render a previously stored scan."""
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        scan = db.get_scan(scan_id)
        if scan is None:
            raise HTTPException(404, "Scan not found.")
        result_rows = db.get_scan_results(scan_id)
        cells: list[CellRow] = []
        for r in result_rows:
            parsed = ParsedCard(
                grid_position=r["grid_position"],
                finish=r["claude_finish"] or "regular",
                confidence=r["confidence"],
                candidates=_parse_candidates(r["candidates"]),
            )
            match = MatchResult(
                matched_card_id=r["matched_card_id"],
                match_method=r["match_method"] or "clip_low_confidence",
                confidence=r["confidence"],
            )
            matched_card = db.get_card_by_id(r["matched_card_id"]) if r["matched_card_id"] else None
            candidate_cards: dict[str, Card] = {}
            for cand in parsed.candidates:
                cid = cand.get("card_id")
                if cid and cid not in candidate_cards:
                    card = db.get_card_by_id(cid)
                    if card is not None:
                        candidate_cards[cid] = card
            cells.append(
                CellRow(
                    card=parsed,
                    match=match,
                    scan_result_id=int(r["id"]),
                    matched_card=matched_card,
                    candidate_cards=candidate_cards,
                )
            )
        applied_count = sum(1 for r in result_rows if r["applied_at"] is not None)
    finally:
        db.close()

    binder_rows = _arrange_cells_as_binder(cells)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="scan/detail.html",
        context={
            "scan": scan,
            "scan_id": scan_id,
            "cells": cells,
            "binder_rows": binder_rows,
            "applied_count": applied_count,
        },
    )


def _arrange_cells_as_binder(cells: list[CellRow]) -> list[list[CellRow | None]]:
    """Group cells into a row-major grid mirroring the actual binder layout.

    Reads the row/col from each grid_position ("r1c2" → row 1, col 2) and
    pads missing positions with None so the template can render every slot
    even if the scan reported fewer cells than the grid implies. Returns a
    single-row 1-cell list for single-card scans (grid_position="single").
    """
    by_pos: dict[tuple[int, int], CellRow] = {}
    max_row = 0
    max_col = 0
    has_single = False
    for cell in cells:
        pos = cell.card.grid_position
        if pos == "single":
            has_single = True
            continue
        if not (pos.startswith("r") and "c" in pos):
            continue
        try:
            r_str, c_str = pos[1:].split("c", 1)
            r = int(r_str)
            c = int(c_str)
        except (ValueError, IndexError):
            continue
        by_pos[(r, c)] = cell
        max_row = max(max_row, r)
        max_col = max(max_col, c)

    if has_single:
        single_cell = next((c for c in cells if c.card.grid_position == "single"), None)
        return [[single_cell]] if single_cell else []
    if not by_pos:
        return []
    return [
        [by_pos.get((r, c)) for c in range(1, max_col + 1)]
        for r in range(1, max_row + 1)
    ]


@router.get("/card/{card_id}/image")
async def card_image(request: Request, card_id: str) -> FileResponse:
    """Serve a catalog card image from the local cache.

    Used by the binder-grid view to show the matched card next to each
    detected cell. Returns 404 if the image hasn't been downloaded yet
    (which only happens for cards skipped during `index-images`).
    """
    cfg = request.app.state.config
    images_dir = cfg.cache_dir / "images"
    # Card IDs are uppercase alphanumeric + hyphens (e.g. ROF-058). Reject
    # anything else as a defense-in-depth path-traversal guard.
    if not card_id.replace("-", "").isalnum():
        raise HTTPException(400, "Invalid card_id")
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        path = images_dir / f"{card_id}{suffix}"
        if path.exists():
            return FileResponse(path)
    raise HTTPException(404, "Card image not cached.")


@router.get("/scan/{scan_id}/photo")
async def scan_photo(request: Request, scan_id: int) -> FileResponse:
    """Serve the original photo for a scan."""
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        scan = db.get_scan(scan_id)
    finally:
        db.close()
    if scan is None:
        raise HTTPException(404, "Scan not found.")
    photo_path = Path(scan["photo_path"])
    try:
        photo_path.resolve().relative_to(cfg.photos_dir.resolve())
    except ValueError:
        raise HTTPException(404, "Photo unavailable.") from None
    if not photo_path.exists():
        raise HTTPException(404, "Photo file missing on disk.")
    # Browsers can't render HEIC; serve the persisted JPEG preview that
    # ensure_supported_format wrote next to the original at scan time.
    preview = jpeg_preview_path(photo_path)
    if preview != photo_path and preview.exists():
        return FileResponse(preview)
    return FileResponse(photo_path)


@router.post("/scan/{scan_id}/cell/{scan_result_id}/correct")
async def scan_cell_correct(
    request: Request,
    scan_id: int,
    scan_result_id: int,
    matched_card_id: Annotated[str, Form()] = "",
) -> RedirectResponse:
    """Replace the match on a single scan cell.

    `matched_card_id`: the new card_id (must exist in the catalog), or
    empty string to clear the match (leaves the cell unmatched).
    """
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        # Verify the scan_result belongs to this scan (defense against URL-tampering).
        row = db.connection.execute(
            "SELECT scan_id FROM scan_results WHERE id = ?", (scan_result_id,)
        ).fetchone()
        if row is None or int(row["scan_id"]) != scan_id:
            raise HTTPException(404, "Scan cell not found.")
        new_id: str | None = matched_card_id.strip() or None
        if new_id is not None and db.get_card_by_id(new_id) is None:
            raise HTTPException(400, f"Unknown card_id: {new_id!r}")
        db.update_scan_result_match(scan_result_id, matched_card_id=new_id)
    finally:
        db.close()
    return RedirectResponse(url=f"/scan/{scan_id}", status_code=303)


@router.post("/scan/reset")
async def scan_reset(request: Request) -> RedirectResponse:
    """Wipe all scans, scan_results, and saved photo files.

    Local-only convenience for iterating on the scanner — the catalog,
    embeddings index, and accepted collection items are NOT touched, so
    you don't have to re-sync or re-curate anything after a reset.
    """
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        db.connection.execute("DELETE FROM scan_results")
        db.connection.execute("DELETE FROM scans")
        db.connection.execute(
            "DELETE FROM sqlite_sequence WHERE name IN ('scans','scan_results')"
        )
        db.connection.commit()
    finally:
        db.close()

    # Delete saved upload bytes + transcoded HEIC previews + diag dumps.
    photos_dir = cfg.photos_dir
    if photos_dir.exists():
        for f in photos_dir.iterdir():
            if f.is_file():
                f.unlink(missing_ok=True)

    return RedirectResponse(url="/scan?reset=1", status_code=303)


@router.post("/scan/{scan_id}/apply", response_class=HTMLResponse)
async def scan_apply(request: Request, scan_id: int) -> RedirectResponse:
    """Add every matched card from this scan to the user's collection."""
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        scan = db.get_scan(scan_id)
        if scan is None:
            raise HTTPException(404, "Scan not found.")
        result_rows = db.get_scan_results(scan_id)
        applied_ids: list[int] = []
        for r in result_rows:
            if r["matched_card_id"] is None:
                continue
            if r["applied_at"] is not None:
                continue
            db.upsert_collection_item(
                card_id=r["matched_card_id"],
                finish=r["claude_finish"] or "regular",
                quantity_delta=1,
            )
            applied_ids.append(int(r["id"]))
        db.mark_scan_results_applied(scan_id, applied_ids)
    finally:
        db.close()

    return RedirectResponse(url=f"/scan/{scan_id}", status_code=303)


__all__ = ["CellRow", "router"]
