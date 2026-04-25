# lorscan — Design Spec

**Date:** 2026-04-25
**Author:** Enri Peters (with Claude)
**Status:** Approved (brainstorming complete; ready for implementation planning)

---

## 1. Overview

`lorscan` is a **local Python web app** for managing a personal Disney Lorcana TCG collection. The user runs a small server on their Mac, opens `http://localhost:8000` in a browser, and works with their collection through a familiar three-page UI: **Scan**, **Collection**, **Missing**.

The defining capability is photo-based card recognition: the user uploads a photo of a binder page (typically 9 cards in a 3×3 grid), the app calls the **Anthropic Claude API** with the image, and Claude returns a structured JSON list of identified cards. The user then reviews the result on a staging page and explicitly accepts cards into the collection.

The collection is rendered as a **3D page-flipping binder** — every set, and any user-defined binder, is displayed as a sequence of 3×3 pages with skeuomorphic page-turn animation. Filled slots show your card; empty slots are visible gaps. The same component drives the Collection, Missing, and Reorganize views, providing a unified visual language across the app.

A secondary capability — **misplacement detection** — flags cards on a binder page that don't belong there (wrong set, wrong finish), giving the user a Reorganize queue they can work through to keep their physical binders tidy.

### 1.1 Goals (v1)
- Reliable identification of Lorcana cards from a 3×3 binder-page photo using Claude vision.
- A staging-area review flow that prevents wrong identifications from corrupting the collection.
- Persistent, content-addressed photo storage and full audit trail (request/response of every Claude call).
- Catalog of all Lorcana cards synced from `lorcana-api.com`, cached locally, refreshable on demand.
- Quantity tracking with finish (`regular` / `cold_foil` / `promo`) and free-text promo annotation.
- Suffix-aware collector numbers (`1a`, `1b`) for adventure sets and alt-arts.
- A 3D page-flip binder visualization for browsing the collection and missing cards.
- Misplacement detection with a Reorganize queue.
- Cost transparency (per-scan and monthly USD).

### 1.2 Non-goals (v1)
- **Marketplace integration** (Cardmarket, eBay) — deferred to a later milestone with its own spec.
- **Multi-user / hosted deployment** — local single-user only.
- **Mobile native app** — phone access via the responsive web UI is acceptable; no native app build.
- **Deck building** — out of scope; `lorscan` is collection management.
- **Card condition tracking** (NM/LP/MP/HP/DMG) — added later if requested; nullable column reserved.
- **Price / value tracking** — belongs to the marketplace milestone.
- **Browser-automated UI tests, accessibility audits** — manual smoke testing only in v1.
- **Database backups** — user responsibility; CLI helper deferred to v1.1.

### 1.3 Why these choices in one paragraph
A local Python web app with FastAPI + Jinja2 + HTMX + SQLite is the smallest credible stack that's still genuinely user-friendly. By using Claude's vision API for recognition, we avoid the entire ML/OCR/embedding pipeline that would otherwise dominate the project. By using `lorcana-api.com` for the master catalog, we avoid building or maintaining card data ourselves. By staging every scan for explicit user review, we eliminate the "error-prone — makes me start over" pain point that motivated the project. Everything else is supporting infrastructure.

---

## 2. Architecture

### 2.1 Stack
- **Backend:** Python 3.12+, FastAPI, Uvicorn, Jinja2, `anthropic` Python SDK.
- **Frontend:** Server-rendered HTML with HTMX for interactivity. Vanilla JS where needed for the 3D page-flip animation. No build pipeline. No npm.
- **Storage:** SQLite (single file via `sqlite3` standard library — no ORM in v1). Plain SQL migrations applied at startup.
- **Photo storage:** content-addressed files on disk under `~/.lorscan/photos/<sha256>.<ext>`. The original upload bytes are saved verbatim (the sha256 is computed over those exact bytes for dedupe). A normalized derivative is built only for the API request and is not persisted.
- **Catalog cache:** `~/.lorscan/cache/api/*.json`, refreshable.
- **Image cache:** `~/.lorscan/cache/images/<card_id>.webp` (catalog thumbnails downloaded on first browse).
- **Config:** `~/.lorscan/config.toml` for Anthropic API key and preferences.

### 2.2 Module layout
```
lorscan/
├── app/
│   ├── main.py                 # FastAPI app + lifespan (DB migrations, catalog sync check)
│   ├── routes/
│   │   ├── scan.py             # /scan, /scan/<id>, /scan/<id>/review
│   │   ├── collection.py       # /collection
│   │   ├── missing.py          # /missing
│   │   ├── binders.py          # /binders, /binder/<id>
│   │   ├── reorganize.py       # /reorganize
│   │   └── api.py              # JSON endpoints used by HTMX (POST /api/scan-results/<id>/decision, etc.)
│   ├── templates/              # Jinja2 templates
│   └── static/                 # CSS + small JS (binder page-flip animation)
├── services/
│   ├── recognition/            # Claude vision pipeline (split for testability)
│   │   ├── __init__.py
│   │   ├── prompt.py           # Builds the cached system prompt + per-scan user message
│   │   ├── client.py           # Calls the Anthropic SDK; budget guard; usage→cost
│   │   └── parser.py           # Strict JSON parsing of Claude responses
│   ├── catalog.py              # lorcana-api.com sync + local lookup
│   ├── collection.py           # Collection CRUD + accept/reject scan_results
│   ├── matching.py             # Suffix-aware card matching
│   ├── anomaly.py              # Misplacement detection (explicit + implicit)
│   ├── photos.py               # Hashing, saving original bytes, normalizing for API
│   └── cost.py                 # Token-usage → USD, monthly aggregation, budget guards
├── storage/
│   ├── db.py                   # Single Database class wrapping sqlite3
│   ├── migrations/             # 001_catalog.sql, 002_collection.sql, 003_scans.sql, 004_binders.sql
│   └── models.py               # Plain dataclasses for domain types
├── config.py                   # Reads ~/.lorscan/config.toml + env overrides
└── cli.py                      # `lorscan` entry point: serve | sync-catalog | backup
```

### 2.3 Layer rules
- **Routes are thin.** They validate input, call services, render templates. No business logic.
- **Services are pure.** They take inputs, call other services, return outputs. No HTTP awareness.
- **`storage/db.py` is the only place SQL lives.** Services receive typed domain objects; raw rows never escape.
- **`config.py` is the only place that reads env / TOML.** Services receive a config object.

### 2.4 Data layout on disk
```
~/.lorscan/
├── lorscan.db                  # SQLite, all relational data
├── config.toml                 # API key + preferences
├── photos/
│   └── <sha256>.<ext>          # original uploaded binder-page photos (extension preserved from upload)
└── cache/
    ├── api/                    # raw lorcana-api.com responses (offline fallback)
    └── images/<card_id>.webp   # catalog thumbnails
```

User data lives outside the project repo. The repo is the code; `~/.lorscan/` is the user's collection. This means `git clean -fdx` never destroys user data.

### 2.5 Why FastAPI + Jinja2 + HTMX (not React, Streamlit, or NiceGUI)
- **HTMX** gives drag-and-drop file upload, partial page updates, live grid edits — the things you actually want from a "user-friendly" web UI — without a JS build pipeline. ~50 lines of vanilla JS handles the 3D page-flip; everything else is server-rendered.
- **No ORM** because the schema is small (6 tables) and migrations are simple SQL. SQLAlchemy's session model has a learning surface that costs more than it saves at this scale. We can swap to it later if the schema explodes; the swap is one module.
- **Streamlit/Gradio** were ruled out because the binder visualization, multi-page navigation, and scan-review interactions hit their UX ceiling fast.
- **NiceGUI/Reflex** were ruled out because they're tied to a specific component model that's harder to extend than HTML/CSS.

---

## 3. Data Model

All schemas are plain SQLite. Migrations are forward-only in v1.

### 3.1 `sets` — synced from lorcana-api.com
```sql
CREATE TABLE sets (
  set_code     TEXT PRIMARY KEY,           -- e.g. "1", "TFC" — whatever the API uses
  name         TEXT NOT NULL,              -- "The First Chapter"
  released_on  DATE,
  total_cards  INTEGER NOT NULL,
  icon_url     TEXT,
  synced_at    DATETIME NOT NULL
);
```

### 3.2 `cards` — master catalog
```sql
CREATE TABLE cards (
  card_id          TEXT PRIMARY KEY,       -- stable id from API or hash
  set_code         TEXT NOT NULL REFERENCES sets(set_code),
  collector_number TEXT NOT NULL,
  -- Stored exactly as printed on the card, including any trailing letter
  -- suffix used in adventure sets and alt-arts ("1a", "127b").
  -- Treated as opaque text — no parsing, no normalization.
  name             TEXT NOT NULL,
  subtitle         TEXT,                   -- "Brave Little Tailor"
  rarity           TEXT NOT NULL,          -- Common / Uncommon / Rare / Super Rare / Legendary / Enchanted
  ink_color        TEXT,                   -- Amber / Amethyst / Emerald / Ruby / Sapphire / Steel
  cost             INTEGER,
  inkable          INTEGER,                -- 0/1
  card_type        TEXT,                   -- Character / Action / Item / Location / Song
  body_text        TEXT,
  image_url        TEXT,
  api_payload      TEXT NOT NULL,          -- full original JSON from API, for replay
  UNIQUE(set_code, collector_number)
);
CREATE INDEX cards_name_idx ON cards(name);
CREATE INDEX cards_set_idx  ON cards(set_code);
```

**Variant handling.** Enchanted cards have their own collector numbers above the set total (`213/204`) and are returned by the API as separate `cards` rows — no special schema needed. Unique promos (D23, store, etc.) are also separate `cards` rows in their own promo "sets". The only finish-as-metadata distinction (cold foil, stamped promo of an existing card) lives on `collection_items` (§3.3).

### 3.3 `collection_items` — the user's possessions
```sql
CREATE TABLE collection_items (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id       TEXT NOT NULL REFERENCES cards(card_id),
  finish        TEXT NOT NULL DEFAULT 'regular',
  -- 'regular' | 'cold_foil' | 'promo'
  -- Distinguishes finish OF THE SAME PRINTED CARD, not a different card.
  finish_label  TEXT,
  -- Free-text annotation for promo provenance: "League Q2 2024", "D23 2022".
  -- Optional. Only meaningful when finish = 'promo'.
  quantity      INTEGER NOT NULL DEFAULT 1,
  notes         TEXT,
  updated_at    DATETIME NOT NULL,
  UNIQUE(card_id, finish, COALESCE(finish_label, ''))
);
```
The composite uniqueness lets you track multiple distinct promo printings of the same card (League Q1 vs League Q2) as separate rows.

### 3.4 `scans` — one row per uploaded photo
```sql
CREATE TABLE scans (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  photo_hash            TEXT NOT NULL UNIQUE,        -- sha256 of original file bytes
  photo_path            TEXT NOT NULL,               -- ~/.lorscan/photos/<hash>.<ext>
  binder_id             INTEGER REFERENCES binders(id),  -- optional binder this scan belongs to
  page_number           INTEGER,                     -- which page of the binder
  status                TEXT NOT NULL,               -- 'pending' | 'completed' | 'failed'
  error_message         TEXT,
  api_request_payload   TEXT,                        -- what was sent to Claude
  api_response_payload  TEXT,                        -- raw Claude response
  cost_usd              REAL,                        -- decoded from response.usage
  created_at            DATETIME NOT NULL,
  completed_at          DATETIME
);
```

### 3.5 `scan_results` — one row per identified card on a scan
```sql
CREATE TABLE scan_results (
  id                       INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id                  INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  grid_position            TEXT NOT NULL,            -- "r1c2"
  claude_name              TEXT,
  claude_subtitle          TEXT,
  claude_collector_number  TEXT,                     -- exact, suffix preserved
  claude_set_hint          TEXT,
  claude_ink_color         TEXT,
  claude_finish            TEXT,                     -- 'regular' | 'cold_foil' | 'promo' | 'enchanted'
  confidence               TEXT NOT NULL,            -- 'high' | 'medium' | 'low'
  matched_card_id          TEXT REFERENCES cards(card_id),  -- null if no match
  match_method             TEXT,
  -- 'collector_number' | 'name+set' | 'name_only' | 'ambiguous_suffix' | 'unmatched'
  user_decision            TEXT,                     -- null until reviewed; then 'accepted' | 'rejected' | 'replaced'
  user_replaced_card_id    TEXT REFERENCES cards(card_id),
  position_anomaly             TEXT,
  -- Lifecycle (state machine):
  --   NULL or 'none'   = no anomaly detected
  --   'set_mismatch'   = auto-detected: card's set differs from binder rule
  --   'finish_mismatch'= auto-detected: card's finish differs from binder rule
  --   'outlier'        = auto-detected: card differs from page's modal set (≥7/9 majority)
  --   'user_confirmed' = user clicked "Confirm misplaced" → enters Reorganize queue
  --   'user_dismissed' = user clicked "Dismiss" → false positive, hidden from queue
  --   'resolved'       = user fixed the physical placement and ticked it off
  -- Auto-detected values are written by the matching/anomaly pass.
  -- The remaining values are written by user actions in the review or Reorganize UI.
  position_anomaly_detail      TEXT,                 -- e.g. "expected set TFC, found ROF"
  position_anomaly_resolved_at DATETIME,             -- set when user marks 'resolved'
  applied_at                   DATETIME              -- when accepted into collection
);
CREATE INDEX scan_results_scan_idx ON scan_results(scan_id);
```

### 3.6 `binders` — optional user-defined binder rules
```sql
CREATE TABLE binders (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL,                         -- "First Chapter (regulars)"
  set_code    TEXT REFERENCES sets(set_code),        -- nullable: 'any set'
  finish      TEXT,                                  -- nullable: 'regular' | 'cold_foil' | 'promo'
  notes       TEXT,
  created_at  DATETIME NOT NULL
);
```

### 3.7 `schema_migrations` — applied migration tracking
```sql
CREATE TABLE schema_migrations (
  version    TEXT PRIMARY KEY,
  applied_at DATETIME NOT NULL
);
```

### 3.8 Derived views (computed at query time, no migration)
- **What I have** — `collection_items` ⋈ `cards` ⋈ `sets`
- **What I'm missing** — for each set, `cards` LEFT JOIN `collection_items` WHERE `quantity` is null or 0
- **Set completion %** — `COUNT(distinct card_id WHERE in collection) / sets.total_cards` per set
- **Reorganize queue** — `scan_results` WHERE `position_anomaly NOT IN ('none', 'user_dismissed')`

### 3.9 Migration files
- `001_catalog.sql` — `sets`, `cards`, `schema_migrations`
- `002_collection.sql` — `collection_items`
- `003_scans.sql` — `scans`, `scan_results`
- `004_binders.sql` — `binders`, `ALTER scans ADD binder_id, page_number`, `ALTER scan_results ADD position_anomaly, position_anomaly_detail`

---

## 4. Scan Flow

### 4.1 Pipeline
1. **Upload.** Browser POSTs a photo to `/api/scan/upload`. Backend reads bytes into memory.
2. **Hash & dedupe.** Compute sha256 of bytes. If a `scans` row exists with that hash → skip API call, redirect to existing review page.
3. **Save.** Write the **original** upload bytes to `~/.lorscan/photos/<sha256>.<ext>` (no transformation). Insert `scans` row with `status='pending'`.
4. **Pre-flight image normalization (in-memory only, not persisted).** Build a normalized derivative for the API request: downscale long edge to ≤ 1568px (Anthropic vision recommended max), strip EXIF, re-encode JPEG @ 85% quality. The original on disk is untouched.
5. **Build request.**
   - **System prompt** (cached): role, lexicon (ink colors, rarities, set codes), layout rules, suffix preservation rule, confidence rules, JSON output schema.
   - **User message:** image + one-line instruction ("Identify the cards in this binder page.").
6. **Call Anthropic Messages API.** Vision-capable model (e.g., `claude-sonnet-4-6` or `claude-opus-4-7` — selectable via config). Use prompt caching on the system prompt.
7. **Persist usage.** Decode `response.usage` into `cost_usd` and store on the `scans` row.
8. **Parse JSON.** If `json.loads` fails, retry once with stricter "JSON only, no markdown fences" instruction. If still bad, mark `status='failed'`.
9. **Match each card.** Run §4.3 algorithm; insert `scan_results` rows with `match_method` and confidence.
10. **Run anomaly detection.** §4.4. Annotate `scan_results.position_anomaly`.
11. **Mark scan complete.** Redirect user to `/scan/<id>/review`.

### 4.2 Recognition contract (Claude → JSON)
```jsonc
{
  "page_type": "binder_3x3",   // or "binder_3x4", "loose_layout", "single_card"
  "cards": [
    {
      "grid_position": "r1c1",
      "name": "Hermes",
      "subtitle": "Messenger of the Gods",
      "set_hint": "URS",
      "collector_number": "127a",
      "ink_color": "Amber",
      "finish": "regular",
      "confidence": "high",
      "candidates": []
    }
    // … up to 9 entries for a 3x3 page
  ],
  "issues": [
    "row 2 col 3 has heavy glare, collector number unreadable"
  ]
}
```
The system prompt mandates:
- `collector_number` is reported **exactly as printed**, including letter suffixes; never normalized.
- If suffix is unreadable, omit it and lower confidence.
- `ink_color` and `finish` are constrained to the lexicon.
- Output is JSON only — no markdown, no prose.

### 4.3 Matching algorithm
Matching runs **before** anomaly detection (§4.4) and uses only what's directly available on each `scan_result`: Claude's reported fields plus the optional `binder_id` on the parent scan.

The "known set" used below is the **first** of these that is non-empty, in order:
1. `binder.set_code` from the scan's tagged binder (if any)
2. `claude_card.set_hint`

If neither is available, set is treated as unknown and matching falls through to the cross-set step.

```
INPUT: claude_card (parsed JSON entry), known_set (or None), catalog (cards table)

1. If claude_card.collector_number AND known_set:
     row = catalog WHERE set_code = known_set AND collector_number = ?  -- exact, suffix preserved
     if hit → match_method = 'collector_number', confidence unchanged

2. Elif claude_card.name AND known_set:
     rows = catalog WHERE set_code = known_set AND name = ?  -- with subtitle if present
     if exactly one row → match_method = 'name+set', confidence demoted one step
     if multiple rows → match_method = 'ambiguous_suffix', matched_card_id = NULL, candidates stored

3. Elif claude_card.name (cross-set fallback):
     rows = catalog WHERE name = ?
     if exactly one row → match_method = 'name_only', confidence = 'low'
     else → match_method = 'unmatched', matched_card_id = NULL

OUTPUT: matched_card_id (or NULL), match_method, possibly demoted confidence
```

### 4.4 Anomaly detection
```
For a scan S:

  IF S.binder_id IS NOT NULL:
    binder = lookup S.binder_id
    FOR EACH ci in scan_results:
      mismatches = []
      IF binder.set_code AND ci.matched_card.set_code != binder.set_code:
        mismatches += "set_mismatch (expected " + binder.set_code + ")"
      IF binder.finish AND ci.claude_finish != binder.finish:
        mismatches += "finish_mismatch (expected " + binder.finish + ")"
      IF mismatches:
        ci.position_anomaly = primary mismatch type
        ci.position_anomaly_detail = "; ".join(mismatches)

  ELSE:
    counts = group ci by ci.matched_card.set_code (skipping unmatched)
    modal_set, modal_count = max(counts)
    IF modal_count >= 7:                    # 7-of-9 threshold; below = no flag
      FOR EACH ci where ci.matched_card.set_code != modal_set:
        ci.position_anomaly = 'outlier'
        ci.position_anomaly_detail = "majority is " + modal_set + ", this card is " + ci.set_code
```

### 4.5 Review-and-accept UX
The `/scan/<id>/review` page:
- **Left pane:** original photo with bounding-box overlays mapping each grid slot.
- **Right pane:** 3×3 cell grid; each cell shows confidence badge (✓/⚠/?), match status, and an action area.
- **Per-cell actions:** Accept / Reject / Replace (search catalog) / Edit finish / Edit quantity / Confirm misplaced / Dismiss anomaly.
- **High-confidence matches default to "Accept" pre-selected.** User only acts on medium / low / unmatched / anomalous cells.
- **Apply button:** atomic transaction — every accepted result increments `collection_items.quantity`. Rejected/skipped results are preserved on the scan with their decision recorded; user can revisit.
- **Undo:** if the user later wants to reverse an accepted scan, a "Roll back this scan" button decrements all quantities atomically. Idempotency guaranteed by the `applied_at` column.

### 4.6 Cost transparency
- Every scan stores `cost_usd` derived from `response.usage`.
- The Scan page footer shows running monthly spend.
- Per-scan modal shows tokens (input / output / cache-read) and USD.
- Optional monthly soft budget configurable in `config.toml`; warns at 80%, 100%; never hard-blocks.

---

## 5. UI Pages

### 5.1 `/scan`
- Upload zone at top: drag-and-drop or file picker, multi-file supported.
- Optional binder + page-number tagging above the drop zone.
- Below: list of recent scans with status badges (`reviewed` ✓, `partial` ⚠, `pending` 🟡, `failed` ✕).
- Click a row → `/scan/<id>/review`.
- Footer: monthly cost summary.

### 5.2 `/collection`
- Default view: **3D page-flip binder visualization**, one virtual binder per set, set switcher tabs at top.
- Filled slots show catalog thumbnail with quantity badge and finish indicators (foil sparkle, promo stamp).
- Click a filled slot → side panel with quantity controls, finish toggle, notes, link to scan history.
- Filters: ink color, rarity, finish, free-text name search.
- Toggle to flat-grid view as a fallback for power-edit operations.

### 5.3 `/missing`
- Same 3D page-flip binder visualization, but **empty slots are visually loud** (gold border, subtle shimmer) so gaps are immediately legible.
- Per-set progress bar at the top of each binder ("The First Chapter — 187 / 204, 91.7%").
- Click an empty slot → side panel with catalog details and a placeholder "Find on marketplace" link (v2).
- Filters by set, ink color, rarity.

### 5.4 `/binders`
- CRUD page for user-defined binders (name + set rule + finish rule + notes).
- "Manage binders" link is reachable from `/scan` and `/collection`.

### 5.5 `/binder/<id>`
- Same binder visualization, scoped to a specific user-defined binder.

### 5.6 `/reorganize`
- Lists all unresolved misplacements grouped by binder & page.
- Each row: card thumbnail, current location (binder X, page 12, slot r2c3), expected location (best guess from card's actual set), checkbox to mark "fixed" → moves to history.

---

## 6. Binder Visualization

### 6.1 Component
A reusable Jinja2 macro + ~50 lines of CSS + ~50 lines of vanilla JS that renders any binder as a sequence of 3×3 pages with **3D page-flip transitions**.

### 6.2 Data inputs
- Source = either `set_code` (virtual set-binder) or `binder_id` (user-defined binder).
- For a set-binder: cards = all `cards` in that set, ordered by `collector_number` (suffix-aware: `1`, `1a`, `1b`, `2`, …).
- For a user-defined binder: cards filtered by binder rules (set + finish), then ordered the same way.
- Ownership data joined in for slot rendering: filled vs empty, quantity, finish.

### 6.3 Layout & math
- 9 cards per page.
- Page count = `ceil(len(cards) / 9)`.
- Empty slot = card not yet in `collection_items` (or quantity = 0).
- Filled slot = catalog thumbnail + small `×N` badge.
- Anomaly slot (only on the Reorganize view): orange border + warning icon.

### 6.4 Navigation
- **Keyboard:** ← / → / Page Up / Page Down to flip. Home / End to jump to first/last.
- **Mouse:** click left/right page edges, or arrow buttons.
- **Touch:** swipe (responsive layout works on phones).
- **Jump-to-page:** indicator dots OR number input ("Page [12] of 23").
- **Set switcher:** tabs or dropdown at top.

### 6.5 Animation
- **3D `rotateY`** with a midpoint divider. Pages turn from the right edge.
- Cubic-bezier ease, ~600ms duration.
- `transform-style: preserve-3d`; `backface-visibility: hidden` to avoid mirror-flicker.
- Component accepts a `transition` prop (`'flip' | 'slide'`); default `'flip'`. Allows trivial fallback to slide for low-power devices in future.

### 6.6 Performance
- Only the current ±1 pages are mounted in the DOM at any time (lazy mount).
- Catalog thumbnails cached locally on first download → `~/.lorscan/cache/images/<card_id>.webp`.
- Visualization works fully offline once a set's images are cached.

### 6.7 Slot interactions
- **Filled slot click:** side panel with quantity controls, finish toggle, notes, link to scan history that added it.
- **Empty slot click:** side panel with catalog card details and (v2) marketplace link.
- **Anomaly slot click (Reorganize view):** misplacement detail + "Confirm misplaced / Dismiss" actions.

---

## 7. Error Handling & Resilience

### 7.1 Failure modes & responses

| Failure | Detection | Response |
|---|---|---|
| Anthropic timeout / 5xx / rate-limit | HTTP error from SDK | Exponential backoff, max 3 attempts. Persist final failure. UI offers "Retry". |
| Anthropic returns prose / malformed JSON | `json.loads` fails | One retry with stricter "JSON only" instruction. If still bad → `status='failed'`, raw response stored. |
| Anthropic refusal / safety block | `stop_reason` indicates refusal | Mark scan failed with reason; don't retry; clear UI message. |
| Image too large | Pre-flight file-size check | Auto-downscale to long-edge ≤ 1568px before send. |
| Wrong file type | Magic-byte sniff at upload | Reject at upload, before save. |
| Multi-photo upload, one fails | Per-photo try/except | Other photos continue; failed one shown with retry button in scan list. |
| lorcana-api.com unreachable on first run | HTTP error during initial sync | Refuse to start; "needs network for first run" page with retry button. |
| lorcana-api.com unreachable on refresh | HTTP error during scheduled sync | Use cached catalog; banner: "Catalog last synced N days ago — new sets may be missing." |
| `~/.lorscan/` write fails | OSError on write | Fail fast with clear message naming path and likely cause. No silent fallback. |
| SQLite locked / corrupt | sqlite3 exception | Surface error; suggest restoring backup of `lorscan.db`. No auto-repair. |
| User edits scan_result to non-existent card | Catalog lookup miss in form handler | Form-level validation; never accept invalid `card_id` into `collection_items`. |

### 7.2 Cost / spend safeguards
- Per-scan budget cap: abort if API call would exceed **$0.50** (configurable; catches runaway loops).
- Per-minute throttle: max 6 vision calls per minute.
- Visible cost ledger on `/scan` footer.
- Optional monthly soft budget in `config.toml`; warning banners at 80% / 100%; no hard block.

### 7.3 Explicit non-handling in v1
- No mid-flight failover for in-progress API calls — failed scans just become re-runnable.
- Concurrent edits across browser tabs use last-write-wins on `scan_results.user_decision`.
- Database backups are user responsibility; CLI helper deferred.

---

## 8. Testing Strategy

### 8.1 Unit tests (pytest, no I/O)
- `services/recognition/prompt.py` — snapshot-test the system prompt to catch accidental drift (would invalidate cache or change Claude behavior).
- `services/recognition/parser.py` — exhaustive JSON cases: valid, malformed, partial, unexpected keys.
- `services/matching.py` — suffix-aware exact match, name+set fallback, ambiguous-suffix, unmatched. Tested with a tiny in-memory catalog.
- `services/anomaly.py` — explicit (binder rules) and implicit (modal-set ≥7/9) modes; edge cases (8/1, 7/2, 5/4 splits, all unmatched).

### 8.2 Integration tests (real files, in-memory SQLite)
- Catalog sync against recorded `lorcana-api.com` JSON fixtures.
- End-to-end scan with stubbed Anthropic SDK: upload → parse → match → review → accept → collection update.
- Migration test: run all migrations on a fresh DB; verify schema version.

### 8.3 Smoke tests (FastAPI test client)
- Each route returns 200 on the happy path with seeded data.
- Upload accepts JPG/PNG, rejects everything else.
- Review endpoint correctly increments `collection_items.quantity` on accept.

### 8.4 Live-API tests (manual, off by default)
- `tests/live/` suite that hits real Anthropic with one real photo and asserts ≥7/9 cards correctly matched.
- Run manually before releases (`pytest tests/live/ --runlive`). Never in CI.

### 8.5 Fixtures
- `tests/fixtures/photos/` — real binder-page photos provided by user.
- `tests/fixtures/api/` — recorded JSON from lorcana-api.com (2-3 sets).
- `tests/fixtures/claude/` — recorded Claude responses (good, malformed, anomalous).

### 8.6 Out of scope
- No browser-level UI tests in v1 (Playwright). Manual smoke testing only.
- No formal accessibility audit. Use semantic HTML; defer formal pass to later.

---

## 9. Open Questions / Future Work

These are deliberately deferred but worth noting now so they're not lost.

### 9.1 v1.1 candidates
- CLI `lorscan backup` command to snapshot `~/.lorscan/lorscan.db`.
- Single-card upload mode (in addition to 3×3 binder pages).
- `condition` field on `collection_items` (`NM` / `LP` / `MP` / `HP` / `DMG`).

### 9.2 v2 — Marketplace milestone
- Cardmarket integration (EU; primary target since user is in NL).
- eBay integration (universal).
- Price snapshots, alert thresholds, deep links into search results.
- TCGPlayer deferred / probably skipped (US-centric, low value for this user).

### 9.3 v2+ — Polish & growth
- Browser-automated UI tests (Playwright) once project is "tooling I share."
- Accessibility audit + a11y testing.
- Slot-level inventory tracking (where each physical card lives in which binder + page + slot).
- Trade list / wishlist priority flag.
- Multi-user + hosted deployment (would require auth, per-user data isolation, real DB).
- Native mobile app.

---

## 10. Locked Decisions Summary

| Decision | Value |
|---|---|
| Tool form | Local Python web app, browser → `localhost:8000` |
| Backend stack | FastAPI + Jinja2 + HTMX + raw `sqlite3` |
| Data location | `~/.lorscan/` (outside the repo) |
| Photo input | 3×3 binder pages, multi-card per photo (single-card later) |
| Recognition | Claude Messages API (vision) with cached system prompt |
| Card database | `lorcana-api.com` (cached locally, refreshable) |
| Quantity tracking | Counts per `(card, finish, finish_label)` |
| Variant model | Cold foil & promos as `finish` on possession; enchanted/unique-promos as separate `cards` rows |
| Suffixes | `collector_number` is opaque text; matching is suffix-exact |
| Set scope | All sets, on initial sync |
| Marketplace | Deferred to v2 (Cardmarket + eBay) |
| Recognition latency | Synchronous, 5–15s per page |
| Misplacement detection | Explicit (binder rules) + implicit (modal-set ≥7/9) |
| Reorganize workflow | `/reorganize` queue, dismissable, history-tracked |
| Binder visualization | 3D page-flip, used across Collection / Missing / Reorganize |
| UI shape | Three-page top-nav (Scan / Collection / Missing) + Binders & Reorganize as supporting pages |
| Cost guard | Per-scan $0.50 cap, per-minute 6-call throttle, visible monthly ledger |
| Testing | pytest unit + integration + smoke; manual live-API |

---

*End of design spec.*
