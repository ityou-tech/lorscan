# lorscan

Local Disney Lorcana TCG collection manager. Photographs of binder pages
go in via the CLI or web UI; **local CLIP embeddings** identify each card
visually against a catalog synced from `lorcana-api.com`. Fully offline
after the one-time setup — no API keys, no rate limits, no cost.

> **Status:** Plan 1 + Plan 2 MVP + Phase A (CLIP recognition) — fast
> local scanning, web UI, scan persistence, /collection, /missing,
> accept-into-collection workflow.

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

After `sync-catalog`, the local DB carries the canonical 3-letter set codes:

| Code | Name |
| ---- | ---- |
| TFC | The First Chapter |
| ROF | Rise of the Floodborn |
| ITI | Into the Inklands |
| URS | Ursula's Return |
| SSK | Shimmering Skies |
| ARI | Archazia's Island |
| ROJ | Reign of Jafar |
| FAB | Fabled |
| WHI | Whisperwood |
| WIN | Winter |
| AZS | Azurite Sea |

(Exact list depends on what `lorcana-api.com` currently exposes.)

If you mistype a set code, `lorscan scan` fails fast with a "Did you
mean: …?" hint based on what's actually in your catalog.

### Manual image overrides

The upstream catalog (`lorcana-api.com`) occasionally hands out image
URLs whose content-hash 404s on Ravensburger's CDN — a publisher-side
bug that re-syncing won't fix. Without an image, `index-images` skips
the card and any binder slot containing it gets misclassified as its
nearest catalog neighbor in art space rather than reported as
un-matchable.

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

`uv run lorscan serve` opens the local UI on port 8000. Three pages:

- **Scan** — upload a photo, pick a set from a dropdown of friendly names,
  see the per-cell recognition + match table inline. Recent scans list
  underneath, click any to revisit.
- **Collection** — every card you own with quantity, finish, set, number.
- **Missing** — per-set progress bars + collapsible lists of cards you
  don't have yet.

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
`lorcana-api.com`, runs each through OpenCLIP ViT-B-32, and saves a
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

## Development

```bash
uv sync
uv run pytest          # 44 tests
uv run ruff check src tests
uv run lorscan serve   # auto-reload is on by default
```

Project structure:

```
src/lorscan/
├── cli.py             # entry point (scan, serve, sync-catalog, index-images, version)
├── config.py          # TOML + env-var loader
├── app/               # FastAPI web UI
│   ├── main.py
│   ├── routes/scan.py, collection.py
│   ├── templates/
│   └── static/
├── services/
│   ├── catalog.py     # lorcana-api.com sync
│   ├── photos.py      # hash, save, HEIC→JPEG transcode
│   ├── embeddings.py  # OpenCLIP wrapper + CardImageIndex
│   ├── image_cache.py # async catalog-image downloader
│   ├── visual_scan.py # tile-and-CLIP scanner
│   ├── scan_result.py # ParsedCard, ParsedScan, MatchResult dataclasses
│   └── marketplaces/  # marketplace stock scraping (Plan 3)
│       ├── base.py            # ShopAdapter Protocol + Listing dataclass
│       ├── bazaarofmagic.py   # Bazaar adapter (parser + crawler)
│       ├── matching.py        # strict (set,collector) → card_id
│       ├── orchestrator.py    # run_sweep
│       └── seed.py            # TOML loader for per-set categories
└── storage/
    ├── db.py          # SQLite wrapper (only place SQL lives)
    ├── models.py      # CardSet, Card, CollectionItem, Binder
    └── migrations/    # 001-004 SQL migrations

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
