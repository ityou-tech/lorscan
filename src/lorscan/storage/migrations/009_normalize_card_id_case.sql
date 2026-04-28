-- Migration 009: normalize card_ids whose <SET>- prefix doesn't match the
-- row's set_code column. Catches a known legacy typo ('URs-190' instead of
-- 'URS-190') and any similar drift from earlier importer revisions. Without
-- this, a fresh `sync-catalog` against LorcanaJSON would fail with a
-- UNIQUE(set_code, collector_number) collision when the new derivation
-- (`URS-190`) clashes with the legacy row.
--
-- FK refs in collection_items, marketplace_listings, and scan_results are
-- updated in lock-step. PRAGMA foreign_keys = OFF disables enforcement
-- during the rename window; SQLite ignores the pragma inside a transaction
-- but executescript runs in autocommit so the directive takes effect.

PRAGMA foreign_keys = OFF;

CREATE TEMP TABLE _card_id_renames AS
  SELECT card_id AS old_id,
         set_code || '-' || substr(card_id, instr(card_id, '-') + 1) AS new_id
  FROM cards
  WHERE instr(card_id, '-') > 0
    AND card_id != set_code || '-' || substr(card_id, instr(card_id, '-') + 1);

UPDATE collection_items
  SET card_id = (SELECT new_id FROM _card_id_renames WHERE old_id = collection_items.card_id)
  WHERE card_id IN (SELECT old_id FROM _card_id_renames);

UPDATE marketplace_listings
  SET card_id = (SELECT new_id FROM _card_id_renames WHERE old_id = marketplace_listings.card_id)
  WHERE card_id IN (SELECT old_id FROM _card_id_renames);

UPDATE scan_results
  SET matched_card_id = (SELECT new_id FROM _card_id_renames WHERE old_id = scan_results.matched_card_id)
  WHERE matched_card_id IN (SELECT old_id FROM _card_id_renames);

UPDATE cards
  SET card_id = (SELECT new_id FROM _card_id_renames WHERE old_id = cards.card_id)
  WHERE card_id IN (SELECT old_id FROM _card_id_renames);

DROP TABLE _card_id_renames;

PRAGMA foreign_keys = ON;
