-- Persist the top-K CLIP candidates per scan_result so the user can
-- pick a different card later from the inline correction dropdown.
-- Stored as a JSON array of {card_id, similarity} objects (the same
-- shape ParsedCard.candidates already uses in memory). Pre-existing
-- rows leave this NULL — they just won't have a correction dropdown.

ALTER TABLE scan_results ADD COLUMN candidates TEXT;
