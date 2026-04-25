"""Collection + Missing pages."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from lorscan.storage.db import Database

router = APIRouter()


@router.get("/collection", response_class=HTMLResponse)
async def collection_index(request: Request) -> HTMLResponse:
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        items = db.get_collection_with_cards()
        total = db.get_collection_count()
    finally:
        db.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="collection/index.html",
        context={"items": items, "total": total},
    )


@router.get("/missing", response_class=HTMLResponse)
async def missing_index(request: Request) -> HTMLResponse:
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        completion = db.get_set_completion()
        # For each set, fetch missing cards (limit to keep page light).
        sets_with_missing = []
        for row in completion:
            missing = db.get_missing_in_set(row["set_code"])
            sets_with_missing.append(
                {
                    "set_code": row["set_code"],
                    "name": row["name"],
                    "total": row["total_cards"],
                    "owned": row["owned"],
                    "missing": missing,
                }
            )
    finally:
        db.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="missing/index.html",
        context={"sets": sets_with_missing},
    )


__all__ = ["router"]
