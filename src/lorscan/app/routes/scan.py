"""Scan upload + review routes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse

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


@router.get("/", response_class=HTMLResponse)
@router.get("/scan", response_class=HTMLResponse)
async def scan_index(request: Request) -> HTMLResponse:
    """Render the scan upload page with the set-selector dropdown."""
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        sets = sorted(
            db.get_sets(),
            key=lambda s: (s.released_on or "9999-99-99", s.set_code),
        )
    finally:
        db.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="scan/index.html",
        context={"sets": sets},
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

    # Persist the upload — content-addressed by sha256 so duplicates dedupe.
    payload = await photo.read()
    if not payload:
        raise HTTPException(400, "Uploaded file is empty.")
    digest = hash_bytes(payload)
    suffix = Path(photo.filename).suffix.lower() or ".jpg"
    saved_path = cfg.photos_dir / f"{digest}{suffix}"
    if not saved_path.exists():
        saved_path.write_bytes(payload)

    binder_set_code = (set_code or "").strip() or None

    try:
        with ensure_supported_format(saved_path) as scan_path:
            transcoded = scan_path != saved_path
            recog: RecognitionResult = identify(
                photo_path=scan_path,
                model=cfg.anthropic_model,
                max_budget_usd=cfg.per_scan_budget_usd,
            )
    except (CliInvocationError, CliNotInstalledError, ParseError, ValueError) as e:
        templates = request.app.state.templates
        return templates.TemplateResponse(
            request=request,
            name="scan/error.html",
            context={"error": str(e)},
            status_code=502 if isinstance(e, CliInvocationError) else 400,
        )

    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        cells = [
            CellRow(card=c, match=match_card(c, db=db, binder_set_code=binder_set_code))
            for c in recog.parsed.cards
        ]
        # Look up the friendly set name for the header (if a set was supplied).
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
            "filename": photo.filename,
            "transcoded": transcoded,
            "binder_set_code": binder_set_code,
            "binder_set_name": binder_set_name,
            "page_type": recog.parsed.page_type,
            "cells": cells,
            "issues": recog.parsed.issues,
            "usage": recog.usage,
            "cost_usd": recog.cost_usd,
        },
    )


# Re-export for tests.
__all__ = ["router", "CellRow"]
