# lorscan

Local Disney Lorcana TCG collection manager. Photographs of binder pages
go in via the CLI or web UI; Claude Opus 4.7 vision identifies the cards;
matches against a local catalog synced from `lorcana-api.com`. Built to run
on a Max-plan subscription via the Claude Code CLI — no separate API
credits required.

> **Status:** Plan 1 + Plan 2 MVP — recognition pipeline, web UI, scan
> persistence, /collection, /missing, accept-into-collection workflow.

---

## Setup

```bash
# Clone + install
git clone https://github.com/ityou-tech/lorscan.git
cd lorscan
uv sync

# One-time auth (Max plan via Claude Code OAuth — keeps the keychain)
claude setup-token

# Initial catalog sync (~2300 cards across 11 sets, takes ~10s)
uv run lorscan sync-catalog
```

That's it. Nothing else to configure.

---

## CLI

```bash
# Identify cards in a photo
uv run lorscan scan path/to/binder-page.jpg

# Restrict matching to a single Lorcana set (recommended)
uv run lorscan scan path/to/binder-page.jpg --set ROF

# Refresh the local catalog
uv run lorscan sync-catalog

# Run the web UI on http://localhost:8000
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

## How auth works

lorscan invokes the `claude` CLI (Claude Code) as a subprocess in
headless print mode (`claude -p ... --output-format json`). The CLI
handles credential discovery — keychain (from `claude setup-token`), env
vars, then `ANTHROPIC_API_KEY`. lorscan never touches your token
directly.

If you don't have a Max subscription, you can also set
`ANTHROPIC_API_KEY` with a regular console.anthropic.com key — the
CLI uses that automatically.

---

## Development

```bash
uv sync
uv run pytest          # 62 tests + 1 snapshot
uv run ruff check src tests
uv run lorscan serve --reload   # dev mode with auto-reload
```

Project structure:

```
src/lorscan/
├── cli.py             # `lorscan` entry point (scan, serve, sync-catalog, version)
├── config.py          # TOML + env-var loader (auth optional)
├── app/               # FastAPI web UI
│   ├── main.py
│   ├── routes/scan.py, collection.py
│   ├── templates/
│   └── static/
├── services/
│   ├── catalog.py     # lorcana-api.com sync
│   ├── photos.py      # hash, save, HEIC→JPEG transcode
│   ├── matching.py    # suffix-aware catalog matching
│   └── recognition/
│       ├── prompt.py  # cached system prompt
│       ├── parser.py  # strict JSON parser w/ fence + prose tolerance
│       └── client.py  # `claude` CLI subprocess call
└── storage/
    ├── db.py          # SQLite wrapper (only place SQL lives)
    ├── models.py      # CardSet, Card, CollectionItem, Binder
    └── migrations/    # 001-004 SQL migrations
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
