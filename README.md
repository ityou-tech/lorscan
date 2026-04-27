# lorscan

Local Disney Lorcana TCG collection manager. Photographs of binder pages
go in via the CLI or web UI; **local CLIP embeddings** identify each card
visually against a catalog synced from `lorcanajson.org`. Fully offline
after the one-time setup — no API keys, no rate limits, no cost.

> **Status:** Plan 1 + Plan 2 MVP + Phase A (CLIP recognition) + Plan 3
> (marketplace stock) — fast local scanning, web UI, scan persistence,
> /collection with marketplace badges, accept-into-collection workflow.

---

## Setup

```bash
# Clone + install
git clone https://github.com/ityou-tech/lorscan.git
cd lorscan
uv sync

# Initial catalog sync (~2300 cards across 11 sets, takes ~10s)
uv run lorscan sync-catalog

# Build the local CLIP image index (downloads catalog images + computes
# embeddings; ~1–2 minutes on Apple Silicon, fully offline thereafter)
uv run lorscan index-images
```

That's it. Nothing else to configure. No API keys, no auth.

---

## Self-hosting

Two supported deployment paths:

- **Mac (autostart)** — best for an always-on Mac mini or laptop on Apple Silicon. One command: `./deploy/macmini/install.sh`. See [docs/deploy/macmini.md](docs/deploy/macmini.md).
- **Docker / Synology** — containerized build for any Linux host or Synology NAS with Container Manager. `docker compose up -d --build` from the repo root.

---

## CLI

```bash
# Identify cards in a photo (local CLIP, ~1 second)
uv run lorscan scan path/to/binder-page.jpg

# Refresh the local catalog
uv run lorscan sync-catalog

# Rebuild the CLIP index (run after sync-catalog adds new sets)
uv run lorscan index-images

# Run the web UI on http://localhost:8000 (auto-reload on by default)
uv run lorscan serve
```

### Set codes

After `sync-catalog`, the local DB carries the canonical 3-letter set
codes in official Ravensburger numeric order:

| #  | Code | Name                  |
| -- | ---- | --------------------- |
| 1  | TFC  | The First Chapter     |
| 2  | ROF  | Rise of the Floodborn |
| 3  | ITI  | Into the Inklands     |
| 4  | URS  | Ursula's Return       |
| 5  | SSK  | Shimmering Skies      |
| 6  | AZS  | Azurite Sea           |
| 7  | ARI  | Archazia's Island     |
| 8  | ROJ  | Reign of Jafar        |
| 9  | FAB  | Fabled                |
| 10 | WHI  | Whispers in the Well  |
| 11 | WIN  | Winterspell           |
| 12 | WUN  | Wilds Unknown         |
| Q1 | Q1   | Illumineer's Quest    |

Each main set ships ~204 numbered cards plus higher-numbered enchanteds
(typically 205-223), iconics, and a handful of promos with their own
numbering. `lorscan` imports all of them — when a "missing" pocket on
`/collection` shows an enchanted, it's just another collector number to
hunt down, treated identically to a common.

(Exact list depends on what `lorcanajson.org` currently exposes.)

If you mistype a set code, `lorscan scan` fails fast with a "Did you
mean: …?" hint based on what's actually in your catalog.

### Manual image overrides

The upstream catalog occasionally hands out image URLs whose
content-hash 404s on Ravensburger's CDN — a publisher-side bug that
re-syncing won't fix. Since the LorcanaJSON migration (April 2026) the
URLs come from the official Lorcana app data feed and the workaround is
expected to be needed less often, but the gap can still appear for
brand-new releases. Without an image, `index-images` skips the card and
any binder slot containing it gets misclassified as its nearest catalog
neighbor in art space rather than reported as un-matchable.

To plug the gap, drop a replacement image at:

```
~/.lorscan/overrides/<card_id>.<ext>     # .jpg .jpeg .png .webp .avif
```

`<card_id>` is the `<SET>-<NUMBER>` form printed in the warning during
`lorscan index-images` (e.g. `WHI-102.jpg`). Overrides win over both the
upstream URL and any previously-cached download, and they live outside
the `cache/` subtree so a cache wipe won't nuke them.

[Lorcast](https://lorcast.com/) is a useful third-party catalog when
you need a working image — its API at `https://api.lorcast.com/v0/cards/{set_num}/{collector_num}`
returns AVIF URLs that Pillow 11+ can decode directly.

---

## Web UI

`uv run lorscan serve` opens the local UI on port 8000. Two pages:

- **Scan** — upload a photo, pick a set from a dropdown of friendly names,
  see the per-cell recognition + match table inline. Recent scans list
  underneath, click any to revisit.
- **Collection** — every card per set with quantity controls on owned
  pockets and "+ Add" / "€X · Bazaar" / `CM` / `CT` badges on missing
  pockets. Page header shows cards-needed, sets-unfinished, the
  marketplace refreshed-at line, and the "closest to complete"
  highlight strip. Per-binder and global "📋 Copy want-list" buttons.

After a scan finishes, the **Accept matched cards into collection**
button atomically increments quantities for every cell with a confirmed
catalog match. Re-applying a scan is a no-op (idempotent).

While a scan is running you'll see a full-page loading overlay with a
spinner and progress messages — the submit button is disabled so you
can't double-submit.

---

## Photo tips

The recognition pipeline is bottlenecked by photo quality at the
collector-number level (printed in tiny text at each card's bottom-left).

- **Closer crop**: fill the frame with the binder page; no margins.
- **Direct overhead angle**: avoid perspective.
- **Diffuse lighting**: side glare on plastic sleeves is the #1
  readability killer.
- **Skip sleeves if safe**: the plastic always degrades clarity.
- **Native phone resolution**: lorscan auto-transcodes HEIC → JPEG at
  quality 92 with no resize.

Even with collector numbers unreadable, the matcher uses cards' name +
your selected `--set` to resolve most cells. Cards with title-only
matches in the chosen set succeed; cards whose name appears more than
once in the set surface as `(ambiguous: N candidates)` for manual pick.

---

## How recognition works

`lorscan index-images` downloads every catalog card image from
`lorcanajson.org`, runs each through OpenCLIP ViT-B-32, and saves a
512-dim L2-normalized embedding per card to `~/.lorscan/embeddings.npz`
(~5MB for ~2300 cards).

At scan time, `lorscan` tiles your binder photo into 9 cells (with a
small inset to ignore sleeve edges), embeds each cell through the same
CLIP model, and finds the nearest neighbor in the catalog by cosine
similarity. ~500ms total per binder page on Apple Silicon. Confidence
scoring: similarity ≥ 0.85 → high, ≥ 0.70 → medium, < 0.70 → low.

Empty sleeves come back as `clip_low_confidence` because their
embeddings don't resemble any card.

---

## Marketplace stock

`lorscan` can scrape known card shops to surface "available to buy" data
on the empty pockets in `/collection`. Currently supports
[Bazaar of Magic](https://www.bazaarofmagic.eu).

```bash
uv run lorscan marketplaces refresh    # ~10–15 min full sweep
uv run lorscan marketplaces status     # last-sweep summary
```

Refresh whenever you want fresh prices — there is no background
scheduler. The page header on `/collection` shows when the data was
last refreshed.

### Adding new sets

To extend which Lorcana sets get scraped, edit
[`data/bazaarofmagic_set_map.toml`](data/bazaarofmagic_set_map.toml)
and add a new `[[set]]` block:

```toml
[[set]]
code = "AZS"
category_id = "1234567"   # from the URL on Bazaar's per-set page
category_path = "/nl-NL/c/azurite-sea/1234567"
```

The next `lorscan marketplaces refresh` upserts the new mapping
automatically. Sets not listed here are silently skipped.

### Limitations (v1)

- Strict matching only: a listing whose collector number is missing
  from the title is silently dropped. Most cleanly-listed shops (like
  Bazaar) hit ≈100% match rate; messier shops like eBay would need a
  fuzzy matcher (not yet built).
- Only Bazaar of Magic is supported. The `services/marketplaces/`
  scaffolding makes adding another shop straightforward — implement a
  new adapter that satisfies the `ShopAdapter` Protocol.
- Per-detail HTTP errors are silently dropped (counted in the sweep's
  `errors` total but no per-card visibility).

---

## Buy missing cards

Every card in the catalog carries direct links to its Cardmarket,
CardTrader, and TCGplayer product pages (sourced from LorcanaJSON's
`externalLinks` block). On `/collection`, empty pockets show small
`CM` / `CT` icons next to any Bazaar price badge — clicking opens the
marketplace product page with your preferred filters pre-applied. The
buy links coexist with the Bazaar badge rather than acting as a
fallback, so you can compare across marketplaces side-by-side.

The default Cardmarket filter set is tuned for a Netherlands-based
collector:

| Filter            | Default                 |
| ----------------- | ----------------------- |
| Seller country    | Netherlands (23)        |
| Seller reputation | Good and above (4)      |
| Language          | English (1)             |
| Min condition     | Excellent and above (3) |

Override any of these in `~/.lorscan/config.toml`:

```toml
[buy_links.cardmarket]
sellerCountry = [23, 5, 21]   # widen to NL + DE + BE
minCondition  = 2              # near-mint and above only
isFoil        = "Y"            # foils only
```

Pass a list to repeat a query parameter (Cardmarket honours repeated
`sellerCountry` and `language`). Any keys not in the default set
flow through to the URL untouched, so you can surface filters lorscan
doesn't default (`isReverseHolo`, `isAltered`, etc.).

---

## Development

```bash
uv sync
uv run pytest
uv run ruff check src tests
uv run lorscan serve   # auto-reload is on by default
```

Project structure:

```
src/lorscan/
├── cli.py             # entry point (scan, serve, sync-catalog, index-images, marketplaces, version)
├── config.py          # TOML + env-var loader
├── app/               # FastAPI web UI
│   ├── main.py
│   ├── routes/scan.py, collection.py
│   ├── templates/
│   └── static/
├── services/
│   ├── catalog.py            # LorcanaJSON sync (sets + cards + external links)
│   ├── lorcana_json/         # LorcanaJSON-specific fetcher, mapper, set-code map
│   ├── buy_links.py          # Cardmarket/CardTrader URL builders
│   ├── photos.py             # hash, save, HEIC→JPEG transcode
│   ├── embeddings.py         # OpenCLIP wrapper + CardImageIndex
│   ├── image_cache.py        # async catalog-image downloader
│   ├── visual_scan.py        # tile-and-CLIP scanner
│   ├── scan_result.py        # ParsedCard, ParsedScan, MatchResult dataclasses
│   └── marketplaces/         # marketplace stock scraping (Plan 3)
│       ├── base.py            # ShopAdapter Protocol + Listing dataclass
│       ├── bazaarofmagic.py   # Bazaar adapter (parser + crawler)
│       ├── matching.py        # strict (set,collector) → card_id
│       ├── orchestrator.py    # run_sweep
│       └── seed.py            # TOML loader for per-set categories
└── storage/
    ├── db.py          # SQLite wrapper (only place SQL lives)
    ├── models.py      # CardSet, Card, CollectionItem, Binder
    └── migrations/    # 001-008 SQL migrations

data/                  # bundled non-Python data
└── bazaarofmagic_set_map.toml
```

---

## Roadmap

See `docs/superpowers/notes/TODO.md` for the running list. Highlights:

- **Tile mode**: split a 3×3 photo into 9 single-card scans for
  legible collector numbers (~9× pixels per card).
- **3D page-flip binder visualization**: per the design spec §6.
- **Photo-quality doctor**: pre-flight readability check.
- **Background scanning** with progress polling.

---

## License

Private. (Plan 3 — pre-release polish.)
