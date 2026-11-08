-- Phase 8 Gold: prepare foods_source for in-place incremental updates
-- Run once (safe to rerun). foods_source is never dropped again from here
-- on: recipe_items and meal_log_items point at its ids, so rebuilding the
-- table would break every saved recipe and logged meal.
--   1. barcode becomes UNIQUE so ON CONFLICT (barcode) can upsert.
--      NULL barcodes are still allowed (and allowed to repeat).
--   2. source_modified_t = OFF's last_modified_t for the row's current
--      data, so an older delta can never overwrite newer data.
-- @author Tony Shin <tonyshin4065@gmail.com>

ALTER TABLE foods_source
	ADD COLUMN IF NOT EXISTS source_modified_t BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS foods_source_barcode_key
	ON foods_source (barcode);

-- the old non-unique index is now redundant
DROP INDEX IF EXISTS idx_foods_source_barcode;
