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
        # Fetch badge data: cheapest in-stock listing per card_id across all
        # enabled marketplaces. Enrich with shop_name for display.
        raw_badges = db.get_cheapest_in_stock_per_card()
        shop_names = _shop_name_lookup(db)
        badges = {
            card_id: {**badge, "shop_name": shop_names.get(badge["marketplace_id"], "shop")}
            for card_id, badge in raw_badges.items()
        }

        binders = _build_binders(db, badges=badges)
        total = db.get_collection_count()

        # Header stats.
        total_catalog = sum(b["total"] for b in binders)
        distinct_owned = sum(b["owned_count"] for b in binders)
        cards_needed = total_catalog - distinct_owned
        unfinished_sets = sum(1 for b in binders if b["owned_count"] < b["total"])

        # "Closest to complete" strip — top 3 sets in the 50-99% range.
        closest = [
            {**b, "missing_count": b["total"] - b["owned_count"]}
            for b in binders
            if 50.0 <= b["pct"] < 100.0
        ][:3]

        total_missing = sum(b["total"] - b["owned_count"] for b in binders)

        # Marketplace last-sweep info for the refreshed-at line.
        mp = db.get_marketplace_by_slug("bazaarofmagic")
        last_sweep = db.get_latest_finished_sweep(mp["id"]) if mp else None
    finally:
        db.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="collection/index.html",
        context={
            "binders": binders,
            "total": total,
            "distinct_owned": distinct_owned,
            "cards_needed": cards_needed,
            "unfinished_sets": unfinished_sets,
            "closest": closest,
            "total_missing": total_missing,
            "last_sweep": last_sweep,
            "has_badges": bool(badges),
        },
    )


def _shop_name_lookup(db: Database) -> dict[int, str]:
    """marketplace_id → display_name for badge labeling."""
    rows = db.connection.execute(
        "SELECT id, display_name FROM marketplaces WHERE enabled = 1"
    ).fetchall()
    return {int(r["id"]): r["display_name"] for r in rows}


def _build_binders(db: Database, *, badges: dict | None = None) -> list[dict]:
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
                "badge": badges.get(r["card_id"]) if badges else None,
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
    """Want-list view: only sets you haven't fully completed, ordered by
    how close you are to finishing them.

    Differs from /collection in three ways:
      - 100%-owned sets are filtered out (they're not "missing" anything)
      - Sort key is pct_owned DESC, so sets you're closest to completing
        rise to the top
      - The template surfaces a "closest to complete" highlight strip and
        copy-to-clipboard want-list buttons (per-binder + page-level)
    """
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        all_binders = _build_binders(db)
    finally:
        db.close()

    incomplete = [b for b in all_binders if b["owned_count"] < b["total"]]
    # Closest to complete first; for ties (especially the common 0%-owned
    # case where the user hasn't started a set yet) fall back to release
    # order so the layout reads chronologically — TFC, ROF, INK, … —
    # instead of alphabetically by missing-count tiebreak (which surfaced
    # tiny sets like "Adventure Set" above main releases).
    incomplete.sort(
        key=lambda b: (-b["pct"], release_sort_key(b["set_code"]))
    )

    # "Closest to complete" highlight: top 3 sets that are at least 50%
    # owned but not yet finished. Hidden when no set qualifies (e.g. fresh
    # collection where every set is mostly empty).
    closest = [
        {**b, "missing_count": b["total"] - b["owned_count"]}
        for b in incomplete
        if b["pct"] >= 50.0 and b["pct"] < 100.0
    ][:3]

    total_missing = sum(b["total"] - b["owned_count"] for b in incomplete)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="missing/index.html",
        context={
            "binders": incomplete,
            "closest": closest,
            "total_missing": total_missing,
            "incomplete_set_count": len(incomplete),
        },
    )


@router.post("/collection/reset")
async def collection_reset(request: Request) -> RedirectResponse:
    """Wipe every row in collection_items.

    Mirrors `/scan/reset`: catalog/sets/scan history are NOT touched, so the
    user can re-build their collection from scratch (e.g. after testing) by
    re-running scans and accepting matches. The autoincrement counter is
    also reset so new items start at id=1 again.
    """
    cfg = request.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        db.connection.execute("DELETE FROM collection_items")
        db.connection.execute(
            "DELETE FROM sqlite_sequence WHERE name = 'collection_items'"
        )
        db.connection.commit()
    finally:
        db.close()
    return RedirectResponse(url="/collection?reset=1", status_code=303)


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
