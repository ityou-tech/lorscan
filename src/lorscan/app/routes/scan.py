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
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

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


@dataclass(frozen=True)
class ScanRunResult:
    """Outcome of running CLIP on an uploaded photo."""

    scan_id: int
    duplicate: bool  # True if we returned an existing completed scan
    error: str | None = None  # set on user-visible failures


def _run_clip_scan_for_payload(
    payload: bytes, filename: str, *, cfg, db: Database
) -> ScanRunResult:
    """Persist the photo, run CLIP, store results. Returns the scan id.

    Idempotent: if the photo's sha256 already maps to a completed scan, we
    return its id with duplicate=True and skip the CLIP run entirely.
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
            tile_matches = scan_with_clip(scan_path, index)
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
        )

    return ScanRunResult(scan_id=scan_id, duplicate=False)


def _scan_to_json(scan_id: int, *, db: Database, duplicate: bool = False) -> dict:
    """Render a stored scan as a JSON-serializable dict for the webcam UI."""
    scan = db.get_scan(scan_id)
    if scan is None:
        return {"scan_id": scan_id, "error": "Scan not found"}

    cells_json: list[dict] = []
    for r in db.get_scan_results(scan_id):
        matched = db.get_card_by_id(r["matched_card_id"]) if r["matched_card_id"] else None
        cells_json.append(
            {
                "grid_position": r["grid_position"],
                "matched_card_id": r["matched_card_id"],
                "match_method": r["match_method"],
                "confidence": r["confidence"],
                "name": matched.name if matched else None,
                "subtitle": matched.subtitle if matched else None,
                "set_code": matched.set_code if matched else None,
                "collector_number": matched.collector_number if matched else None,
            }
        )
    return {
        "scan_id": scan_id,
        "status": scan["status"],
        "duplicate": duplicate,
        "cells": cells_json,
    }


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


@router.get("/scan/webcam", response_class=HTMLResponse)
async def scan_webcam(request: Request) -> HTMLResponse:
    """Live webcam scanner page."""
    from lorscan.services.network import detect_lan_ip

    cfg = request.app.state.config
    embeddings_path = cfg.data_dir / "embeddings.npz"

    # Build a phone-accessible URL. Prefer https on a real LAN IP so
    # `getUserMedia` works in mobile browsers; fall back to plain http
    # if the server isn't running TLS.
    lan_ip = detect_lan_ip()
    server_port = getattr(request.url, "port", None) or 8000
    is_https = request.url.scheme == "https"
    scheme = "https" if is_https else "http"
    # Send phones to the streamer page, not the webcam page.
    phone_url = f"{scheme}://{lan_ip}:{server_port}/scan/phone"

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="scan/webcam.html",
        context={
            "clip_index_ready": embeddings_path.exists(),
            "phone_url": phone_url,
            "is_https": is_https,
        },
    )


@router.get("/scan/phone", response_class=HTMLResponse)
async def scan_phone(request: Request) -> HTMLResponse:
    """Mobile-optimized page that streams the phone camera to the Mac."""
    templates = request.app.state.templates
    return templates.TemplateResponse(request=request, name="scan/phone.html", context={})


@router.post("/api/stream/frame")
async def stream_frame_upload(request: Request, frame: Annotated[UploadFile, File(...)]) -> dict:
    """Phone uploads one JPEG frame; we cache it in memory for the desktop."""
    import time

    payload = await frame.read()
    if not payload:
        raise HTTPException(400, "Empty frame")
    request.app.state.latest_frame_bytes = payload
    request.app.state.latest_frame_ts = time.time()
    return {"ok": True, "size": len(payload)}


@router.get("/api/stream/latest.jpg")
async def stream_frame_latest(request: Request) -> Response:
    """Desktop polls this to display the most recent phone frame.

    Returns 204 No Content if no frame has been received in the last 5 seconds
    so the desktop can fall back to its local camera.
    """
    import time

    bytes_ = request.app.state.latest_frame_bytes
    ts = request.app.state.latest_frame_ts
    if bytes_ is None or (time.time() - ts) > 5.0:
        return Response(status_code=204)
    return Response(
        content=bytes_,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/stream/status")
async def stream_status(request: Request) -> dict:
    """Desktop uses this to detect 'phone is currently streaming'."""
    import time

    ts = request.app.state.latest_frame_ts
    age = time.time() - ts if ts else None
    return {
        "active": age is not None and age < 5.0,
        "age_seconds": age,
    }


@router.get("/qr.png")
async def qr_png(url: str) -> Response:
    """Return a PNG QR code for the given URL with explicit black-on-white pixels.

    PNG is preferable to SVG here because the QR is displayed on a dark page
    theme — without an explicit white background, the SVG paths blend into
    the page color and become unreadable.
    """
    import io

    import qrcode

    qr = qrcode.QRCode(box_size=10, border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.post("/scan/upload")
async def scan_upload(
    request: Request,
    photo: Annotated[UploadFile, File(...)],
) -> RedirectResponse:
    """File-upload form: scan + redirect to /scan/<id> (POST/Redirect/GET)."""
    if not photo.filename:
        raise HTTPException(400, "No file uploaded.")

    cfg = request.app.state.config
    payload = await photo.read()
    if not payload:
        raise HTTPException(400, "Uploaded file is empty.")

    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        result = _run_clip_scan_for_payload(payload, photo.filename, cfg=cfg, db=db)
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


@router.post("/api/scan")
async def api_scan(
    request: Request,
    photo: Annotated[UploadFile, File(...)],
) -> dict:
    """Webcam-friendly JSON variant of scan/upload.

    Returns: {scan_id, status, duplicate, cells: [...], error?}
    """
    cfg = request.app.state.config
    if not photo.filename:
        raise HTTPException(400, "No file uploaded.")

    payload = await photo.read()
    if not payload:
        raise HTTPException(400, "Uploaded file is empty.")

    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        result = _run_clip_scan_for_payload(payload, photo.filename, cfg=cfg, db=db)
        if result.error:
            return {"scan_id": result.scan_id, "error": result.error, "cells": []}
        return _scan_to_json(result.scan_id, db=db, duplicate=result.duplicate)
    finally:
        db.close()


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
