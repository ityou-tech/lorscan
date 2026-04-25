-- Remove duplicate scan_results that accumulated before re-scan dedup
-- landed in the scan_upload route. The cause: insert_scan is idempotent
-- on photo_hash (returns the existing scan id) but insert_scan_result
-- previously appended without removing prior rows, so re-uploading the
-- same photo created N copies of every cell.
--
-- Strategy: for each (scan_id, grid_position), keep one row. Prefer rows
-- with applied_at set (so we don't lose collection-acceptance history),
-- then prefer the highest id (most recent run).
DELETE FROM scan_results
WHERE id NOT IN (
  SELECT keeper_id FROM (
    SELECT id AS keeper_id,
      ROW_NUMBER() OVER (
        PARTITION BY scan_id, grid_position
        ORDER BY (CASE WHEN applied_at IS NOT NULL THEN 0 ELSE 1 END), id DESC
      ) AS rn
    FROM scan_results
  )
  WHERE rn = 1
);
