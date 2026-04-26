# Marketplace stock integration — design

**Date:** 2026-04-26
**Status:** Approved, ready for implementation planning.
**Author:** Enri (with Claude)

## Goal

Surface "available to buy right now" data on lorscan's `/collection` page, starting with [Bazaar of Magic](https://www.bazaarofmagic.eu/), with the architecture ready to plug eBay and other shops in later. Delete the standalone `/missing` page and absorb its useful prioritization features into `/collection`.

## Out of scope (v1)

- Fuzzy matching for messy listing titles (eBay, loose-format sellers).
- Manual-mapping or human-review UI for ambiguous matches.
- Live "refresh now" button in the web UI.
- Shipping cost, multi-currency conversion.
- Cart-export / multi-shop comparison shopping.
- Per-finish ownership tracking (today lorscan treats "owned in any finish" as owned; that does not change here).
- Auto-discovery of per-set category IDs on Bazaar (hand-curated TOML for the 11 known sets is enough).

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Refresh model | **Manual** — `lorscan marketplaces refresh` invoked by the user | No background job to monitor; staleness is user-chosen and visible in the page header. |
| Match strictness | **Strict** — `(set_code, collector_number) → card_id` direct lookup | Bazaar exposes both fields cleanly; near 100% hit rate without any fuzzy logic. Defer fuzzy until eBay forces the issue. |
| Crawl shape | **Per-set categories** | Bazaar exposes per-set category URLs (e.g. ROF=`/c/rise-of-the-floodborn/1000676`). Set is known up-front from the URL we requested; partial failures are naturally chunked. |
| UI placement | **`/collection`; delete `/missing`** | `/collection` already shows every card with empty pockets for what's not owned — putting the price right next to the gap matches the existing mental model. `/missing`'s prioritization features (closest-to-complete, want-list) port over cleanly. |

## Architecture

```
src/lorscan/services/marketplaces/
  __init__.py
  base.py              ShopAdapter Protocol; Listing dataclass; Sweep orchestrator
  bazaarofmagic.py     Bazaar adapter (only adapter shipping in v1)
  matching.py          strict (set_code, collector_number) → card_id resolver
  storage.py           DB ops for listings + sweeps + bootstrap seeding

data/
  bazaarofmagic_set_map.toml   hand-curated 11-row (set_code → category_id) map
```

CLI:

```
lorscan marketplaces refresh [--shop bazaarofmagic] [--set ROF] [--dry-run]
lorscan marketplaces status
```

No scheduler integration. README documents the manual command.

### ShopAdapter Protocol

```python
@dataclass(frozen=True)
class Listing:
    external_id: str            # shop's product id, e.g. '9154978'
    title: str                  # raw title for diagnostics
    price_cents: int
    currency: str               # ISO 4217 (Bazaar = 'EUR')
    in_stock: bool
    url: str                    # absolute product detail URL
    finish: str | None          # 'regular' | 'foil' | 'cold_foil'
    collector_number: str | None  # parsed from product detail; None if not found

class ShopAdapter(Protocol):
    slug: str                   # e.g. 'bazaarofmagic'
    display_name: str           # e.g. 'Bazaar of Magic'

    async def crawl_set(
        self,
        client: httpx.AsyncClient,
        set_code: str,
        category_path: str,
    ) -> AsyncIterator[Listing]: ...
```

The matcher (`matching.py`) takes a `Listing` plus the known `set_code` (from which category we crawled it under) and returns `card_id | None`. It's the future-proofing layer: when fuzzy matching arrives, it slots in here without changes to the adapter or storage.

## Data model

New SQLite migration `007_marketplaces.sql`. Additive and idempotent. Failure to apply does not break `/collection` (empty marketplace tables behave identically to a never-refreshed state).

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
  category_id    TEXT NOT NULL,    -- shop's id, e.g. '1000676'
  category_path  TEXT NOT NULL,    -- e.g. '/nl-NL/c/rise-of-the-floodborn/1000676'
  PRIMARY KEY (marketplace_id, set_code)
);

CREATE TABLE marketplace_listings (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  marketplace_id  INTEGER NOT NULL REFERENCES marketplaces(id),
  external_id     TEXT NOT NULL,
  card_id         TEXT REFERENCES cards(card_id),  -- nullable: unmatched listings kept for diagnostics
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
  status           TEXT NOT NULL    -- 'running' | 'ok' | 'partial' | 'failed'
);
```

**Bootstrap.** Migration 007 inserts the Bazaar marketplace row. The 11 `(set_code, category_id)` mappings live in `data/bazaarofmagic_set_map.toml` (committed to repo) and are upserted into `marketplace_set_categories` on every refresh — so adding a new set is a one-line TOML edit, no migration needed.

**`card_id` is nullable.** Bazaar lists oversized promos and sealed bundles that don't exist in our catalog. Storing them with `card_id = NULL` (instead of dropping silently) lets `lorscan marketplaces status` show "X listings unmatched" — early warning if Bazaar changes their title format and matching breaks for thousands of cards.

## Bazaar crawl

Per enabled set:

1. Walk listing pages: `GET {base_url}{category_path}?page=N&items=24`. Parse cards (URL, title, price). Stop when a page returns no products.
2. For each product URL, `GET` the detail page. Parse:
   - **`collector_number`** ← regex `#(\d+)` on the product title.
   - **`finish`** ← parens suffix in title: `(foil)` → `foil`, `(cold foil)` → `cold_foil`, otherwise `regular`.
   - **`in_stock`** ← Dutch text: `Op voorraad` → true, `Uitverkocht` → false.
3. Yield a `Listing` per product.

**Politeness.**
- 4 concurrent requests per host (`httpx.Limits` + `asyncio.Semaphore`).
- 200 ms delay between batches.
- User-Agent: `lorscan/<version> (+https://github.com/ityou-tech/lorscan)`.
- `robots.txt` fetched once per sweep and respected.

**Failure handling.**
- Per-listing parser exception: counted, not fatal; sweep continues.
- HTTP 5xx / timeout: retry once after 2 s backoff.
- Persistent per-set failure: sweep status becomes `partial`, other sets still attempted.
- Whole-sweep crash: `marketplace_sweeps` row remains `running` so the next `status` call can spot orphaned sweeps.

**Estimated cost.** ~5500 product detail fetches per full sweep across 11 sets. At 4-concurrent + 200 ms inter-batch delay, ~10–15 minutes wall time. Acceptable for a manual command.

## Matching — strict v1

Resolver in `matching.py`:

```python
def resolve(
    db: Database,
    *,
    set_code: str,
    collector_number: str | None,
) -> str | None:
    """Return card_id for a (set_code, collector_number) pair, or None."""
```

Direct SQL lookup against `cards` table. No fuzzy logic, no name comparison, no ambiguity handling — if collector_number is missing or no row matches, return `None` and the listing is stored with `card_id = NULL`.

## `/collection` UI changes

### Page header gains:

- **`X cards needed`** meta-stat (computed as `total_catalog_cards - distinct_owned`).
- **`Y sets unfinished`** meta-stat (sets with `owned_count < total`).
- **`Marketplace data refreshed N days ago`** sub-line, sourced from the most recent successful `marketplace_sweeps` row. Hidden if no sweep has run yet, with a tooltip pointing to the CLI command.
- **`📋 Copy full want-list`** button (ported verbatim from `/missing`).

### "Closest to complete" strip

Ported verbatim from `/missing`. Top 3 sets in the 50–99% completion range, anchored above the binder shelf. Hidden when no set qualifies.

### Per-binder header

Existing `binder-nav-tab` gains a `Z missing` count alongside the current `X/Y owned`.

### Empty-pocket badges

Each empty pocket on `/collection` (a card the user does not own) gains a small badge:

```
€4,00 · Bazaar
```

The badge is a link that opens the product detail page in a new tab. Sourced from the cheapest in-stock listing per `card_id` across all enabled marketplaces. No badge if no in-stock listing matches.

**Data flow.** `_build_binders()` in `app/routes/collection.py` adds a single extra query before the per-set loop:

```sql
SELECT card_id, marketplace_id, MIN(price_cents) AS price_cents,
       url, currency
FROM marketplace_listings
WHERE in_stock = 1 AND card_id IS NOT NULL
GROUP BY card_id;
```

Result is a `dict[str, BadgeData]` passed into the template context. Each empty pocket looks up its `card_id` and renders the badge if present. No N+1 queries, no per-pocket fetches.

### Per-binder copy-want-list button

Already lives in `_partials/binder.html` behind the `mode == 'missing'` flag — moved to always-on (or behind a new `show_want_buttons` flag). When clicked, copies the missing cards in that binder as plain text:

```
ROF 12 Mickey Mouse - Brave Little Tailor
ROF 42 Donald Duck - Buccaneer
...
```

## `/missing` removal

Delete:
- `src/lorscan/app/templates/missing/` directory and its contents.
- `missing_index` route handler in `src/lorscan/app/routes/collection.py`.
- `<a href="/missing">Missing</a>` nav link in `src/lorscan/app/templates/base.html`.
- Tests targeting `/missing` (in `tests/integration/` and possibly `tests/unit/`).
- The `mode == 'missing'` branch in `_partials/binder.html`.

`/missing` becomes a 404. No redirect (per user preference — clean removal).

## Failure modes / degradation

| Failure | Behavior |
|---|---|
| Migration 007 fails | `/collection` renders without badges (empty marketplace tables = same outcome). |
| No sweep has run yet | No badges, no "refreshed" timestamp. README points the user at `lorscan marketplaces refresh`. |
| Sweep crashes mid-run | `marketplace_sweeps` row stays `running`. Next `status` call surfaces the orphan. Listings table is upserted incrementally so partial data is still useful. |
| Bazaar returns 5xx for a whole set | That set's previous listings stay in DB (not wiped). Sweep marked `partial`. Other sets still refreshed. |
| Bazaar HTML format changes | Unmatched count spikes. `status` shows it. Badges quietly thin out. No crash. |

## Testing

**Unit:**
- `tests/unit/services/marketplaces/test_bazaarofmagic_parser.py` — golden-file HTML at `tests/fixtures/marketplaces/bazaarofmagic/{listing.html, detail.html}` parsed into expected `Listing` dataclasses.
- `tests/unit/services/marketplaces/test_matching.py` — DB fixture; verify hit, miss, missing-collector-number cases.

**Integration:**
- `tests/integration/test_marketplace_sweep.py` — sweep orchestrator against `respx`-mocked HTTP. Covers happy path + per-set partial failure + parser error counting.

**Manual smoke:**
- `lorscan marketplaces refresh --dry-run --shop bazaarofmagic --set ROF` — runs the crawl, prints what would be written without touching DB.

No live HTTP exercised in CI.

## Build sequence

1. Migration `007_marketplaces.sql` + `data/bazaarofmagic_set_map.toml` + DB upserts in `storage/db.py`.
2. `services/marketplaces/base.py` — `ShopAdapter` Protocol, `Listing` dataclass, sweep orchestrator skeleton.
3. `services/marketplaces/bazaarofmagic.py` — listing-page walker + detail-page parser.
4. `services/marketplaces/matching.py` — strict resolver.
5. `services/marketplaces/storage.py` + sweep orchestrator + CLI commands (`refresh`, `status`).
6. Wire `/collection` route: add badge query, attach to template context.
7. Update `/collection` template + `_partials/binder.html`: render badges, port `/missing` features (header stats, closest-strip, copy-want buttons, refreshed-at line).
8. Delete `/missing` (route, template dir, nav link, tests, partial branch).
9. Tests + manual smoke run.
10. README: document `lorscan marketplaces refresh` and the `data/bazaarofmagic_set_map.toml` extension procedure for new sets.
