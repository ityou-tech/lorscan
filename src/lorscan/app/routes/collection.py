"""Collection + Missing pages."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from lorscan.services.sets import release_index, release_sort_key
from lorscan.storage.db import Database

router = APIRouter()


@router.get("/collection", response_class=HTMLResponse)
async def collection_index(request: Request) -> HTMLResponse:
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        items = sorted(
            db.get_collection_with_cards(),
            # Group by release-ordered set, then collector number within set.
            key=lambda r: (release_sort_key(r["set_code"]), r["collector_number"]),
        )
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
        completion = sorted(
            db.get_set_completion(),
            key=lambda r: release_sort_key(r["set_code"]),
        )
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
                    "chapter": release_index(row["set_code"]),
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


@router.post("/collection/{item_id}/adjust")
async def collection_adjust(
    request: Request,
    item_id: int,
    action: str = Form(...),
) -> RedirectResponse:
    """Bump quantity (action=inc/dec) or remove a collection_item (action=remove).

    Quantity is clamped at 0 — a 'dec' that would go below 0 just stays at 0.
    'remove' deletes the row entirely so the card disappears from the page.
    """
    if action not in ("inc", "dec", "remove"):
        raise HTTPException(400, "action must be 'inc', 'dec', or 'remove'")
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        if action == "remove":
            db.delete_collection_item(item_id)
        else:
            delta = 1 if action == "inc" else -1
            new_qty = db.adjust_collection_item(item_id, delta=delta)
            if new_qty <= 0:
                db.delete_collection_item(item_id)
    finally:
        db.close()
    return RedirectResponse(url="/collection", status_code=303)


__all__ = ["router"]
