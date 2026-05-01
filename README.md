<p align="center">
  <img src="docs/banner.png" alt="lorscan" width="720">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License">
  <img src="https://img.shields.io/badge/packaged%20with-uv-DE5FE9" alt="uv">
  <img src="https://img.shields.io/badge/lint-ruff-D7FF64?logo=ruff&logoColor=black" alt="Ruff">
  <img src="https://img.shields.io/badge/web-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
</p>

# lorscan

Local Lorcana collection manager. Take a photo of a binder page, get the
cards back. Recognition runs offline with OpenCLIP ViT-B-32 against a
catalog synced from [lorcanajson.org](https://lorcanajson.org).

## Setup

```bash
git clone https://github.com/ityou-tech/lorscana.git
cd lorscana
uv sync

uv run lorscan sync-catalog    # ~2,300 cards, ~10s
uv run lorscan index-images    # CLIP index, 1–2 min on Apple Silicon
```

The catalog sync and image index pull from `lorcanajson.org` over the
internet. After that, scanning is fully local — typically you run
`lorscan serve` on a Mac mini or Synology and reach the web UI over LAN.

## Self-hosting

- **Mac (autostart)** — `./deploy/macmini/install.sh`. Details in
  [docs/deploy/macmini.md](docs/deploy/macmini.md).
- **Docker / Synology** — `docker compose up -d --build` from the repo root.

## CLI

```bash
uv run lorscan scan path/to/binder-page.jpg   # identify cards (~1s)
uv run lorscan sync-catalog                   # refresh catalog
uv run lorscan index-images                   # rebuild CLIP index
uv run lorscan serve                          # web UI on :8000
uv run lorscan diag path/to/photo.jpg         # debug recognition
uv run lorscan version
```

`diag` dumps the edge map, contour overlay, and CLIP top-5 with vs.
without card-boundary warping. Useful when a photo is matching badly.

### Set codes

The local DB stores 3-letter codes in official release order:

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
| 13 | AOV  | Attack of the Vine    |
| 14 | HYC  | Hyperia City          |
| Q1 | Q1   | Illumineer's Quest    |

Each main set has ~204 numbered cards plus enchanteds (205–223), iconics,
and some promos. lorscan imports all of them, so an enchanted in a "missing"
pocket on `/collection` is just another card to track down.

(The exact list depends on what `lorcanajson.org` currently exposes.)

### Manual image overrides

Since the LorcanaJSON migration in April 2026, image URLs come from the
official Lorcana app data feed and coverage on released sets sits at 100%.
The override mechanism stays as a fallback for the rare CDN hash drop on
a brand-new set.

If `lorscan index-images` ends with a `warning: N image(s) failed to download`
block listing a card you care about, drop a replacement at:

```
~/.lorscan/overrides/<card_id>.<ext>     # .jpg .jpeg .png .webp .avif
```

`<card_id>` is the `<SET>-<NUMBER>` form printed in the warning (e.g.
`WHI-102.jpg`). Overrides win over the upstream URL and any cached download,
and live outside `cache/` so they survive cache wipes. An override suppresses
the upstream fetch entirely, so once Ravensburger publishes a working URL,
remove the override to pick up the (usually higher-resolution) official image.

[Lorcast](https://lorcast.com/) is a useful third-party catalog when
LorcanaJSON itself is missing an image. Their API at
`https://api.lorcast.com/v0/cards/{set_num}/{collector_num}` returns AVIF
URLs that Pillow 11+ decodes directly.

## Web UI

`uv run lorscan serve` opens the UI on port 8000. Two pages:

- **Scan** — upload a photo, optionally pick a set from the dropdown, see
  per-cell recognition inline. Recent scans are listed underneath, click
  one to revisit.
- **Collection** — every card per set, with quantity controls on owned
  pockets and "+ Add" / `CM` / `CT` icons on missing pockets. The header
  shows cards-needed, sets-unfinished, and a "closest to complete" strip.
  Per-binder and global "📋 Copy want-list" buttons.

After a scan, **Accept matched cards into collection** atomically bumps
quantities for every confirmed match. Re-applying the same scan is a no-op.

A scan-in-progress overlay disables the submit button so you can't
double-submit.

## Photo tips

The pipeline cares about how clearly CLIP can see the card art:

- Fill the frame, no margins around the page.
- Direct overhead angle, no perspective.
- Diffuse lighting. Side glare on plastic sleeves is the #1 readability killer.
- Skip sleeves when safe.
- Native phone resolution. lorscan auto-transcodes HEIC → JPEG at quality 92,
  no resize.

Recognition is purely visual (no OCR), so the **Restrict to set** dropdown
on `/scan` is the most useful knob you have. It narrows the catalog to one
expansion and removes most cross-set false positives.

## How recognition works

`lorscan index-images` runs every catalog image through OpenCLIP ViT-B-32
and saves a 512-dim L2-normalized embedding per card to
`~/.lorscan/embeddings.npz` (~5 MB for ~2,300 cards).

At scan time, lorscan tiles the photo into 9 cells (small inset to ignore
sleeve edges), embeds each cell, and finds the nearest neighbor by cosine
similarity. About 500 ms per binder page on Apple Silicon.

Confidence: ≥ 0.85 high, ≥ 0.70 medium, < 0.70 low. Empty sleeves come back
low-confidence because their embeddings don't match anything.

## Buy missing cards

Each catalog card carries Cardmarket, CardTrader, and TCGplayer product
links (sourced from LorcanaJSON's `externalLinks`). On `/collection`,
empty pockets show `CM` / `CT` icons that open the marketplace product page
with your filters pre-applied.

The default Cardmarket filter is set up for a Netherlands collector:

| Filter            | Default                 |
| ----------------- | ----------------------- |
| Seller country    | Netherlands (23)        |
| Seller reputation | Good and above (4)      |
| Language          | English (1)             |
| Min condition     | Excellent and above (3) |

Override in `~/.lorscan/config.toml`:

```toml
[buy_links.cardmarket]
sellerCountry = [23, 5, 21]   # NL + DE + BE
minCondition  = 2              # near-mint and above
isFoil        = "Y"            # foils only
```

A list value repeats the query parameter (Cardmarket honours repeated
`sellerCountry` and `language`). Keys not in the default set flow through
untouched, so filters lorscan doesn't expose by default
(`isReverseHolo`, `isAltered`, …) still work.

CardTrader uses its own filter vocabulary, taken from their card-page
`filter.json` schema:

| Filter      | Type    | Values |
| ----------- | ------- | ------ |
| `language`  | string  | `en`, `fr`, `it`, `de`, `es`, `jp`, `zh-CN` |
| `condition` | string  | `Near Mint`, `Slightly Played`, `Moderately Played`, `Played`, `Poor` |
| `foil`      | boolean | `true` / `false` |
| `signed`    | boolean | `true` / `false` |
| `altered`   | boolean | `true` / `false` |

Default is `language = "en"`. Override in `~/.lorscan/config.toml`:

```toml
[buy_links.cardtrader]
language  = "en"
condition = "Near Mint"
foil      = false
```

CardTrader's "Same Country" toggle is client-side, applied off your profile
country rather than via URL params, so lorscan can't pre-filter to NL
sellers. Set your country in your CardTrader account once and stay logged
in when clicking buy-links if you want country-locked listings. Their
condition filter is also single-value (not a min-floor), so
`condition = "Near Mint"` shows only Near Mint, not "NM and above".

### Bulk buying via Cardmarket

Each binder on `/collection` has a "🛒 Cardmarket" button next to its plain
copy button. Clicking copies that set's missing cards to the clipboard in
Cardmarket's deck-list format and shows a toast linking to
[Cardmarket's Wants page](https://www.cardmarket.com/en/Lorcana/Wants).
The pasted lines look like:

```
1x Elsa - Spirit of Winter (V.1) (The First Chapter)
1x Elsa - Spirit of Winter (V.2) (The First Chapter)
1x Sisu - Divine Water Dragon (V.1) (Rise of the Floodborn)
…
```

`(V.N)` selects the printing within a set: V.1 standard, V.2 Enchanted,
V.3 Iconic/Infinity. `(Set Name)` scopes the lookup to the right expansion
so a TFC card doesn't match a Fabled reprint of the same name.

It's per-binder rather than one full-collection button because Cardmarket
caps a wantlist at ~150 entries. One binder per wantlist (or per import
into the same wantlist) keeps every paste under the cap.

Cardmarket models wantlists as named, persistent containers, so the first
run has a one-time setup. After that, every bulk-buy click reuses the same
wantlist:

1. **First time only** — on Cardmarket's Wants page, name your list
   (e.g. "Lorcana Wants") and click **Add list**.
2. Open it, click **+ Add Deck List**, paste from the clipboard, save.
3. Click **Sellers with the most cards** at the bottom of the wantlist.
   Cardmarket runs Shopping Wizard and shows the seller (or small set
   of sellers) covering the most cards.

Repeat use: open the existing wantlist, **+ Add Deck List**, paste, save,
re-run **Sellers with the most cards**.

A couple of quirks:

- **Multi-printing cards become separate `(V.N)` lines.** *Belle - Strange
  but Special* exists in TFC as a Legendary (#142, V.1) and an Enchanted
  (#214, V.2). The clipboard contains both lines explicitly; Cardmarket
  adds them as two distinct rows instead of merging.
- **Default condition floor is `≥ PO` (Poor — any condition).** Click a
  row's edit pencil to bump it to `≥ NM` or `≥ EX` if you want Shopping
  Wizard to filter on condition.

## Development

```bash
uv sync
uv run pytest
uv run ruff check src tests
uv run lorscan serve
```

Project structure:

```
src/lorscan/
├── cli.py             # entry point (scan, serve, sync-catalog, index-images, diag, version)
├── config.py          # TOML + env-var loader
├── app/               # FastAPI web UI
│   ├── main.py
│   ├── routes/scan.py, collection.py
│   ├── templates/
│   └── static/
├── services/
│   ├── catalog.py            # LorcanaJSON sync (sets + cards + external links)
│   ├── lorcana_json/         # LorcanaJSON-specific fetcher, mapper, set-code map
│   ├── sets.py               # canonical Lorcana release order
│   ├── buy_links.py          # Cardmarket/CardTrader URL builders
│   ├── photos.py             # hash, save, HEIC→JPEG transcode
│   ├── embeddings.py         # OpenCLIP wrapper + CardImageIndex
│   ├── image_cache.py        # async catalog-image downloader
│   ├── card_detection.py     # Canny + contour card-boundary warp (used by `diag`)
│   ├── visual_scan.py        # tile-and-CLIP scanner
│   └── scan_result.py        # ParsedCard, ParsedScan, MatchResult dataclasses
└── storage/
    ├── db.py          # SQLite wrapper (only place SQL lives)
    ├── models.py      # CardSet, Card, CollectionItem, Binder
    └── migrations/    # 001-011 SQL migrations
```

## Roadmap

Tracked on [GitHub Issues](https://github.com/ityou-tech/lorscana/issues).

## License

MIT — see [LICENSE](LICENSE).
