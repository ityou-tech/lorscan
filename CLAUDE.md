# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`lorscan` is a local Disney Lorcana TCG collection manager. Photos of binder pages are recognized by **local CLIP embeddings** (OpenCLIP ViT-B-32) against a catalog synced from `lorcanajson.org`. Fully offline after one-time setup. Python 3.12+, FastAPI, SQLite, `uv` for package management.

## Common commands

```bash
uv sync                                    # install / update deps
uv run pytest                              # run full suite
uv run pytest tests/unit/test_smoke.py     # one file
uv run pytest -k "buy_links"               # by name expression
uv run pytest -m live --runlive            # live tests hit real APIs (marker defined; opt-in)
uv run ruff check src tests                # lint
uv run ruff format src tests               # format
uv run lorscan serve                       # web UI on :8000, auto-reload on
uv run lorscan sync-catalog                # refresh card DB from LorcanaJSON
uv run lorscan index-images                # rebuild CLIP embeddings (~1-2 min on Apple Silicon)
uv run lorscan scan path/to/photo.jpg      # CLI scan
```

`pytest` runs in `asyncio_mode = "auto"` — `async def test_*` works without decorators.

## Architecture

The `lorscan` package is layered. Cross-file invariants that aren't visible from a single file:

### Storage is a single chokepoint

**All SQL lives behind `storage/db.py`.** Services and routes call methods on `Database` and receive typed domain objects from `storage/models.py` (`Card`, `CardSet`, `CollectionItem`, `Binder`, ...). Never write raw SQL outside that module — if you need a new query, add a method.

Migrations are forward-only `.sql` files in `storage/migrations/`, applied in alphabetical order by `Database.migrate()` via `importlib.resources`. They are tracked in a `schema_migrations` table; a failed `executescript` does **not** mark the version applied, so it retries on next boot. To add a migration: drop `NNN_name.sql` into the migrations folder — the next `migrate()` picks it up. Tests use an in-memory SQLite via the `db` pytest fixture in `tests/conftest.py`.

### Card identity is `<SET>-<NUMBER>`

The composite `card_id` (e.g. `TFC-001`) is the primary key for `cards` and is referenced from `collection_items`, `scan_results`, and the CLIP embeddings file. **Casing is load-bearing** — migration 009 normalized the catalog to uppercase set codes; new code should preserve that.

### Two set-code namespaces

- **lorscan internal**: 3-letter codes (`TFC`, `ROF`, `ITI`, ...) — see README's set-codes table.
- **LorcanaJSON upstream**: numeric (`"1"`, `"2"`, ..., `"Q1"` for Quests).

The bridge is `services/lorcana_json/set_codes.py::LORCANA_JSON_SET_CODE_MAP`. **When a new Lorcana set drops, update this map AND the README's set-codes table.** Cards with an unknown numeric set are skipped (counted in `unknown_sets_skipped`) rather than crashing the sync.

### Recognition pipeline

1. `services/image_cache.py` — async downloader for catalog images. User overrides at `~/.lorscan/overrides/<card_id>.<ext>` win over upstream URLs.
2. `services/embeddings.py` — OpenCLIP wrapper + `CardImageIndex`, persisted as 512-dim L2-normalized vectors at `~/.lorscan/embeddings.npz` (~5 MB for ~2300 cards).
3. `services/visual_scan.py` — tiles a binder page into 9 cells, embeds, nearest-neighbor lookup. Confidence: `≥0.85` high, `≥0.70` medium, `<0.70` low. Uses `_four_rotations` because corner ordering can't be inferred reliably — let the catalog match itself vote.
4. `services/card_detection.py` — optional pre-scan card-boundary warp (Canny + contour quad).
5. `services/scan_result.py` — `ParsedCard`, `ParsedScan`, `MatchResult` dataclasses returned across layers.

The `lorscan diag` subcommand exists for debugging this pipeline: it dumps edge maps, contour overlays, and CLIP top-5 with vs. without warping for a single photo.

### Web UI

`app/main.py` is a FastAPI factory consumed by `uvicorn.run("lorscan.app.main:create_app", factory=True)`. Routes live in `app/routes/` (one file per page: `scan.py`, `collection.py`); Jinja templates in `app/templates/` (page-specific subfolders + `_partials/` for shared chunks); static assets under `app/static/`.

### Config + data dir

`Config` (frozen dataclass) is loaded by `config.load_config()` from `~/.lorscan/config.toml` with env-var overrides (`LORSCAN_DATA_DIR`, `LORSCAN_MODEL`, `ANTHROPIC_API_KEY`). All on-disk state lives under one configurable root:

- `~/.lorscan/lorscan.db` — SQLite catalog + collection
- `~/.lorscan/cache/images/` — downloaded card art
- `~/.lorscan/embeddings.npz` — CLIP index
- `~/.lorscan/overrides/<card_id>.<ext>` — user image overrides (survive cache wipes)
- `~/.lorscan/photos/` — saved scan input photos

Tests use the `tmp_data_dir` fixture (in `tests/conftest.py`) which sets `LORSCAN_DATA_DIR` to a temp path via `monkeypatch`.

## Conventions

- **Test markers**: the `live` marker (declared in `pyproject.toml`) is for tests that hit real external APIs. Default suite skips them.
- **Commit/PR style**: conventional-commit prefixes (`feat(scope): ...`, `fix(scope): ...`); see recent `git log`.
- **Buy-link filter overrides**: extra TOML keys flow through to URLs untouched, so adding a new Cardmarket filter usually needs no Python change — see `services/buy_links.py` and `~/.lorscan/config.toml`'s `[buy_links.cardmarket]` section.
- **Ruff**: target `py312`, line length 100, rules `E F I B UP N SIM`, ignores `E501`.

## Self-hosting

Two paths, both documented in `README.md` and `docs/deploy/macmini.md`:

- **Mac autostart**: `./deploy/macmini/install.sh` (launchd plist).
- **Docker / Synology**: `docker compose up -d --build`. Image installs CPU-only PyTorch (~800 MB instead of CUDA ~3 GB), caps OMP/MKL threads to 2, mounts `/data` for state.

## Gotchas

- `lorscan index-images` must be re-run after `sync-catalog` when new sets land — the embeddings file is otherwise stale.
- A LorcanaJSON image URL that 404s gets logged and the card is skipped from the index. Drop a manual file at `~/.lorscan/overrides/<card_id>.<ext>` to include it; remove the override once upstream is fixed (overrides suppress the upstream fetch entirely).
