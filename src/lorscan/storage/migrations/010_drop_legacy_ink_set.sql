-- Migration 010: drop the legacy 'INK' set rows.
--
-- An early lorcana-api.com importer revision used 'INK' as the 3-letter
-- code for "Into the Inklands" before the project settled on 'ITI'.
-- Both sets remained in the DB after later imports added 'ITI' rows
-- alongside, leaving 204 dead 'INK-*' rows that the new LorcanaJSON sync
-- never touches (its `sets` payload only ships the canonical 'ITI'
-- naming). They render as a stale empty binder on /collection.
--
-- Also drop the legacy unsuffixed 'ITI-004' Dalmatian Puppy row. Upstream
-- LorcanaJSON ships only `4a`/`4b`/`4c`/`4d`/`4e` suffix variants for
-- this card; the next sync will create those as ITI-004a..e but won't
-- refresh ITI-004, leaving it orphaned.
--
-- FK refs in collection_items, marketplace_listings, and scan_results
-- are deleted in lockstep.

PRAGMA foreign_keys = OFF;

DELETE FROM collection_items WHERE card_id GLOB 'INK-*' OR card_id = 'ITI-004';
DELETE FROM marketplace_listings WHERE card_id GLOB 'INK-*' OR card_id = 'ITI-004';
DELETE FROM scan_results WHERE matched_card_id GLOB 'INK-*' OR matched_card_id = 'ITI-004';
DELETE FROM cards WHERE set_code = 'INK' OR card_id = 'ITI-004';
DELETE FROM sets WHERE set_code = 'INK';

PRAGMA foreign_keys = ON;
