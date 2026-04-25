"""Scan upload + review routes (CLIP-only).

The web UI is now exclusively driven by local CLIP visual matching.
The earlier LLM (Claude vision via the `claude` CLI) path was removed
when CLIP proved sufficient — see commit history for context.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from lorscan.services.embeddings import CardImageIndex
from lorscan.services.photos import ensure_supported_format, hash_bytes
from lorscan.services.scan_result import MatchResult, ParsedCard
from lorscan.services.visual_scan import scan_with_clip, to_parsed_scan
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


@router.get("/", response_class=HTMLResponse)
@router.get("/scan", response_class=HTMLResponse)
async def scan_index(request: Request) -> HTMLResponse:
    """Scan upload page + recent scans list."""
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        recent = db.get_recent_scans(limit=8)
    finally:
        db.close()

    embeddings_path = cfg.data_dir / "embeddings.npz"
    clip_index_ready = embeddings_path.exists()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="scan/index.html",
        context={
            "recent_scans": recent,
            "clip_index_ready": clip_index_ready,
        },
    )


@router.post("/scan/upload")
async def scan_upload(
    request: Request,
    photo: Annotated[UploadFile, File(...)],
) -> RedirectResponse:
    """Receive a photo, run CLIP scan synchronously, redirect to /scan/<id>.

    POST/Redirect/GET pattern: rendering the result page on this POST would
    re-run the scan on browser refresh. Instead we redirect (303) to the
    detail page, which is a stable GET that's safe to refresh.

    Idempotency: if the photo (by sha256) was already scanned and completed,
    we redirect immediately without re-running CLIP. If a prior scan exists
    but is failed/pending, we wipe its scan_results and re-run cleanly.
    """
    if not photo.filename:
        raise HTTPException(400, "No file uploaded.")

    cfg = request.app.state.config
    cfg.photos_dir.mkdir(parents=True, exist_ok=True)

    payload = await photo.read()
    if not payload:
        raise HTTPException(400, "Uploaded file is empty.")
    digest = hash_bytes(payload)
    suffix = Path(photo.filename).suffix.lower() or ".jpg"
    saved_path = cfg.photos_dir / f"{digest}{suffix}"
    if not saved_path.exists():
        saved_path.write_bytes(payload)

    db = Database.connect(str(cfg.db_path))
    db.migrate()

    # Idempotency: already-completed scan of this photo? Just show it.
    existing = db.get_scan_by_photo_hash(digest)
    if existing is not None and existing["status"] == "completed":
        existing_id = int(existing["id"])
        db.close()
        return RedirectResponse(url=f"/scan/{existing_id}", status_code=303)

    scan_id = db.insert_scan(photo_hash=digest, photo_path=str(saved_path))
    # Wipe any leftover results from a prior failed/pending run on the same hash.
    db.delete_scan_results(scan_id)

    embeddings_path = cfg.data_dir / "embeddings.npz"
    if not embeddings_path.exists():
        db.update_scan_failed(
            scan_id,
            error_message="CLIP index not built. Run `lorscan index-images` first.",
        )
        db.close()
        templates = request.app.state.templates
        return templates.TemplateResponse(  # type: ignore[return-value]
            request=request,
            name="scan/error.html",
            context={
                "error": (
                    "CLIP index not built yet. From a terminal in this project, run:\n"
                    "    uv run lorscan index-images\n\n"
                    "This is a one-time setup that downloads the catalog images "
                    "and builds the local visual index."
                )
            },
            status_code=400,
        )

    try:
        with ensure_supported_format(saved_path) as scan_path:
            index = CardImageIndex.load(embeddings_path)
            tile_matches = scan_with_clip(scan_path, index)
            parsed_scan = to_parsed_scan(tile_matches)
    except (ValueError, FileNotFoundError) as e:
        db.update_scan_failed(scan_id, error_message=str(e))
        db.close()
        templates = request.app.state.templates
        return templates.TemplateResponse(  # type: ignore[return-value]
            request=request,
            name="scan/error.html",
            context={"error": str(e)},
            status_code=400,
        )

    try:
        db.update_scan_completed(
            scan_id,
            api_request_payload=None,
            api_response_payload=None,
            cost_usd=None,
        )
        for c in parsed_scan.cards:
            best_id = c.candidates[0]["card_id"] if c.candidates else None
            rotation = int(c.candidates[0].get("rotation_degrees", 0)) if c.candidates else 0
            if c.confidence == "empty":
                match = MatchResult(
                    matched_card_id=None,
                    match_method="empty_slot",
                    confidence=c.confidence,
                    candidates=[],
                )
            elif best_id and c.confidence in ("high", "medium"):
                match = MatchResult(
                    matched_card_id=best_id,
                    match_method="clip_visual",
                    confidence=c.confidence,
                    candidates=c.candidates,
                )
            else:
                match = MatchResult(
                    matched_card_id=None,
                    match_method="clip_low_confidence",
                    confidence=c.confidence,
                    candidates=c.candidates,
                )

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
                matched_card_id=match.matched_card_id,
                match_method=match.match_method,
                rotation_degrees=rotation,
            )
    finally:
        db.close()

    return RedirectResponse(url=f"/scan/{scan_id}", status_code=303)


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
            # Surface stored rotation via the candidates list so the template
            # renders the badge identically on fresh and historical scans.
            try:
                row_rotation = int(r["rotation_degrees"] or 0)
            except (IndexError, KeyError, TypeError):
                row_rotation = 0
            candidates_for_template: list[dict] = (
                [{"card_id": r["matched_card_id"], "rotation_degrees": row_rotation}]
                if row_rotation
                else []
            )
            parsed = ParsedCard(
                grid_position=r["grid_position"],
                finish=r["claude_finish"] or "regular",
                confidence=r["confidence"],
                candidates=candidates_for_template,
            )
            match = MatchResult(
                matched_card_id=r["matched_card_id"],
                match_method=r["match_method"] or "clip_low_confidence",
                confidence=r["confidence"],
            )
            matched_card = db.get_card_by_id(r["matched_card_id"]) if r["matched_card_id"] else None
            cells.append(
                CellRow(
                    card=parsed,
                    match=match,
                    scan_result_id=int(r["id"]),
                    matched_card=matched_card,
                )
            )
        applied_count = sum(1 for r in result_rows if r["applied_at"] is not None)
    finally:
        db.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="scan/detail.html",
        context={
            "scan": scan,
            "scan_id": scan_id,
            "cells": cells,
            "applied_count": applied_count,
        },
    )


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
    return FileResponse(photo_path)


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
