"""Collection + Missing pages."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from lorscan.services.sets import release_index, release_sort_key
from lorscan.storage.db import Database

router = APIRouter()


@router.get("/collection", response_class=HTMLResponse)
async def collection_index(request: Request) -> HTMLResponse:
    """Physical-binder layout: every set is its own binder with 3×3 pages.

    Each pocket is either a thumbnail of the owned card (with quantity
    controls) or a dashed empty pocket showing the card name and a + button
    to add it directly. Sets with no owned cards default-collapsed so they
    don't dominate the page.
    """
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        binders = _build_binders(db)
        total = db.get_collection_count()
    finally:
        db.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="collection/index.html",
        context={
            "binders": binders,
            "total": total,
            "distinct_owned": sum(b["owned_count"] for b in binders),
        },
    )


def _build_binders(db: Database) -> list[dict]:
    """Construct the per-set binder rendering data.

    For each set in release order, fetch every card joined to its collection
    row (LEFT JOIN — missing cards yield NULL on the right side), chunk by
    9 into binder pages, and tag each card with `owned` + `collection_item_id`
    + `quantity` so the template can render owned and missing pockets
    without further queries.
    """
    set_rows = db.connection.execute(
        "SELECT set_code, name FROM sets"
    ).fetchall()
    sorted_sets = sorted(
        ({"set_code": r["set_code"], "name": r["name"]} for r in set_rows),
        key=lambda s: release_sort_key(s["set_code"]),
    )
    binders: list[dict] = []
    page_size = 9
    for s in sorted_sets:
        rows = db.connection.execute(
            "SELECT c.card_id, c.collector_number, c.name, c.subtitle, "
            "       c.set_code, ci.id AS collection_item_id, "
            "       COALESCE(ci.quantity, 0) AS quantity "
            "FROM cards c "
            "LEFT JOIN collection_items ci ON ci.card_id = c.card_id "
            "WHERE c.set_code = ? "
            "ORDER BY CAST(c.collector_number AS INTEGER), c.collector_number",
            (s["set_code"],),
        ).fetchall()
        cards = [
            {
                "card_id": r["card_id"],
                "collector_number": r["collector_number"],
                "name": r["name"],
                "subtitle": r["subtitle"],
                "set_code": r["set_code"],
                "owned": r["collection_item_id"] is not None,
                "collection_item_id": r["collection_item_id"],
                "quantity": r["quantity"],
            }
            for r in rows
        ]
        if not cards:
            continue
        owned_count = sum(1 for c in cards if c["owned"])
        pages = [cards[i : i + page_size] for i in range(0, len(cards), page_size)]
        chapter = release_index(s["set_code"])
        binders.append(
            {
                "set_code": s["set_code"],
                "name": s["name"],
                "chapter": chapter,
                "owned_count": owned_count,
                "total": len(cards),
                "pct": round(owned_count / len(cards) * 100, 1) if cards else 0,
                "pages": pages,
            }
        )
    return binders


@router.post("/collection/add")
async def collection_add(
    request: Request,
    card_id: str = Form(...),
) -> RedirectResponse:
    """Add a card to the collection by card_id (one-click from a missing pocket).

    Increments quantity by 1 if the user already owns one in 'regular' finish,
    otherwise creates a new collection_item. Redirects back to /collection
    with a `#`-anchor on the set so the page jumps to the right binder.
    """
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        card = db.get_card_by_id(card_id)
        if card is None:
            raise HTTPException(400, f"Unknown card_id: {card_id!r}")
        db.upsert_collection_item(card_id=card_id, quantity_delta=1)
    finally:
        db.close()
    return RedirectResponse(url=f"/collection#{card.set_code}", status_code=303)


@router.get("/missing", response_class=HTMLResponse)
async def missing_index(request: Request) -> HTMLResponse:
    """Same binder visualization as /collection but emphasizing what's missing.

    The shared `_build_binders` data lets the template invert focus —
    missing pockets are highlighted, owned cards dim — without duplicating
    any data-shaping logic.
    """
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        binders = _build_binders(db)
    finally:
        db.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="missing/index.html",
        context={"binders": binders},
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
