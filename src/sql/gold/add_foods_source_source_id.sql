-- Phase 8b Gold: give foods_source a stable per-source key
-- USDA generic foods have no barcode, so barcode can't identify them for
-- in-place updates. source_id holds the source's own id (USDA fdc_id).
-- Unique per source when present; NULL for rows loaded before this column
-- existed. Safe to rerun.
-- @author Tony Shin <tonyshin4065@gmail.com>

ALTER TABLE foods_source
	ADD COLUMN IF NOT EXISTS source_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS foods_source_source_id_key
	ON foods_source (source, source_id)
	WHERE source_id IS NOT NULL;
