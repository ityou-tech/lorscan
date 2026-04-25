"""Scan upload + review routes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from lorscan.services.matching import MatchResult, match_card
from lorscan.services.photos import ensure_supported_format, hash_bytes
from lorscan.services.recognition.client import (
    CliInvocationError,
    CliNotInstalledError,
    RecognitionResult,
    identify,
)
from lorscan.services.recognition.parser import ParsedCard, ParseError
from lorscan.storage.db import Database

router = APIRouter()


@dataclass(frozen=True)
class CellRow:
    """One row in the scan-results table."""

    card: ParsedCard
    match: MatchResult
    scan_result_id: int | None = None


@router.get("/", response_class=HTMLResponse)
@router.get("/scan", response_class=HTMLResponse)
async def scan_index(request: Request) -> HTMLResponse:
    """Render the scan upload page with the set-selector dropdown + recent scans."""
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        sets = sorted(
            db.get_sets(),
            key=lambda s: (s.released_on or "9999-99-99", s.set_code),
        )
        recent = db.get_recent_scans(limit=8)
    finally:
        db.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="scan/index.html",
        context={"sets": sets, "recent_scans": recent},
    )


@router.post("/scan/upload", response_class=HTMLResponse)
async def scan_upload(
    request: Request,
    photo: Annotated[UploadFile, File(...)],
    set_code: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    """Receive a photo + optional set hint, run scan synchronously, render results."""
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

    binder_set_code = (set_code or "").strip() or None

    db = Database.connect(str(cfg.db_path))
    db.migrate()
    scan_id = db.insert_scan(photo_hash=digest, photo_path=str(saved_path))

    try:
        with ensure_supported_format(saved_path) as scan_path:
            transcoded = scan_path != saved_path
            recog: RecognitionResult = identify(
                photo_path=scan_path,
                model=cfg.anthropic_model,
                max_budget_usd=cfg.per_scan_budget_usd,
            )
    except (CliInvocationError, CliNotInstalledError, ParseError, ValueError) as e:
        db.update_scan_failed(scan_id, error_message=str(e))
        db.close()
        templates = request.app.state.templates
        return templates.TemplateResponse(
            request=request,
            name="scan/error.html",
            context={"error": str(e)},
            status_code=502 if isinstance(e, CliInvocationError) else 400,
        )

    # Persist completed scan + per-cell results.
    try:
        db.update_scan_completed(
            scan_id,
            api_request_payload=json.dumps(recog.request_payload, default=str),
            api_response_payload=recog.response_text,
            cost_usd=recog.cost_usd,
        )
        cells: list[CellRow] = []
        for c in recog.parsed.cards:
            match = match_card(c, db=db, binder_set_code=binder_set_code)
            sr_id = db.insert_scan_result(
                scan_id=scan_id,
                grid_position=c.grid_position,
                claude_name=c.name,
                claude_subtitle=c.subtitle,
                claude_collector_number=c.collector_number,
                claude_set_hint=c.set_hint,
                claude_ink_color=c.ink_color,
                claude_finish=c.finish,
                confidence=c.confidence,
                matched_card_id=match.matched_card_id,
                match_method=match.match_method,
            )
            cells.append(CellRow(card=c, match=match, scan_result_id=sr_id))

        binder_set_name = None
        if binder_set_code:
            for s in db.get_sets():
                if s.set_code == binder_set_code:
                    binder_set_name = s.name
                    break
    finally:
        db.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="scan/results.html",
        context={
            "scan_id": scan_id,
            "filename": photo.filename,
            "transcoded": transcoded,
            "binder_set_code": binder_set_code,
            "binder_set_name": binder_set_name,
            "page_type": recog.parsed.page_type,
            "cells": cells,
            "issues": recog.parsed.issues,
        },
    )


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
        # Reconstruct CellRow + MatchResult shape from the stored rows.
        for r in result_rows:
            parsed = ParsedCard(
                grid_position=r["grid_position"],
                name=r["claude_name"],
                subtitle=r["claude_subtitle"],
                set_hint=r["claude_set_hint"],
                collector_number=r["claude_collector_number"],
                ink_color=r["claude_ink_color"],
                finish=r["claude_finish"] or "regular",
                confidence=r["confidence"],
                candidates=[],
            )
            match = MatchResult(
                matched_card_id=r["matched_card_id"],
                match_method=r["match_method"] or "unmatched",
                confidence=r["confidence"],
                candidates=[],
            )
            cells.append(CellRow(card=parsed, match=match, scan_result_id=int(r["id"])))

        # Look up binder set name if this scan had one.
        binder_set_code = None
        binder_set_name = None
        if scan["binder_id"] is not None:
            # binder_id support is Plan 2.5; for now, use binder_set_code from a future col.
            pass

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
            "binder_set_code": binder_set_code,
            "binder_set_name": binder_set_name,
            "applied_count": applied_count,
        },
    )


@router.get("/scan/{scan_id}/photo")
async def scan_photo(request: Request, scan_id: int) -> FileResponse:
    """Serve the original photo for a scan (so templates can <img> embed it)."""
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
    # Defensive: the photo path must live under photos_dir (no traversal).
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
                continue  # already applied
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


__all__ = ["router", "CellRow"]
