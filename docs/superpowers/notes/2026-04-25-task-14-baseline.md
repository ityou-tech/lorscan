# Task 14 baseline — first real-photo scan

**Date:** 2026-04-25
**Branch:** `feature/plan-1-foundation`
**Photo:** `tests/fixtures/photos/binder-page-1.jpg` (3×3 binder page, 9 cards in sleeves)
**Model:** `claude-opus-4-7`
**Auth:** Max plan via `claude setup-token` (subscription, no API credits used)

## Headline

**8 of 9 cards correctly identified by name.** The recognition pipeline works
end-to-end against a real binder photo. Cards Claude saw:

| pos  | name (Claude)       | confidence | collector #  | set hint |
| ---- | ------------------- | ---------- | ------------ | -------- |
| r1c1 | Hermes              | medium     | unreadable   | unread   |
| r1c2 | Fairy Godmother     | medium     | unreadable   | unread   |
| r1c3 | Chip the Teacup     | medium     | unreadable   | unread   |
| r2c1 | Jiminy Cricket      | medium     | unreadable   | unread   |
| r2c2 | Fairy Godmother     | medium     | unreadable   | unread   |
| r2c3 | Dr. Facilier        | medium     | unreadable   | unread   |
| r3c1 | ?                   | low        | unreadable   | unread   |
| r3c2 | Fairy Godmother     | medium     | unreadable   | unread   |
| r3c3 | Elsa                | medium     | unreadable   | unread   |

## Issues reported by the model

- collector numbers unreadable at this resolution for all cards
- r3c1 card name illegible — too small and partially obscured
- r1c2 ink color ambiguous between Steel and Amethyst
- r2c2 finish uncertain between cold_foil and enchanted
- set symbols not clearly readable on any card

## Cost & latency

- Cache cold (first call): **1m 37s**, **$0.1253**
- Tokens: input=6, output=5859, cache_read=28127
- Cache TTL: 1 hour (`ephemeral_1h`); subsequent scans should hit cache
  and cost ~$0.02–0.03

## What this tells us for Plan 2

### What's already working

- Per-cell `grid_position` reporting is correct (9/9 cells found, no phantom slots).
- Card name recognition is reliable at binder-page resolution.
- The `issues` array surfaces actionable problems instead of being a black box.
- The Max-subscription auth path works end-to-end with `--permission-mode auto`.

### The bottleneck: collector numbers

Without collector numbers, the matcher falls back to name-only — which only
succeeds when a name is unique across the entire Lorcana catalog. Names like
"Fairy Godmother" appear in multiple sets, so even with a complete catalog
many cards would still come back as `unmatched`.

**Plan 2 prompt-tuning target:** make collector numbers readable. Two
candidate approaches:

1. **Per-slot tile scanning.** Crop each binder cell to its own image
   before sending. This gives the model 9× more pixels per card. Trade-off:
   9× the API calls (so 9× the cost and latency, though caching helps).
2. **Photographic guidance.** A `lorscan doctor` UX hint that tells the
   user when their photo is too low-resolution to extract collector
   numbers, and suggests specific framing fixes (closer, better light,
   or tile mode).
3. **Tighter prompt.** Explicit instruction to spend extra effort on
   the collector number area and to report the most likely number with
   a confidence rather than refusing.

### What goes into the catalog matters

We only seeded 4 cards from a test fixture, so every name-only match was
correctly `unmatched`. Plan 2 must wire `lorscan sync-catalog` against
real `lorcana-api.com` data so the matcher has a complete reference.
With the full catalog and unique-name fallback, this scan would
have matched: Hermes (if unique), Chip the Teacup (likely unique),
Jiminy Cricket (likely unique), Dr. Facilier (likely unique), Elsa
(probably across sets — needs subtitle disambig).

### Confidence grades

Eight `medium` and one `low` — zero `high`. Two interpretations:

- **Conservative model behavior:** Opus 4.7 is appropriately reluctant
  to claim `high` when collector numbers are unreadable, even when the
  card name is dead-obvious. This is good-not-bad — it surfaces the
  uncertainty for human review.
- **The prompt could re-anchor `high`:** for example, "high confidence
  means name and ink color are clearly legible; collector number is
  not required for high confidence." Worth experimenting in Plan 2.

## Next steps

- Plan 2 wires real `sync-catalog` so matching has data to work with.
- Plan 2 also addresses the photo-quality / collector-number gap
  (tile mode? user-facing photo guidance?).
- This baseline is the metric to beat for Plan 2's recognition tuning.
