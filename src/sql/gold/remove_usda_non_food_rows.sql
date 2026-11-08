-- Phase 8b Gold: remove USDA rows that aren't foods, or are stale duplicates
-- The original Phase 2 load passed every barcode-less USDA row through to
-- foods_source, including lab records (sample_food, sub_sample_food,
-- market_acquisition, agricultural_acquisition: measurements of individual
-- samples, e.g. "BANANAS, RIPE" with no macros) and Foundation foods whose
-- macros were all NULL (Foundation reports energy as Atwater kcal, which
-- the original pivot didn't read). The generic load now provides the
-- Foundation foods again, complete and keyed by fdc_id.
--
-- foods_source has no fdc_id for those old rows, so they're matched by
-- name against the original bronze usda_food table. A row is removed only
-- if ALL of these hold:
--   * USDA, no barcode, no source_id (loaded by the original pipeline)
--   * its name is a non-food or Foundation description in usda_food
--   * the same name is NOT also a branded food (could be a real product)
--   * no recipe or logged meal references it
-- Ids of every remaining row are unchanged.
-- @author Tony Shin <tonyshin4065@gmail.com>

DELETE FROM foods_source fs
WHERE fs.source = 'usda'
	AND fs.barcode IS NULL
	AND fs.source_id IS NULL
	AND EXISTS (
		SELECT 1 FROM usda_food u
		WHERE u.description = fs.name
			AND u.data_type IN ('sample_food', 'sub_sample_food', 'market_acquisition',
			                    'agricultural_acquisition', 'foundation_food')
	)
	-- NOT EXISTS, not NOT IN: with ~2M branded names, NOT IN can't be hashed
	-- and Postgres rescans the whole list for every candidate row (hours);
	-- NOT EXISTS runs as one hash anti-join (seconds)
	AND NOT EXISTS (
		SELECT 1 FROM usda_food u
		WHERE u.description = fs.name
			AND u.data_type = 'branded_food'
	)
	AND NOT EXISTS (
		SELECT 1 FROM recipe_items ri
		WHERE ri.food_id = fs.id AND ri.food_origin = 'source'
	)
	AND NOT EXISTS (
		SELECT 1 FROM meal_log_items mi
		WHERE mi.food_id = fs.id AND mi.food_origin = 'source'
	);
