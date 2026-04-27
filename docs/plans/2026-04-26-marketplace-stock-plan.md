# Marketplace Stock Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Surface "available to buy" data on `/collection`'s empty pockets, sourced from Bazaar of Magic via a manual `lorscan marketplaces refresh` command. Architect the scraper layer so eBay (and others) plug in later. Delete `/missing` and absorb its prioritization features into `/collection`.

**Architecture:** A new `services/marketplaces/` package introduces a `ShopAdapter` Protocol with one concrete adapter (`bazaarofmagic.py`). A `Listing` dataclass + strict `(set_code, collector_number) → card_id` matcher decouple scraping from catalog-mapping so future shops with messier listings can swap in fuzzy matching behind the same interface. Scraped data is persisted via 4 new SQLite tables and surfaced as small price badges on `/collection`'s empty pockets.

**Tech stack:**
- Python 3.12, FastAPI, Jinja2, SQLite (via the existing `Database` wrapper — *all SQL lives there*)
- `httpx` for outbound HTTP (already a dep)
- `beautifulsoup4` for HTML parsing (new dep)
- `respx` for HTTP mocking in tests (already a dev dep)
- pytest-asyncio in `auto` mode (no `@pytest.mark.asyncio` decorators needed)

**Conventions (read before starting):**
- `db.py` is the only place SQL lives. Services receive a `Database` instance and call typed methods.
- Tests use `:memory:` SQLite via the `db` fixture in `tests/conftest.py`.
- Commits are small and per-task. Each commit message follows the `type(scope): subject` pattern in recent history (`feat(marketplaces): ...`, `test(marketplaces): ...`, `docs(readme): ...`).
- Run `uv run ruff check src tests` and `uv run pytest` before each commit.

**Reference design:** [`docs/plans/2026-04-26-marketplace-stock-design.md`](./2026-04-26-marketplace-stock-design.md). Read it once before starting.

---

## Pre-work: dependency add

### Task 0: Add `beautifulsoup4` dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add dep**

Edit `pyproject.toml`'s `dependencies` block to include `"beautifulsoup4>=4.12"` after `"httpx>=0.28"`.

**Step 2: Sync**

Run: `uv sync`
Expected: lockfile updates, no errors.

**Step 3: Verify import**

Run: `uv run python -c "from bs4 import BeautifulSoup; print('ok')"`
Expected: `ok`

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): add beautifulsoup4 for marketplace scrapers"
```

---

## Phase 1 — Schema & seed

### Task 1: Migration 007 — marketplace tables

**Files:**
- Create: `src/lorscan/storage/migrations/007_marketplaces.sql`
- Create: `tests/unit/test_db_migrations_007.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_db_migrations_007.py
"""Migration 007: marketplace tables exist after migrate()."""

from __future__ import annotations

from lorscan.storage.db import Database


def test_marketplace_tables_created(db: Database):
    cursor = db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('marketplaces','marketplace_set_categories',"
        "'marketplace_listings','marketplace_sweeps')"
    )
    names = {row[0] for row in cursor.fetchall()}
    assert names == {
        "marketplaces",
        "marketplace_set_categories",
        "marketplace_listings",
        "marketplace_sweeps",
    }


def test_bazaar_marketplace_seeded(db: Database):
    row = db.connection.execute(
        "SELECT slug, display_name, base_url, enabled "
        "FROM marketplaces WHERE slug = 'bazaarofmagic'"
    ).fetchone()
    assert row is not None
    assert row["display_name"] == "Bazaar of Magic"
    assert row["base_url"] == "https://www.bazaarofmagic.eu"
    assert row["enabled"] == 1


def test_listing_card_fk_is_nullable(db: Database):
    db.connection.execute(
        "INSERT INTO marketplace_listings "
        "(marketplace_id, external_id, card_id, finish, price_cents, "
        " currency, in_stock, url, title, fetched_at) "
        "VALUES (1, 'x123', NULL, 'regular', 400, 'EUR', 1, "
        " 'https://example.com/x', 'Whatever', '2026-04-26T00:00:00+00:00')"
    )
    # Should not raise — card_id is nullable for unmatched listings.


def test_listing_unique_per_marketplace_external_id(db: Database):
    import sqlite3
    db.connection.execute(
        "INSERT INTO marketplace_listings "
        "(marketplace_id, external_id, card_id, finish, price_cents, "
        " currency, in_stock, url, title, fetched_at) "
        "VALUES (1, 'dup', NULL, 'regular', 100, 'EUR', 1, 'u', 't', 'now')"
    )
    try:
        db.connection.execute(
            "INSERT INTO marketplace_listings "
            "(marketplace_id, external_id, card_id, finish, price_cents, "
            " currency, in_stock, url, title, fetched_at) "
            "VALUES (1, 'dup', NULL, 'foil', 200, 'EUR', 0, 'u2', 't2', 'now')"
        )
    except sqlite3.IntegrityError:
        return
    raise AssertionError("Expected UNIQUE violation on (marketplace_id, external_id)")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_db_migrations_007.py -v`
Expected: FAIL — tables don't exist.

**Step 3: Write the migration**

Create `src/lorscan/storage/migrations/007_marketplaces.sql`:

```sql
CREATE TABLE marketplaces (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  slug         TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  base_url     TEXT NOT NULL,
  enabled      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE marketplace_set_categories (
  marketplace_id INTEGER NOT NULL REFERENCES marketplaces(id),
  set_code       TEXT NOT NULL REFERENCES sets(set_code),
  category_id    TEXT NOT NULL,
  category_path  TEXT NOT NULL,
  PRIMARY KEY (marketplace_id, set_code)
);

CREATE TABLE marketplace_listings (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  marketplace_id  INTEGER NOT NULL REFERENCES marketplaces(id),
  external_id     TEXT NOT NULL,
  card_id         TEXT REFERENCES cards(card_id),
  finish          TEXT,
  price_cents     INTEGER NOT NULL,
  currency        TEXT NOT NULL DEFAULT 'EUR',
  in_stock        INTEGER NOT NULL DEFAULT 0,
  url             TEXT NOT NULL,
  title           TEXT NOT NULL,
  fetched_at      TEXT NOT NULL,
  UNIQUE (marketplace_id, external_id)
);
CREATE INDEX idx_listings_card_stock
  ON marketplace_listings (card_id, in_stock, price_cents);

CREATE TABLE marketplace_sweeps (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  marketplace_id   INTEGER NOT NULL REFERENCES marketplaces(id),
  started_at       TEXT NOT NULL,
  finished_at      TEXT,
  listings_seen    INTEGER NOT NULL DEFAULT 0,
  listings_matched INTEGER NOT NULL DEFAULT 0,
  errors           INTEGER NOT NULL DEFAULT 0,
  status           TEXT NOT NULL
);

INSERT INTO marketplaces (slug, display_name, base_url, enabled)
VALUES ('bazaarofmagic', 'Bazaar of Magic', 'https://www.bazaarofmagic.eu', 1);
```

**Step 4: Re-run test**

Run: `uv run pytest tests/unit/test_db_migrations_007.py -v`
Expected: all 4 tests PASS.

**Step 5: Commit**

```bash
git add src/lorscan/storage/migrations/007_marketplaces.sql tests/unit/test_db_migrations_007.py
git commit -m "feat(marketplaces): migration 007 + Bazaar seed row"
```

---

### Task 2: Bazaar set-category map (TOML seed file)

**Files:**
- Create: `data/bazaarofmagic_set_map.toml`

**Step 1: Capture the 11 known mappings**

The two we already know from research:
- ROF → `1000676` → `/nl-NL/c/rise-of-the-floodborn/1000676`
- ITI → `1000697` → `/nl-NL/c/into-the-inklands/1000697`

For the other 9 sets (TFC, URS, SSK, ARI, ROJ, FAB, WHI, WIN, AZS), discover the IDs by visiting <https://www.bazaarofmagic.eu/nl-NL/c/disney-lorcana-tcg/1000565> in a browser and reading the per-set sub-category links. (If a set's category isn't yet listed on Bazaar, omit the row — the sweep will skip it.)

**Step 2: Write the TOML**

```toml
# data/bazaarofmagic_set_map.toml
# Hand-curated map of Lorcana set codes to Bazaar of Magic category IDs.
# Add a new row when a new Lorcana set is added to Bazaar's catalog.
# Read on every `lorscan marketplaces refresh` and upserted into the DB.

[[set]]
code = "ROF"
category_id = "1000676"
category_path = "/nl-NL/c/rise-of-the-floodborn/1000676"

[[set]]
code = "ITI"
category_id = "1000697"
category_path = "/nl-NL/c/into-the-inklands/1000697"

# ... add the remaining 9 here after browser inspection
```

**Step 3: Commit**

```bash
git add data/bazaarofmagic_set_map.toml
git commit -m "feat(marketplaces): seed file for Bazaar per-set category IDs"
```

---

## Phase 2 — Domain types

### Task 3: `Listing` dataclass + `ShopAdapter` Protocol

**Files:**
- Create: `src/lorscan/services/marketplaces/__init__.py` (empty)
- Create: `src/lorscan/services/marketplaces/base.py`
- Create: `tests/unit/services/__init__.py` (empty)
- Create: `tests/unit/services/marketplaces/__init__.py` (empty)
- Create: `tests/unit/services/marketplaces/test_base.py`

**Step 1: Write the failing test**

```python
# tests/unit/services/marketplaces/test_base.py
"""Listing dataclass + ShopAdapter Protocol surface."""

from __future__ import annotations

from lorscan.services.marketplaces.base import Listing, ShopAdapter


def test_listing_is_frozen():
    listing = Listing(
        external_id="9154978",
        title="Pinocchio, Strings Attached (#224) (foil)",
        price_cents=1500,
        currency="EUR",
        in_stock=True,
        url="https://www.bazaarofmagic.eu/nl-NL/p/pinocchio-strings-attached-224-foil/9154978",
        finish="foil",
        collector_number="224",
    )
    try:
        listing.price_cents = 999  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Expected Listing to be frozen")


def test_shop_adapter_is_a_protocol():
    # Any duck-typed object with the right attributes should satisfy isinstance.
    class FakeAdapter:
        slug = "fake"
        display_name = "Fake Shop"

        async def crawl_set(self, client, set_code, category_path):
            yield Listing(
                external_id="x",
                title="x",
                price_cents=0,
                currency="EUR",
                in_stock=False,
                url="x",
                finish=None,
                collector_number=None,
            )

    assert isinstance(FakeAdapter(), ShopAdapter)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/services/marketplaces/test_base.py -v`
Expected: FAIL — module doesn't exist.

**Step 3: Implement**

```python
# src/lorscan/services/marketplaces/base.py
"""Marketplace scraping primitives: shared dataclass + adapter Protocol."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx


@dataclass(frozen=True)
class Listing:
    """One product as scraped from a marketplace.

    Identity is `(marketplace_id, external_id)`. `card_id` is resolved later
    by the matcher; here we only carry what the shop told us. `finish` and
    `collector_number` may be None when the title doesn't expose them — the
    matcher decides what to do with those listings.
    """

    external_id: str
    title: str
    price_cents: int
    currency: str
    in_stock: bool
    url: str
    finish: str | None              # 'regular' | 'foil' | 'cold_foil'
    collector_number: str | None    # parsed from title; None if absent


@runtime_checkable
class ShopAdapter(Protocol):
    """One marketplace's scraping surface. One adapter per shop."""

    slug: str
    display_name: str

    def crawl_set(
        self,
        client: httpx.AsyncClient,
        set_code: str,
        category_path: str,
    ) -> AsyncIterator[Listing]: ...
```

**Step 4: Re-run test**

Run: `uv run pytest tests/unit/services/marketplaces/test_base.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/lorscan/services/marketplaces/__init__.py \
        src/lorscan/services/marketplaces/base.py \
        tests/unit/services/__init__.py \
        tests/unit/services/marketplaces/__init__.py \
        tests/unit/services/marketplaces/test_base.py
git commit -m "feat(marketplaces): Listing dataclass + ShopAdapter Protocol"
```

---

## Phase 3 — Bazaar parsers

### Task 4: Capture golden HTML fixtures

**Files:**
- Create: `tests/fixtures/marketplaces/__init__.py` (empty)
- Create: `tests/fixtures/marketplaces/bazaarofmagic/listing.html`
- Create: `tests/fixtures/marketplaces/bazaarofmagic/detail.html`
- Create: `tests/fixtures/marketplaces/bazaarofmagic/empty_listing.html`

**Step 1: Fetch real HTML**

```bash
mkdir -p tests/fixtures/marketplaces/bazaarofmagic

curl -sL --user-agent "lorscan-fixture-capture/1.0" \
  "https://www.bazaarofmagic.eu/nl-NL/c/rise-of-the-floodborn/1000676?page=1&items=24" \
  > tests/fixtures/marketplaces/bazaarofmagic/listing.html

curl -sL --user-agent "lorscan-fixture-capture/1.0" \
  "https://www.bazaarofmagic.eu/nl-NL/p/pinocchio-strings-attached-224-foil/9154978" \
  > tests/fixtures/marketplaces/bazaarofmagic/detail.html

# Empty page (past the last) for end-of-pagination test.
curl -sL --user-agent "lorscan-fixture-capture/1.0" \
  "https://www.bazaarofmagic.eu/nl-NL/c/rise-of-the-floodborn/1000676?page=999&items=24" \
  > tests/fixtures/marketplaces/bazaarofmagic/empty_listing.html
```

**Step 2: Verify fixtures look reasonable**

Run: `wc -l tests/fixtures/marketplaces/bazaarofmagic/*.html`
Expected: each file is several hundred lines of HTML.

```bash
grep -c 'class="product' tests/fixtures/marketplaces/bazaarofmagic/listing.html
```
Expected: ~24 (one per product card on the page).

**Step 3: Commit**

```bash
git add tests/fixtures/marketplaces/
git commit -m "test(marketplaces): capture Bazaar listing/detail/empty fixtures"
```

---

### Task 5: Bazaar listing-page parser

**Files:**
- Create: `src/lorscan/services/marketplaces/bazaarofmagic.py`
- Create: `tests/unit/services/marketplaces/test_bazaarofmagic_listing.py`

**Step 1: Write the failing test**

```python
# tests/unit/services/marketplaces/test_bazaarofmagic_listing.py
"""Bazaar of Magic listing-page parser."""

from __future__ import annotations

from pathlib import Path

from lorscan.services.marketplaces.bazaarofmagic import (
    ListingCard,
    parse_listing_page,
)

FIXTURE_DIR = Path(__file__).parents[3] / "fixtures" / "marketplaces" / "bazaarofmagic"


def test_parse_listing_returns_24_products():
    html = (FIXTURE_DIR / "listing.html").read_text()
    cards = parse_listing_page(html, base_url="https://www.bazaarofmagic.eu")
    assert 1 <= len(cards) <= 24


def test_listing_card_fields_are_populated():
    html = (FIXTURE_DIR / "listing.html").read_text()
    cards = parse_listing_page(html, base_url="https://www.bazaarofmagic.eu")
    sample = cards[0]
    assert isinstance(sample, ListingCard)
    assert sample.external_id  # non-empty product id
    assert sample.url.startswith("https://www.bazaarofmagic.eu/nl-NL/p/")
    assert sample.title  # non-empty
    assert sample.price_cents > 0


def test_empty_page_returns_empty_list():
    html = (FIXTURE_DIR / "empty_listing.html").read_text()
    assert parse_listing_page(html, base_url="https://www.bazaarofmagic.eu") == []
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/services/marketplaces/test_bazaarofmagic_listing.py -v`
Expected: FAIL — module / functions missing.

**Step 3: Implement parser**

```python
# src/lorscan/services/marketplaces/bazaarofmagic.py
"""Bazaar of Magic adapter — listing-page + detail-page parsers + crawler."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from lorscan.services.marketplaces.base import Listing


@dataclass(frozen=True)
class ListingCard:
    """A product as it appears on a category-listing page (sparse)."""

    external_id: str
    title: str
    price_cents: int
    url: str


_PRICE_RE = re.compile(r"€\s*(\d+)[,.](\d{2})")
_PRODUCT_URL_RE = re.compile(r"/nl-NL/p/[^/]+/(\d+)")


def parse_listing_page(html: str, *, base_url: str) -> list[ListingCard]:
    """Parse one /c/<set>?page=N HTML body into ListingCard rows.

    Returns [] if the page has no products (end of pagination).
    """
    soup = BeautifulSoup(html, "html.parser")
    cards: list[ListingCard] = []
    # Bazaar (Shopware 6) wraps each product in an anchor pointing at /p/...
    for anchor in soup.select("a[href*='/nl-NL/p/']"):
        href = anchor.get("href", "")
        match = _PRODUCT_URL_RE.search(href)
        if not match:
            continue
        external_id = match.group(1)
        title = (anchor.get_text(strip=True) or "").strip()
        if not title:
            continue
        price_cents = _extract_price_near(anchor)
        if price_cents is None:
            continue
        url = urljoin(base_url, href)
        cards.append(
            ListingCard(
                external_id=external_id,
                title=title,
                price_cents=price_cents,
                url=url,
            )
        )
    # Dedupe by external_id (Shopware sometimes emits the link twice per card).
    seen: set[str] = set()
    deduped: list[ListingCard] = []
    for c in cards:
        if c.external_id in seen:
            continue
        seen.add(c.external_id)
        deduped.append(c)
    return deduped


def _extract_price_near(anchor) -> int | None:
    """Find the price text near a product anchor.

    Bazaar puts the price in a sibling element of the product card; we walk
    up to the enclosing card container and search its text.
    """
    container = anchor
    for _ in range(5):
        container = container.parent
        if container is None:
            return None
        text = container.get_text(" ", strip=True)
        m = _PRICE_RE.search(text)
        if m:
            return int(m.group(1)) * 100 + int(m.group(2))
    return None
```

**Step 4: Re-run tests**

Run: `uv run pytest tests/unit/services/marketplaces/test_bazaarofmagic_listing.py -v`
Expected: all 3 PASS. If `_extract_price_near` doesn't find prices in the real fixture, inspect the HTML manually and tighten the selector.

**Step 5: Commit**

```bash
git add src/lorscan/services/marketplaces/bazaarofmagic.py \
        tests/unit/services/marketplaces/test_bazaarofmagic_listing.py
git commit -m "feat(marketplaces): Bazaar listing-page parser"
```

---

### Task 6: Bazaar detail-page parser

**Files:**
- Modify: `src/lorscan/services/marketplaces/bazaarofmagic.py`
- Create: `tests/unit/services/marketplaces/test_bazaarofmagic_detail.py`

**Step 1: Write the failing test**

```python
# tests/unit/services/marketplaces/test_bazaarofmagic_detail.py
"""Bazaar of Magic detail-page parser."""

from __future__ import annotations

from pathlib import Path

from lorscan.services.marketplaces.bazaarofmagic import (
    DetailExtras,
    parse_detail_page,
)

FIXTURE = (
    Path(__file__).parents[3]
    / "fixtures" / "marketplaces" / "bazaarofmagic" / "detail.html"
)


def test_detail_extracts_collector_number_and_finish():
    extras = parse_detail_page(FIXTURE.read_text())
    assert isinstance(extras, DetailExtras)
    assert extras.collector_number == "224"
    assert extras.finish == "foil"


def test_detail_extracts_in_stock_status():
    extras = parse_detail_page(FIXTURE.read_text())
    # Pinocchio fixture should be in stock when captured ("Op voorraad").
    # If the captured page later goes out of stock, regenerate the fixture.
    assert extras.in_stock is True


def test_detail_handles_title_without_collector_number():
    html = """<html><body>
        <h1 class="product-name">The Reforged Crown (oversized)</h1>
        <strong>Op voorraad</strong>
    </body></html>"""
    extras = parse_detail_page(html)
    assert extras.collector_number is None
    assert extras.finish == "regular"
    assert extras.in_stock is True


def test_detail_recognises_uitverkocht_as_out_of_stock():
    html = """<html><body>
        <h1>Some Card (foil)</h1>
        <span>Uitverkocht</span>
    </body></html>"""
    extras = parse_detail_page(html)
    assert extras.in_stock is False
    assert extras.finish == "foil"


def test_detail_recognises_cold_foil():
    html = "<html><body><h1>Card Name (cold foil)</h1>Op voorraad</body></html>"
    extras = parse_detail_page(html)
    assert extras.finish == "cold_foil"
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/services/marketplaces/test_bazaarofmagic_detail.py -v`
Expected: FAIL — `DetailExtras` and `parse_detail_page` don't exist.

**Step 3: Append parser to `bazaarofmagic.py`**

```python
# src/lorscan/services/marketplaces/bazaarofmagic.py  (append)

@dataclass(frozen=True)
class DetailExtras:
    """Per-product fields only available on the detail page."""

    collector_number: str | None
    finish: str | None
    in_stock: bool


_COLLECTOR_RE = re.compile(r"#(\d+)")
_FINISH_RES = (
    ("cold_foil", re.compile(r"\(cold foil\)", re.IGNORECASE)),
    ("foil", re.compile(r"\(foil\)", re.IGNORECASE)),
)


def parse_detail_page(html: str) -> DetailExtras:
    """Parse a /p/<slug>/<id> HTML body for collector_number/finish/in_stock."""
    soup = BeautifulSoup(html, "html.parser")
    title = _find_product_title(soup)

    collector = None
    if title:
        m = _COLLECTOR_RE.search(title)
        if m:
            collector = m.group(1)

    finish: str | None = "regular"
    if title:
        for label, pattern in _FINISH_RES:
            if pattern.search(title):
                finish = label
                break

    text_blob = soup.get_text(" ", strip=True).lower()
    if "uitverkocht" in text_blob:
        in_stock = False
    elif "op voorraad" in text_blob:
        in_stock = True
    else:
        # Conservative default: treat unknown as out-of-stock so we never
        # advertise something we can't confirm.
        in_stock = False

    return DetailExtras(collector_number=collector, finish=finish, in_stock=in_stock)


def _find_product_title(soup: BeautifulSoup) -> str | None:
    for selector in (
        "h1.product-name",
        "h1[itemprop='name']",
        "h1",
    ):
        node = soup.select_one(selector)
        if node:
            text = node.get_text(strip=True)
            if text:
                return text
    return None
```

**Step 4: Re-run tests**

Run: `uv run pytest tests/unit/services/marketplaces/test_bazaarofmagic_detail.py -v`
Expected: all PASS. If `parse_detail_page` finds no title in the real fixture, inspect the captured HTML and add a more specific selector to `_find_product_title`.

**Step 5: Commit**

```bash
git add src/lorscan/services/marketplaces/bazaarofmagic.py \
        tests/unit/services/marketplaces/test_bazaarofmagic_detail.py
git commit -m "feat(marketplaces): Bazaar detail-page parser"
```

---

## Phase 4 — Bazaar adapter

### Task 7: `BazaarAdapter.crawl_set` async generator

**Files:**
- Modify: `src/lorscan/services/marketplaces/bazaarofmagic.py`
- Create: `tests/unit/services/marketplaces/test_bazaarofmagic_crawl.py`

**Step 1: Write the failing test (HTTP mocked with respx)**

```python
# tests/unit/services/marketplaces/test_bazaarofmagic_crawl.py
"""BazaarAdapter.crawl_set walks listing pages then fetches detail pages."""

from __future__ import annotations

from pathlib import Path

import httpx
import respx

from lorscan.services.marketplaces.bazaarofmagic import BazaarAdapter

FIXTURE_DIR = Path(__file__).parents[3] / "fixtures" / "marketplaces" / "bazaarofmagic"


async def test_crawl_set_yields_listings():
    listing_html = (FIXTURE_DIR / "listing.html").read_text()
    detail_html = (FIXTURE_DIR / "detail.html").read_text()
    empty_html = (FIXTURE_DIR / "empty_listing.html").read_text()

    base = "https://www.bazaarofmagic.eu"
    adapter = BazaarAdapter()

    with respx.mock(assert_all_called=False) as mock:
        mock.get(
            f"{base}/nl-NL/c/rise-of-the-floodborn/1000676",
            params={"page": "1", "items": "24"},
        ).mock(return_value=httpx.Response(200, text=listing_html))
        mock.get(
            f"{base}/nl-NL/c/rise-of-the-floodborn/1000676",
            params={"page": "2", "items": "24"},
        ).mock(return_value=httpx.Response(200, text=empty_html))
        # Any /nl-NL/p/... GET returns the same detail fixture.
        mock.get(url__regex=rf"{base}/nl-NL/p/.+").mock(
            return_value=httpx.Response(200, text=detail_html)
        )

        async with httpx.AsyncClient(base_url=base, timeout=10.0) as client:
            listings = []
            async for listing in adapter.crawl_set(
                client,
                set_code="ROF",
                category_path="/nl-NL/c/rise-of-the-floodborn/1000676",
            ):
                listings.append(listing)

    assert len(listings) > 0
    # Every yielded listing has the detail-page extras attached.
    sample = listings[0]
    assert sample.url.startswith(f"{base}/nl-NL/p/")
    assert sample.in_stock is True  # detail fixture is in-stock
    assert sample.finish in {"regular", "foil", "cold_foil"}
```

**Step 2: Verify failure**

Run: `uv run pytest tests/unit/services/marketplaces/test_bazaarofmagic_crawl.py -v`
Expected: FAIL — `BazaarAdapter` not defined.

**Step 3: Append the adapter class**

```python
# src/lorscan/services/marketplaces/bazaarofmagic.py  (append)

import asyncio
from urllib.parse import urlparse


class BazaarAdapter:
    """Adapter for https://www.bazaarofmagic.eu (Shopware 6)."""

    slug = "bazaarofmagic"
    display_name = "Bazaar of Magic"

    def __init__(
        self,
        *,
        items_per_page: int = 24,
        max_concurrent_details: int = 4,
        inter_batch_delay_s: float = 0.2,
    ):
        self._items_per_page = items_per_page
        self._max_concurrent_details = max_concurrent_details
        self._inter_batch_delay_s = inter_batch_delay_s

    async def crawl_set(
        self,
        client: httpx.AsyncClient,
        set_code: str,
        category_path: str,
    ) -> AsyncIterator[Listing]:
        base_url = f"{client.base_url.scheme}://{client.base_url.host}"
        page = 1
        while True:
            response = await client.get(
                category_path,
                params={"page": str(page), "items": str(self._items_per_page)},
            )
            response.raise_for_status()
            listing_cards = parse_listing_page(response.text, base_url=base_url)
            if not listing_cards:
                return

            sem = asyncio.Semaphore(self._max_concurrent_details)

            async def fetch(card: ListingCard) -> Listing | None:
                async with sem:
                    try:
                        detail_resp = await client.get(_path_only(card.url))
                        detail_resp.raise_for_status()
                    except httpx.HTTPError:
                        return None
                    extras = parse_detail_page(detail_resp.text)
                return Listing(
                    external_id=card.external_id,
                    title=card.title,
                    price_cents=card.price_cents,
                    currency="EUR",
                    in_stock=extras.in_stock,
                    url=card.url,
                    finish=extras.finish,
                    collector_number=extras.collector_number,
                )

            results = await asyncio.gather(*(fetch(c) for c in listing_cards))
            for listing in results:
                if listing is not None:
                    yield listing

            await asyncio.sleep(self._inter_batch_delay_s)
            page += 1


def _path_only(url: str) -> str:
    """Return just the path+query portion of an absolute URL."""
    parsed = urlparse(url)
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")
```

**Step 4: Re-run test**

Run: `uv run pytest tests/unit/services/marketplaces/test_bazaarofmagic_crawl.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/lorscan/services/marketplaces/bazaarofmagic.py \
        tests/unit/services/marketplaces/test_bazaarofmagic_crawl.py
git commit -m "feat(marketplaces): BazaarAdapter.crawl_set generator"
```

---

## Phase 5 — Matching

### Task 8: Strict `(set_code, collector_number) → card_id` resolver

**Files:**
- Create: `src/lorscan/services/marketplaces/matching.py`
- Create: `tests/unit/services/marketplaces/test_matching.py`

**Step 1: Write the failing test**

```python
# tests/unit/services/marketplaces/test_matching.py
"""Strict marketplace listing → card_id resolver."""

from __future__ import annotations

from lorscan.services.marketplaces.base import Listing
from lorscan.services.marketplaces.matching import resolve_listing
from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet


def _seed(db: Database) -> None:
    db.upsert_set(CardSet(set_code="ROF", name="Rise of the Floodborn", total_cards=204))
    db.upsert_card(
        Card(
            card_id="rof-224",
            set_code="ROF",
            collector_number="224",
            name="Pinocchio",
            subtitle="Strings Attached",
            rarity="Enchanted",
        )
    )


def _make_listing(*, collector_number: str | None) -> Listing:
    return Listing(
        external_id="9154978",
        title="Pinocchio, Strings Attached (#224) (foil)",
        price_cents=1500,
        currency="EUR",
        in_stock=True,
        url="https://example.com/x",
        finish="foil",
        collector_number=collector_number,
    )


def test_resolves_to_card_id_on_hit(db: Database):
    _seed(db)
    card_id = resolve_listing(
        db,
        set_code="ROF",
        listing=_make_listing(collector_number="224"),
    )
    assert card_id == "rof-224"


def test_returns_none_when_collector_number_missing(db: Database):
    _seed(db)
    card_id = resolve_listing(
        db,
        set_code="ROF",
        listing=_make_listing(collector_number=None),
    )
    assert card_id is None


def test_returns_none_when_no_catalog_match(db: Database):
    _seed(db)
    card_id = resolve_listing(
        db,
        set_code="ROF",
        listing=_make_listing(collector_number="999"),
    )
    assert card_id is None
```

**Step 2: Verify failure**

Run: `uv run pytest tests/unit/services/marketplaces/test_matching.py -v`
Expected: FAIL — module missing.

**Step 3: Implement**

```python
# src/lorscan/services/marketplaces/matching.py
"""Strict marketplace-listing → catalog card_id resolver.

Future shops (eBay etc.) with messier listings will need fuzzy matching;
that logic slots in behind this same function signature without changing
the adapter or storage layers.
"""

from __future__ import annotations

from lorscan.services.marketplaces.base import Listing
from lorscan.storage.db import Database


def resolve_listing(
    db: Database,
    *,
    set_code: str,
    listing: Listing,
) -> str | None:
    """Return the catalog card_id for a listing, or None if no strict match."""
    if listing.collector_number is None:
        return None
    card = db.get_card_by_collector_number(set_code, listing.collector_number)
    return card.card_id if card else None
```

**Step 4: Pass**

Run: `uv run pytest tests/unit/services/marketplaces/test_matching.py -v`
Expected: all PASS.

**Step 5: Commit**

```bash
git add src/lorscan/services/marketplaces/matching.py \
        tests/unit/services/marketplaces/test_matching.py
git commit -m "feat(marketplaces): strict (set,collector_number) resolver"
```

---

## Phase 6 — Storage layer

### Task 9: `Database` methods for marketplaces, listings, sweeps

**Files:**
- Modify: `src/lorscan/storage/db.py`
- Create: `tests/unit/test_db_marketplace_ops.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_db_marketplace_ops.py
"""DB ops: marketplaces, set-categories, listings, sweeps."""

from __future__ import annotations

from datetime import UTC, datetime

from lorscan.services.marketplaces.base import Listing
from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet


def _seed_catalog(db: Database) -> None:
    db.upsert_set(CardSet(set_code="ROF", name="Rise of the Floodborn", total_cards=204))
    db.upsert_card(
        Card(
            card_id="rof-224",
            set_code="ROF",
            collector_number="224",
            name="Pinocchio",
            subtitle="Strings Attached",
            rarity="Enchanted",
        )
    )


def test_get_marketplace_by_slug_returns_seeded_bazaar(db: Database):
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    assert mp is not None
    assert mp["display_name"] == "Bazaar of Magic"


def test_upsert_set_category_inserts_then_updates(db: Database):
    _seed_catalog(db)
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    db.upsert_set_category(
        marketplace_id=mp["id"],
        set_code="ROF",
        category_id="1000676",
        category_path="/nl-NL/c/rise-of-the-floodborn/1000676",
    )
    cats = db.get_enabled_set_categories(marketplace_id=mp["id"])
    assert len(cats) == 1
    assert cats[0]["set_code"] == "ROF"

    # Updating the path is idempotent.
    db.upsert_set_category(
        marketplace_id=mp["id"],
        set_code="ROF",
        category_id="1000676",
        category_path="/nl-NL/c/rise-of-the-floodborn-NEW/1000676",
    )
    cats = db.get_enabled_set_categories(marketplace_id=mp["id"])
    assert cats[0]["category_path"].endswith("-NEW/1000676")


def test_sweep_lifecycle(db: Database):
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    sweep_id = db.start_marketplace_sweep(mp["id"])
    assert isinstance(sweep_id, int)
    db.finish_marketplace_sweep(
        sweep_id,
        listings_seen=10,
        listings_matched=8,
        errors=0,
        status="ok",
    )
    row = db.get_sweep(sweep_id)
    assert row["status"] == "ok"
    assert row["listings_seen"] == 10
    assert row["finished_at"] is not None


def test_upsert_listing_then_query_cheapest_in_stock(db: Database):
    _seed_catalog(db)
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    now = datetime.now(UTC).isoformat()
    base = dict(
        marketplace_id=mp["id"],
        currency="EUR",
        url="https://example.com/x",
        title="Pinocchio (#224) (foil)",
        fetched_at=now,
    )
    db.upsert_listing(
        external_id="A",
        card_id="rof-224",
        finish="foil",
        price_cents=1500,
        in_stock=True,
        **base,
    )
    db.upsert_listing(
        external_id="B",
        card_id="rof-224",
        finish="regular",
        price_cents=400,
        in_stock=True,
        **base,
    )
    db.upsert_listing(
        external_id="C",
        card_id="rof-224",
        finish="regular",
        price_cents=300,
        in_stock=False,  # cheapest, but out of stock — must be skipped
        **base,
    )

    cheapest = db.get_cheapest_in_stock_per_card()
    assert cheapest["rof-224"]["price_cents"] == 400
    assert cheapest["rof-224"]["marketplace_id"] == mp["id"]


def test_get_latest_finished_sweep_returns_none_when_empty(db: Database):
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    assert db.get_latest_finished_sweep(mp["id"]) is None
```

**Step 2: Verify failure**

Run: `uv run pytest tests/unit/test_db_marketplace_ops.py -v`
Expected: FAIL — methods missing.

**Step 3: Append methods to `Database` (in `db.py`, after the existing collection ops)**

```python
# src/lorscan/storage/db.py  (append at the bottom of the class, before any
# trailing __all__ or module-level code)

    # ---------- marketplace ops ----------

    def get_marketplace_by_slug(self, slug: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT id, slug, display_name, base_url, enabled "
            "FROM marketplaces WHERE slug = ?",
            (slug,),
        ).fetchone()

    def upsert_set_category(
        self,
        *,
        marketplace_id: int,
        set_code: str,
        category_id: str,
        category_path: str,
    ) -> None:
        self.connection.execute(
            "INSERT INTO marketplace_set_categories "
            "  (marketplace_id, set_code, category_id, category_path) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(marketplace_id, set_code) DO UPDATE SET "
            "  category_id = excluded.category_id, "
            "  category_path = excluded.category_path",
            (marketplace_id, set_code, category_id, category_path),
        )
        self.connection.commit()

    def get_enabled_set_categories(self, *, marketplace_id: int) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            "SELECT msc.set_code, msc.category_id, msc.category_path "
            "FROM marketplace_set_categories msc "
            "JOIN sets s ON s.set_code = msc.set_code "
            "WHERE msc.marketplace_id = ? "
            "ORDER BY msc.set_code",
            (marketplace_id,),
        ).fetchall()
        return list(rows)

    def upsert_listing(
        self,
        *,
        marketplace_id: int,
        external_id: str,
        card_id: str | None,
        finish: str | None,
        price_cents: int,
        currency: str,
        in_stock: bool,
        url: str,
        title: str,
        fetched_at: str,
    ) -> None:
        self.connection.execute(
            "INSERT INTO marketplace_listings "
            "  (marketplace_id, external_id, card_id, finish, price_cents, "
            "   currency, in_stock, url, title, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(marketplace_id, external_id) DO UPDATE SET "
            "  card_id = excluded.card_id, "
            "  finish = excluded.finish, "
            "  price_cents = excluded.price_cents, "
            "  currency = excluded.currency, "
            "  in_stock = excluded.in_stock, "
            "  url = excluded.url, "
            "  title = excluded.title, "
            "  fetched_at = excluded.fetched_at",
            (
                marketplace_id,
                external_id,
                card_id,
                finish,
                price_cents,
                currency,
                int(in_stock),
                url,
                title,
                fetched_at,
            ),
        )
        self.connection.commit()

    def get_cheapest_in_stock_per_card(self) -> dict[str, dict]:
        """Map card_id → {price_cents, currency, url, marketplace_id, finish}.

        Picks the cheapest in-stock listing per card across all enabled shops.
        Excludes listings with NULL card_id.
        """
        rows = self.connection.execute(
            "SELECT ml.card_id, ml.price_cents, ml.currency, ml.url, "
            "       ml.marketplace_id, ml.finish "
            "FROM marketplace_listings ml "
            "JOIN marketplaces m ON m.id = ml.marketplace_id "
            "WHERE ml.in_stock = 1 AND ml.card_id IS NOT NULL AND m.enabled = 1 "
            "AND ml.price_cents = ("
            "  SELECT MIN(price_cents) FROM marketplace_listings ml2 "
            "  WHERE ml2.card_id = ml.card_id AND ml2.in_stock = 1"
            ")"
        ).fetchall()
        result: dict[str, dict] = {}
        for row in rows:
            cid = row["card_id"]
            if cid in result:
                continue  # tie — keep the first one
            result[cid] = {
                "price_cents": int(row["price_cents"]),
                "currency": row["currency"],
                "url": row["url"],
                "marketplace_id": int(row["marketplace_id"]),
                "finish": row["finish"],
            }
        return result

    def start_marketplace_sweep(self, marketplace_id: int) -> int:
        cursor = self.connection.execute(
            "INSERT INTO marketplace_sweeps "
            "  (marketplace_id, started_at, status) "
            "VALUES (?, ?, 'running')",
            (marketplace_id, datetime.now(UTC).isoformat()),
        )
        self.connection.commit()
        return int(cursor.lastrowid or 0)

    def finish_marketplace_sweep(
        self,
        sweep_id: int,
        *,
        listings_seen: int,
        listings_matched: int,
        errors: int,
        status: str,
    ) -> None:
        self.connection.execute(
            "UPDATE marketplace_sweeps SET "
            "  finished_at = ?, listings_seen = ?, listings_matched = ?, "
            "  errors = ?, status = ? "
            "WHERE id = ?",
            (
                datetime.now(UTC).isoformat(),
                listings_seen,
                listings_matched,
                errors,
                status,
                sweep_id,
            ),
        )
        self.connection.commit()

    def get_sweep(self, sweep_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM marketplace_sweeps WHERE id = ?", (sweep_id,)
        ).fetchone()

    def get_latest_finished_sweep(self, marketplace_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM marketplace_sweeps "
            "WHERE marketplace_id = ? AND finished_at IS NOT NULL "
            "ORDER BY finished_at DESC LIMIT 1",
            (marketplace_id,),
        ).fetchone()
```

**Step 4: Re-run all the new tests**

Run: `uv run pytest tests/unit/test_db_marketplace_ops.py -v`
Expected: all PASS.

**Step 5: Commit**

```bash
git add src/lorscan/storage/db.py tests/unit/test_db_marketplace_ops.py
git commit -m "feat(marketplaces): Database ops for listings + sweeps"
```

---

## Phase 7 — Sweep orchestrator

### Task 10: Sweep orchestrator + TOML loader

**Files:**
- Create: `src/lorscan/services/marketplaces/orchestrator.py`
- Create: `src/lorscan/services/marketplaces/seed.py`
- Create: `tests/unit/services/marketplaces/test_seed.py`
- Create: `tests/integration/test_marketplace_sweep.py`

**Step 1: Write the seed-loader test**

```python
# tests/unit/services/marketplaces/test_seed.py
"""TOML loader for the per-set category seed file."""

from __future__ import annotations

from pathlib import Path

from lorscan.services.marketplaces.seed import load_set_map


def test_load_set_map(tmp_path: Path):
    f = tmp_path / "set_map.toml"
    f.write_text(
        '[[set]]\n'
        'code = "ROF"\n'
        'category_id = "1000676"\n'
        'category_path = "/nl-NL/c/rise-of-the-floodborn/1000676"\n'
        '\n'
        '[[set]]\n'
        'code = "ITI"\n'
        'category_id = "1000697"\n'
        'category_path = "/nl-NL/c/into-the-inklands/1000697"\n'
    )
    entries = load_set_map(f)
    assert {e.set_code for e in entries} == {"ROF", "ITI"}
    rof = next(e for e in entries if e.set_code == "ROF")
    assert rof.category_id == "1000676"
    assert rof.category_path == "/nl-NL/c/rise-of-the-floodborn/1000676"
```

**Step 2: Verify failure, then implement**

Run: `uv run pytest tests/unit/services/marketplaces/test_seed.py -v`
Expected: FAIL.

```python
# src/lorscan/services/marketplaces/seed.py
"""Load the hand-curated per-set category map from TOML."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SetMapEntry:
    set_code: str
    category_id: str
    category_path: str


def load_set_map(path: Path) -> list[SetMapEntry]:
    data = tomllib.loads(path.read_text())
    entries = []
    for raw in data.get("set", []):
        entries.append(
            SetMapEntry(
                set_code=str(raw["code"]),
                category_id=str(raw["category_id"]),
                category_path=str(raw["category_path"]),
            )
        )
    return entries
```

Re-run test, confirm PASS.

**Step 3: Write the integration test for the orchestrator**

```python
# tests/integration/test_marketplace_sweep.py
"""End-to-end sweep: TOML → adapter → matcher → DB, with HTTP mocked."""

from __future__ import annotations

from pathlib import Path

import httpx
import respx

from lorscan.services.marketplaces.bazaarofmagic import BazaarAdapter
from lorscan.services.marketplaces.orchestrator import run_sweep
from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "marketplaces" / "bazaarofmagic"


def _seed_catalog(db: Database) -> None:
    db.upsert_set(CardSet(set_code="ROF", name="Rise of the Floodborn", total_cards=204))
    db.upsert_card(
        Card(
            card_id="rof-224",
            set_code="ROF",
            collector_number="224",
            name="Pinocchio",
            subtitle="Strings Attached",
            rarity="Enchanted",
        )
    )


async def test_sweep_writes_listings_and_records_status(db: Database):
    _seed_catalog(db)
    mp = db.get_marketplace_by_slug("bazaarofmagic")
    db.upsert_set_category(
        marketplace_id=mp["id"],
        set_code="ROF",
        category_id="1000676",
        category_path="/nl-NL/c/rise-of-the-floodborn/1000676",
    )

    base = "https://www.bazaarofmagic.eu"
    listing_html = (FIXTURE_DIR / "listing.html").read_text()
    detail_html = (FIXTURE_DIR / "detail.html").read_text()
    empty_html = (FIXTURE_DIR / "empty_listing.html").read_text()

    with respx.mock(assert_all_called=False) as mock:
        mock.get(
            f"{base}/nl-NL/c/rise-of-the-floodborn/1000676",
            params={"page": "1", "items": "24"},
        ).mock(return_value=httpx.Response(200, text=listing_html))
        mock.get(
            f"{base}/nl-NL/c/rise-of-the-floodborn/1000676",
            params={"page": "2", "items": "24"},
        ).mock(return_value=httpx.Response(200, text=empty_html))
        mock.get(url__regex=rf"{base}/nl-NL/p/.+").mock(
            return_value=httpx.Response(200, text=detail_html)
        )

        result = await run_sweep(
            db,
            adapter=BazaarAdapter(),
            base_url=base,
        )

    assert result.status == "ok"
    assert result.listings_seen > 0
    sweep = db.get_latest_finished_sweep(mp["id"])
    assert sweep is not None
    assert sweep["status"] == "ok"

    # Cheapest-in-stock map now has at least our seeded card
    # (assuming the listing fixture happens to include #224 with in-stock).
    # If the fixture's #224 entry is out of stock when captured, replace this
    # assertion with `assert isinstance(db.get_cheapest_in_stock_per_card(), dict)`.
```

**Step 4: Run, confirm fails**

Run: `uv run pytest tests/integration/test_marketplace_sweep.py -v`
Expected: FAIL — orchestrator missing.

**Step 5: Implement orchestrator**

```python
# src/lorscan/services/marketplaces/orchestrator.py
"""Drive one full sweep against one shop adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from lorscan.services.marketplaces.base import ShopAdapter
from lorscan.services.marketplaces.matching import resolve_listing
from lorscan.storage.db import Database


@dataclass(frozen=True)
class SweepResult:
    sweep_id: int
    status: str          # 'ok' | 'partial' | 'failed'
    listings_seen: int
    listings_matched: int
    errors: int


_USER_AGENT = "lorscan/0.1 (+https://github.com/ityou-tech/lorscan)"


async def run_sweep(
    db: Database,
    *,
    adapter: ShopAdapter,
    base_url: str,
    only_set: str | None = None,
) -> SweepResult:
    """Crawl every enabled set on `adapter`, write listings, record sweep stats."""
    mp = db.get_marketplace_by_slug(adapter.slug)
    if mp is None:
        raise RuntimeError(
            f"marketplace {adapter.slug!r} not seeded — apply migration 007"
        )
    sweep_id = db.start_marketplace_sweep(mp["id"])

    categories = db.get_enabled_set_categories(marketplace_id=mp["id"])
    if only_set:
        categories = [c for c in categories if c["set_code"] == only_set]

    seen = matched = errors = 0
    set_failures = 0

    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=20.0,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        for cat in categories:
            try:
                async for listing in adapter.crawl_set(
                    client,
                    set_code=cat["set_code"],
                    category_path=cat["category_path"],
                ):
                    seen += 1
                    card_id = resolve_listing(
                        db, set_code=cat["set_code"], listing=listing
                    )
                    if card_id is not None:
                        matched += 1
                    db.upsert_listing(
                        marketplace_id=mp["id"],
                        external_id=listing.external_id,
                        card_id=card_id,
                        finish=listing.finish,
                        price_cents=listing.price_cents,
                        currency=listing.currency,
                        in_stock=listing.in_stock,
                        url=listing.url,
                        title=listing.title,
                        fetched_at=datetime.now(UTC).isoformat(),
                    )
            except httpx.HTTPError:
                errors += 1
                set_failures += 1
                continue

    if set_failures and set_failures < len(categories):
        status = "partial"
    elif set_failures and set_failures == len(categories):
        status = "failed"
    else:
        status = "ok"

    db.finish_marketplace_sweep(
        sweep_id,
        listings_seen=seen,
        listings_matched=matched,
        errors=errors,
        status=status,
    )
    return SweepResult(
        sweep_id=sweep_id,
        status=status,
        listings_seen=seen,
        listings_matched=matched,
        errors=errors,
    )
```

**Step 6: Re-run integration test**

Run: `uv run pytest tests/integration/test_marketplace_sweep.py -v`
Expected: PASS.

**Step 7: Commit**

```bash
git add src/lorscan/services/marketplaces/seed.py \
        src/lorscan/services/marketplaces/orchestrator.py \
        tests/unit/services/marketplaces/test_seed.py \
        tests/integration/test_marketplace_sweep.py
git commit -m "feat(marketplaces): sweep orchestrator + TOML seed loader"
```

---

## Phase 8 — CLI

### Task 11: `lorscan marketplaces refresh|status` commands

**Files:**
- Modify: `src/lorscan/cli.py`
- Create: `tests/unit/test_cli_marketplaces.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_cli_marketplaces.py
"""CLI smoke tests for `lorscan marketplaces ...`."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

from lorscan.cli import main


def test_marketplaces_status_prints_no_sweep_yet(
    tmp_data_dir: Path, capsys: object
) -> None:
    rc = main(["marketplaces", "status"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "no sweep" in captured.out.lower() or "never" in captured.out.lower()


def test_marketplaces_refresh_invokes_sweep(
    tmp_data_dir: Path, capsys: object
) -> None:
    fake_result = type(
        "R",
        (),
        {
            "sweep_id": 1,
            "status": "ok",
            "listings_seen": 5,
            "listings_matched": 4,
            "errors": 0,
        },
    )()
    with patch(
        "lorscan.cli._run_marketplace_sweep",
        new=AsyncMock(return_value=fake_result),
    ) as mock_sweep:
        rc = main(["marketplaces", "refresh", "--shop", "bazaarofmagic"])
    assert rc == 0
    mock_sweep.assert_called_once()
    captured = capsys.readouterr()
    assert "5" in captured.out
    assert "ok" in captured.out
```

**Step 2: Verify failure**

Run: `uv run pytest tests/unit/test_cli_marketplaces.py -v`
Expected: FAIL — subcommand missing.

**Step 3: Add subparser + commands to `cli.py`**

In `cli.py`, add a new `marketplaces` subparser with `refresh` and `status` sub-commands. Sketch:

```python
# src/lorscan/cli.py — additions

# In main(), after the existing sub.add_parser(...) calls:
mp_p = sub.add_parser("marketplaces", help="Scrape & query marketplace stock.")
mp_sub = mp_p.add_subparsers(dest="mp_command", required=True)

refresh_p = mp_sub.add_parser("refresh", help="Run a full sweep across enabled shops.")
refresh_p.add_argument("--shop", default=None, help="Limit to one shop slug")
refresh_p.add_argument("--set", dest="set_code", default=None, help="Limit to one set code")

mp_sub.add_parser("status", help="Print last-sweep summary per shop.")

# In the dispatch chain at the bottom of main():
elif args.command == "marketplaces":
    cfg = load_config(env=os.environ)
    if args.mp_command == "refresh":
        return marketplaces_refresh_command(
            config=cfg, shop_slug=args.shop, set_code=args.set_code
        )
    elif args.mp_command == "status":
        return marketplaces_status_command(config=cfg)
```

Define the two command functions:

```python
def marketplaces_refresh_command(
    *,
    config: Config,
    shop_slug: str | None,
    set_code: str | None,
) -> int:
    db = Database.connect(str(config.db_path))
    db.migrate()
    try:
        # Upsert per-set categories from the bundled TOML before sweeping.
        from lorscan.services.marketplaces.seed import load_set_map

        seed_path = Path(__file__).resolve().parents[2] / "data" / "bazaarofmagic_set_map.toml"
        if seed_path.exists():
            mp = db.get_marketplace_by_slug("bazaarofmagic")
            if mp is not None:
                for entry in load_set_map(seed_path):
                    db.upsert_set_category(
                        marketplace_id=mp["id"],
                        set_code=entry.set_code,
                        category_id=entry.category_id,
                        category_path=entry.category_path,
                    )

        result = asyncio.run(
            _run_marketplace_sweep(db, shop_slug=shop_slug, set_code=set_code)
        )
    finally:
        db.close()

    print(
        f"Sweep #{result.sweep_id}: {result.status} — "
        f"{result.listings_matched}/{result.listings_seen} listings matched, "
        f"{result.errors} errors."
    )
    return 0 if result.status in ("ok", "partial") else 1


async def _run_marketplace_sweep(
    db: Database,
    *,
    shop_slug: str | None,
    set_code: str | None,
):
    """Thin async wrapper so tests can patch this single symbol."""
    from lorscan.services.marketplaces.bazaarofmagic import BazaarAdapter
    from lorscan.services.marketplaces.orchestrator import run_sweep

    if shop_slug not in (None, "bazaarofmagic"):
        raise ValueError(f"unknown shop: {shop_slug!r}")
    return await run_sweep(
        db,
        adapter=BazaarAdapter(),
        base_url="https://www.bazaarofmagic.eu",
        only_set=set_code,
    )


def marketplaces_status_command(*, config: Config) -> int:
    db = Database.connect(str(config.db_path))
    db.migrate()
    try:
        mp = db.get_marketplace_by_slug("bazaarofmagic")
        if mp is None:
            print("No marketplaces configured.")
            return 0
        sweep = db.get_latest_finished_sweep(mp["id"])
        if sweep is None:
            print(f"{mp['display_name']}: no sweep yet. "
                  f"Run `lorscan marketplaces refresh`.")
            return 0
        print(
            f"{mp['display_name']}: last sweep at {sweep['finished_at']} — "
            f"status={sweep['status']}, "
            f"matched={sweep['listings_matched']}/{sweep['listings_seen']}, "
            f"errors={sweep['errors']}."
        )
    finally:
        db.close()
    return 0
```

**Step 4: Re-run CLI tests**

Run: `uv run pytest tests/unit/test_cli_marketplaces.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/lorscan/cli.py tests/unit/test_cli_marketplaces.py
git commit -m "feat(cli): lorscan marketplaces refresh|status"
```

---

## Phase 9 — `/collection` wire-up

### Task 12: Add badge query + cards-needed stats to the route

**Files:**
- Modify: `src/lorscan/app/routes/collection.py`
- Modify: `tests/integration/test_routes_smoke.py` (add new test, will edit existing further down)

**Step 1: Write the new test**

Append to `tests/integration/test_routes_smoke.py`:

```python
def test_collection_renders_marketplace_badge(client: TestClient):
    """When a matched in-stock listing exists, /collection shows a price badge."""
    from datetime import UTC, datetime

    cfg = client.app.state.config
    db = Database.connect(str(cfg.db_path))
    db.migrate()
    try:
        mp = db.get_marketplace_by_slug("bazaarofmagic")
        db.upsert_listing(
            marketplace_id=mp["id"],
            external_id="9999",
            card_id="rof-001",   # rof-001 was seeded in _seed_db
            finish="regular",
            price_cents=400,
            currency="EUR",
            in_stock=True,
            url="https://www.bazaarofmagic.eu/nl-NL/p/x/9999",
            title="Pinocchio (#1)",
            fetched_at=datetime.now(UTC).isoformat(),
        )
    finally:
        db.close()

    response = client.get("/collection")
    assert response.status_code == 200
    body = response.text
    assert "€4,00" in body or "€ 4,00" in body or "€4.00" in body
    assert "9999" in body  # the external_id appears in the URL we render
```

**Step 2: Run, confirm fail (no badge rendered yet)**

Run: `uv run pytest tests/integration/test_routes_smoke.py::test_collection_renders_marketplace_badge -v`
Expected: FAIL.

**Step 3: Modify `_build_binders` and `collection_index`**

In `src/lorscan/app/routes/collection.py`:

- Add a parameter `badges: dict[str, dict] | None = None` to `_build_binders`. After building each `card` dict, attach `card["badge"] = badges.get(c["card_id"]) if badges else None`.
- In `collection_index`, fetch `badges = db.get_cheapest_in_stock_per_card()` and pass to `_build_binders`.
- Compute the new header stats:
  ```python
  total_catalog = sum(b["total"] for b in binders)
  distinct_owned = sum(b["owned_count"] for b in binders)
  cards_needed = total_catalog - distinct_owned
  unfinished_sets = sum(1 for b in binders if b["owned_count"] < b["total"])
  ```
- Compute `closest` and `total_missing` exactly as `missing_index` did (port the logic verbatim).
- Compute `last_sweep`:
  ```python
  mp = db.get_marketplace_by_slug("bazaarofmagic")
  last_sweep = db.get_latest_finished_sweep(mp["id"]) if mp else None
  ```
- Pass `badges`, `cards_needed`, `unfinished_sets`, `closest`, `total_missing`, `last_sweep` into the template context.

**Step 4: Modify `_partials/binder.html`**

In each `pocket--missing` block (the `{% else %}` branch), inject before the `<form action="/collection/add">`:

```html
{% if card.badge %}
<a href="{{ card.badge.url }}" target="_blank" rel="noopener"
   class="pocket-badge"
   title="In stock at {{ card.badge.shop_name or 'shop' }}">
  €{{ '%.2f' | format(card.badge.price_cents / 100) | replace('.', ',') }}
  · {{ card.badge.shop_name or 'shop' }}
</a>
{% endif %}
```

To make `shop_name` available, change `get_cheapest_in_stock_per_card` to also return the marketplace `display_name`, or join it in the route — simplest: in the route, post-process `badges` to look up `display_name` for each entry.

**Step 5: Re-run tests**

Run: `uv run pytest tests/integration/test_routes_smoke.py -v`
Expected: PASS (new test + existing `test_collection_index_empty_state` etc.).

**Step 6: Commit**

```bash
git add src/lorscan/app/routes/collection.py \
        src/lorscan/app/templates/_partials/binder.html \
        tests/integration/test_routes_smoke.py
git commit -m "feat(collection): render marketplace price badges on empty pockets"
```

---

### Task 13: Port `/missing` features into `/collection` template

**Files:**
- Modify: `src/lorscan/app/templates/collection/index.html`
- Modify: `src/lorscan/app/templates/_partials/binder.html`
- Modify: `src/lorscan/app/static/js/binder.js` (only if want-list copy logic lives there — read first)

**Step 1: Read the existing copy-want JS**

Run: `grep -n "data-copy" src/lorscan/app/static/js/binder.js`
Expected: existing handlers for `[data-copy-all]` and `[data-copy-binder]`. Preserve them — they should keep working once the buttons live in `/collection`.

**Step 2: Modify `/collection/index.html`**

Add to the `page-header-meta` block (next to existing `cards owned` / `distinct cards`):

```html
<div class="meta-stat">
  <span class="meta-stat-num">{{ cards_needed }}</span>
  <span class="meta-stat-label">cards needed</span>
</div>
<div class="meta-stat">
  <span class="meta-stat-num">{{ unfinished_sets }}</span>
  <span class="meta-stat-label">sets unfinished</span>
</div>
{% if cards_needed > 0 %}
<button type="button" class="primary copy-want-btn" data-copy-all>
  📋 Copy full want-list
</button>
{% endif %}
```

Below the header, add the refreshed-at line and (if any) the closest-strip — both copied from `missing/index.html`:

```html
{% if last_sweep %}
<p class="marketplace-refreshed">
  Marketplace data refreshed
  <time datetime="{{ last_sweep.finished_at }}">{{ last_sweep.finished_at }}</time>.
  Run <code>lorscan marketplaces refresh</code> to update.
</p>
{% endif %}

{% if closest %}
<section class="closest-strip" aria-label="Sets closest to complete">
  <span class="closest-label">Closest to complete</span>
  <div class="closest-tiles">
    {% for c in closest %}
    <a href="#{{ c.set_code }}" class="closest-tile">
      <span class="closest-tile-pct">{{ c.pct }}%</span>
      <span class="closest-tile-name">{{ c.name }}</span>
      <span class="closest-tile-need">{{ c.missing_count }} missing</span>
    </a>
    {% endfor %}
  </div>
</section>
{% endif %}

<div id="copy-toast" class="copy-toast" role="status" aria-live="polite" hidden>Copied to clipboard</div>
```

Remove the `set mode = 'collection'` line and replace with whatever flag controls whether the per-binder copy-want button shows (see next step).

**Step 3: Modify `_partials/binder.html`**

Drop the `mode == 'missing'` guard around the per-binder copy button — instead always show it when `binder.owned_count < binder.total`:

```jinja
{% if binder.owned_count < binder.total %}
<button type="button" class="copy-want-btn copy-want-btn--inline"
        data-copy-binder="{{ binder.set_code }}">
  📋 Copy want-list
</button>
{% endif %}
```

Strip every other `{% if mode == ... %}` branch in this partial. The `mode` variable goes away entirely.

**Step 4: Add a smoke test**

Append to `tests/integration/test_routes_smoke.py`:

```python
def test_collection_shows_ported_missing_features(client: TestClient):
    """Header gains 'cards needed', closest-strip + copy buttons appear."""
    response = client.get("/collection")
    assert response.status_code == 200
    body = response.text
    assert "cards needed" in body
    assert "sets unfinished" in body
    # Empty state collection has no missing cards (no catalog seeded with
    # collection rows); but cards_needed = total_catalog - 0 > 0 so the
    # copy-all button should still render.
    assert "data-copy-all" in body
```

**Step 5: Run all routes tests**

Run: `uv run pytest tests/integration/test_routes_smoke.py -v`
Expected: all PASS.

**Step 6: Commit**

```bash
git add src/lorscan/app/templates/collection/index.html \
        src/lorscan/app/templates/_partials/binder.html \
        tests/integration/test_routes_smoke.py
git commit -m "feat(collection): port cards-needed + closest-strip + copy-want from /missing"
```

---

## Phase 10 — Delete `/missing`

### Task 14: Remove the route, template, nav link, and tests

**Files:**
- Modify: `src/lorscan/app/routes/collection.py` (drop `missing_index` handler)
- Delete: `src/lorscan/app/templates/missing/` (entire directory)
- Modify: `src/lorscan/app/templates/base.html` (drop nav link)
- Modify: `tests/integration/test_routes_smoke.py` (drop `test_missing_index_renders_set_progress`)

**Step 1: Drop the test**

Delete `test_missing_index_renders_set_progress` from `test_routes_smoke.py`.

**Step 2: Add a 404 test**

Append:

```python
def test_missing_route_is_gone(client: TestClient):
    response = client.get("/missing")
    assert response.status_code == 404
```

**Step 3: Run, confirm passes (because route still exists, the 404 test will fail)**

Run: `uv run pytest tests/integration/test_routes_smoke.py::test_missing_route_is_gone -v`
Expected: FAIL — route currently returns 200.

**Step 4: Delete handler + template + nav**

```bash
rm -rf src/lorscan/app/templates/missing
```

In `src/lorscan/app/routes/collection.py`, delete the entire `@router.get("/missing", ...)` `missing_index` function.

In `src/lorscan/app/templates/base.html`, delete the `<a href="/missing">Missing</a>` line from the nav.

**Step 5: Re-run all tests**

Run: `uv run pytest -v`
Expected: all PASS, including the new 404 test.

**Step 6: Verify no stragglers**

```bash
grep -rn "/missing" src/ tests/ docs/
```
Expected output: only matches in `docs/plans/...` (design + plan docs), and possibly `README.md` references — nothing in `src/` or `tests/`.

**Step 7: Commit**

```bash
git add -u src/lorscan/app/routes/collection.py \
            src/lorscan/app/templates/base.html \
            tests/integration/test_routes_smoke.py
git rm -r src/lorscan/app/templates/missing
git commit -m "feat(collection): drop /missing route — features ported to /collection"
```

---

## Phase 11 — Documentation & smoke

### Task 15: README + manual smoke

**Files:**
- Modify: `README.md`

**Step 1: Update README**

Add a new section after "How recognition works":

```markdown
## Marketplace stock

`lorscan` can scrape known card shops to surface "available to buy"
data on the missing pockets in `/collection`. Currently supports
[Bazaar of Magic](https://www.bazaarofmagic.eu).

```bash
uv run lorscan marketplaces refresh    # ~10–15 min full sweep
uv run lorscan marketplaces status     # last-sweep summary
```

Refresh whenever you want fresh prices — there is no background
scheduler. The page header shows when the data was last refreshed.

To add or update which Lorcana sets get scraped on Bazaar, edit
`data/bazaarofmagic_set_map.toml` (one row per set). The next
`refresh` picks up the new mapping automatically.
```

Also update the project-structure tree to include `services/marketplaces/`.

**Step 2: Run the full test suite**

Run: `uv run pytest`
Expected: all green.

**Step 3: Lint**

Run: `uv run ruff check src tests`
Expected: clean.

**Step 4: Manual smoke (optional but recommended)**

```bash
uv run lorscan marketplaces refresh --set ROF
uv run lorscan marketplaces status
uv run lorscan serve
```

Open <http://localhost:8000/collection>. Confirm:
- Page header shows "X cards needed" and "Y sets unfinished".
- "Marketplace data refreshed ..." line is visible.
- At least one empty pocket in ROF shows a `€X · Bazaar` badge that opens the Bazaar product page in a new tab.
- `/missing` returns a 404.
- Copy-want-list buttons (global + per-binder) still copy text.

**Step 5: Commit**

```bash
git add README.md
git commit -m "docs(readme): document lorscan marketplaces refresh|status"
```

---

## Done — final verification

```bash
uv run pytest -v        # everything green
uv run ruff check src tests
git log --oneline -20   # ~15 small commits, all on this branch
```

Open a PR (or merge to main) once smoke tests look good.
