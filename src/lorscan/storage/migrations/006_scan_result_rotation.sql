-- Persist the winning rotation per scan_result. Default 0 means upright.
-- Surfaced in the UI as a "↻ 180°" badge for cells where a non-zero rotation
-- gave the highest CLIP similarity.
ALTER TABLE scan_results ADD COLUMN rotation_degrees INTEGER NOT NULL DEFAULT 0;
