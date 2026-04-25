# lorscan TODO — running list

User-driven feature requests and small polish items, queued for Plan 2/3 work.

## UX / labeling

- [ ] **Rename CLI `set` column** — currently shows `claude_set_hint` (the
      model's guess), which is confusing when `--set <code>` was passed.
      Better label: `claude_saw` or `set_hint`. The web UI's `Set hint` label
      is already correct.
- [ ] **Highlight when `--set` overrides `claude_set_hint`.** Show e.g.
      `TFC → ROF (overridden)` in the column when they disagree.
- [ ] **CLI `--set` value validation** — if the user passes a set code that
      isn't in the catalog, fail fast with a "Did you mean: …?" hint
      against `db.get_sets()`.

## Recognition quality

- [ ] **Tile mode** — split a 3×3 binder photo into 9 single-card crops, run
      9 parallel scans. ~9× pixels per card → collector numbers should
      become readable. Major Plan 2 feature. Cost: 9× per-scan API cost
      (mitigated by prompt caching).
- [ ] **Photo-quality doctor** — `lorscan doctor <photo>` that checks
      resolution, lighting heuristics, and recommends fixes before scanning.
- [ ] **`JPEG_TRANSCODE_QUALITY`** — currently 92. Could bump to 95 for
      paranoid users; no observable accuracy gain, +5% file size.

## Web UI (Plan 2 — in progress)

- [ ] **Persist scans in the DB** — currently the web UI shows results
      synchronously and forgets them. Plan 2 spec says `scans` and
      `scan_results` rows should be created so the user can revisit.
- [ ] **Background processing** — synchronous upload blocks the browser
      for 1–4 min on cache-cold scans. Switch to FastAPI BackgroundTasks
      with a polling page once scans are persisted.
- [ ] **Recent scans list** on the `/scan` index page.
- [ ] **`/collection` page** — list cards the user owns, with quantities.
- [ ] **`/missing` page** — per-set progress, gap-card grid.
- [ ] **`/binders` + `/reorganize`** — Plan 2 spec §5.4–5.6.

## Plan 3

- [ ] **3D page-flip binder visualization** (per design spec §6).
- [ ] **Image cache** — `~/.lorscan/cache/images/<card_id>.webp`.
- [ ] **Live-API smoke tests** under `tests/live/`.
- [ ] **README + first release**.
