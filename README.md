# lorscan

Local Disney Lorcana TCG collection manager. Photographs of binder pages
go in via the CLI or web UI; **local CLIP embeddings** identify each card
visually against a catalog synced from `lorcanajson.org`. Fully offline
after the one-time setup — no API keys, no rate limits, no cost.

> **Status:** Plan 1 + Plan 2 MVP + Phase A (CLIP recognition) — fast
> local scanning, web UI, scan persistence, /collection with Cardmarket
> and CardTrader buy-link icons, accept-into-collection workflow.

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
| 13 | AOV  | Attack of the Vine    |
| 14 | HYC  | Hyperia City          |
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

The LorcanaJSON migration (April 2026) sources image URLs from the
official Lorcana app data feed, which currently has 100% coverage on
released sets — the manual-override workaround is **typically not
needed** any more. The mechanism is kept as a fallback for the rare
case where Ravensburger's CDN drops a hash on a brand-new release.

If `lorscan index-images` reports `Skipping card <SET>-<NUM>` for a
card you care about, drop a replacement image at:

```
~/.lorscan/overrides/<card_id>.<ext>     # .jpg .jpeg .png .webp .avif
```

`<card_id>` is the `<SET>-<NUMBER>` form printed in the warning (e.g.
`WHI-102.jpg`). Overrides win over both the upstream URL and any
previously-cached download, and they live outside the `cache/` subtree
so a cache wipe won't nuke them. Note that an override *suppresses* the
upstream fetch entirely, so once Ravensburger publishes a working URL
for the card you'll want to remove the override to pick up the (often
higher-resolution) official image.

[Lorcast](https://lorcast.com/) remains a useful third-party catalog
when LorcanaJSON itself is missing an image — its API at
`https://api.lorcast.com/v0/cards/{set_num}/{collector_num}` returns
AVIF URLs that Pillow 11+ can decode directly.

---

## Web UI

`uv run lorscan serve` opens the local UI on port 8000. Two pages:

- **Scan** — upload a photo, pick a set from a dropdown of friendly names,
  see the per-cell recognition + match table inline. Recent scans list
  underneath, click any to revisit.
- **Collection** — every card per set with quantity controls on owned
  pockets and "+ Add" / `CM` / `CT` icons on missing pockets. Page
  header shows cards-needed, sets-unfinished, and the "closest to
  complete" highlight strip. Per-binder and global "📋 Copy want-list"
  buttons.

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

## Buy missing cards

Every card in the catalog carries direct links to its Cardmarket,
CardTrader, and TCGplayer product pages (sourced from LorcanaJSON's
`externalLinks` block). On `/collection`, empty pockets show small
`CM` / `CT` icons — clicking opens the marketplace product page with
your preferred filters pre-applied.

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

CardTrader uses a separate filter section with its own vocabulary
(extracted from their card-page `filter.json` schema):

| Filter      | Type    | Values |
| ----------- | ------- | ------ |
| `language`  | string  | `en`, `fr`, `it`, `de`, `es`, `jp`, `zh-CN` |
| `condition` | string  | `Near Mint`, `Slightly Played`, `Moderately Played`, `Played`, `Poor` |
| `foil`      | boolean | `true` / `false` |
| `signed`    | boolean | `true` / `false` |
| `altered`   | boolean | `true` / `false` |

Default ships `language = "en"`. Override or extend in
`~/.lorscan/config.toml`:

```toml
[buy_links.cardtrader]
language  = "en"
condition = "Near Mint"
foil      = false
```

**Seller country on CardTrader**: their "Same Country" toggle is
applied **client-side** off the country in your CardTrader profile —
not via URL params — so lorscan can't pre-filter to NL sellers the
way it can on Cardmarket. Set your country in your CardTrader
account once and stay logged in when clicking the buy-link if you
want country-locked listings. Unlike Cardmarket, CardTrader's
condition filter is also single-value (not a min-floor), so
`condition = "Near Mint"` shows only Near Mint, not "NM and above".

### Bulk buying via Cardmarket

Each binder on `/collection` has a "🛒 Cardmarket" button next to its
plain copy button. Clicking it copies that set's missing cards to the
clipboard in Cardmarket's import format and shows a toast with the
next-step instructions and a link to
[Cardmarket's Wants page](https://www.cardmarket.com/en/Lorcana/Wants).
The pasted lines look like:

```
1x Elsa - Spirit of Winter (V.1) (The First Chapter)
1x Elsa - Spirit of Winter (V.2) (The First Chapter)
1x Sisu - Divine Water Dragon (V.1) (Rise of the Floodborn)
…
```

This is Cardmarket's documented deck-list format. `(V.N)` selects the
printing within a set — V.1 is the standard rarity, V.2 is the
Enchanted reprint, V.3 is the Iconic/Infinity tier. `(Set Name)`
scopes the lookup to the right expansion so a TFC card doesn't match
a Fabled reprint of the same name.

Why per-binder and not a single full-collection button? **Cardmarket
caps a wantlist at ~150 entries**, so a full-collection dump would
partial-fail on most collections. One binder per wantlist (or per
import into the same wantlist) keeps every paste under the cap.

Cardmarket models wantlists as named, persistent containers, so the
first run has a one-time setup. After that, every future bulk-buy
click reuses the same wantlist:

1. **First time only** — on Cardmarket's Wants page, give your list
   a name (e.g. "Lorcana Wants") and click **Add list**.
2. Open that wantlist and click **+ Add Deck List** (Cardmarket's
   paste-multi-card entry point). Paste from the clipboard, save.
3. Click **Sellers with the most cards** at the bottom of the
   wantlist. Cardmarket runs its Shopping Wizard against your list
   and shows the seller (or small set of sellers) carrying the most
   cards — that's the bulk-buy optimisation, computed server-side.

Repeat uses: open your existing wantlist, click **+ Add Deck List**
again, paste the new clipboard contents, save, re-run "Sellers with
the most cards".

**Two quirks worth knowing:**

- **Multi-printing cards are emitted as separate `(V.N)` lines.**
  *Belle - Strange but Special* exists in TFC as a Legendary
  (#142, V.1) and an Enchanted (#214, V.2). The clipboard contains
  both lines explicitly — Cardmarket adds them as two distinct rows
  on your wantlist instead of merging into one row with quantity 2.
- **Default condition floor is `≥ PO` (Poor — any condition).** New
  wantlist rows accept any condition. Click the row's edit pencil to
  bump it to `≥ NM` or `≥ EX` if you want Shopping Wizard to filter
  on condition.

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
├── cli.py             # entry point (scan, serve, sync-catalog, index-images, version)
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
│   └── scan_result.py        # ParsedCard, ParsedScan, MatchResult dataclasses
└── storage/
    ├── db.py          # SQLite wrapper (only place SQL lives)
    ├── models.py      # CardSet, Card, CollectionItem, Binder
    └── migrations/    # 001-011 SQL migrations
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
