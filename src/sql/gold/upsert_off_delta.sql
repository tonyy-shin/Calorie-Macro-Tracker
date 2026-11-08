-- Phase 8 Gold: upsert one OFF delta batch into foods_source
-- Rules:
--   * Existing rows are UPDATED IN PLACE, so their ids never change
--     (recipe_items and meal_log_items reference them).
--   * USDA still wins barcode collisions: USDA rows are never overwritten.
--   * Newest wins: a row is only updated if the incoming data is at least as
--     new as what's stored (source_modified_t), so deltas can be replayed or
--     applied out of order safely.
--   * Unchanged rows aren't rewritten, so the row count = real changes.
-- Dedup inside the batch first: ON CONFLICT can't touch one row twice.
-- @author Tony Shin <tonyshin4065@gmail.com>

WITH ranked AS (
	SELECT *,
	ROW_NUMBER() OVER (
		PARTITION BY barcode
		ORDER BY
			source_modified_t DESC NULLS LAST,
			(carbs_g IS NOT NULL)::INT
			+ (fat_g IS NOT NULL)::INT
			+ (kcal IS NOT NULL)::INT
			+ (protein_g IS NOT NULL)::INT DESC
	) AS rn
	FROM off_delta_silver
	WHERE barcode IS NOT NULL
		AND product_name IS NOT NULL
)
INSERT INTO foods_source (
	barcode, name, brand, source,
	kcal, protein_g, carbs_g, fat_g,
	calorie_check, source_modified_t, loaded_at
)
SELECT
	barcode, product_name, brand, source,
	kcal, protein_g, carbs_g, fat_g,
	calorie_check, source_modified_t, loaded_at
FROM ranked
WHERE rn = 1
ON CONFLICT (barcode) DO UPDATE
SET
	name              = EXCLUDED.name,
	brand             = EXCLUDED.brand,
	kcal              = EXCLUDED.kcal,
	protein_g         = EXCLUDED.protein_g,
	carbs_g           = EXCLUDED.carbs_g,
	fat_g             = EXCLUDED.fat_g,
	calorie_check     = EXCLUDED.calorie_check,
	source_modified_t = EXCLUDED.source_modified_t,
	loaded_at         = EXCLUDED.loaded_at
WHERE foods_source.source = 'off'
	AND (foods_source.source_modified_t IS NULL
	     OR EXCLUDED.source_modified_t IS NULL
	     OR EXCLUDED.source_modified_t >= foods_source.source_modified_t)
	AND (foods_source.name, foods_source.brand,
	     foods_source.kcal, foods_source.protein_g,
	     foods_source.carbs_g, foods_source.fat_g)
	    IS DISTINCT FROM
	    (EXCLUDED.name, EXCLUDED.brand,
	     EXCLUDED.kcal, EXCLUDED.protein_g,
	     EXCLUDED.carbs_g, EXCLUDED.fat_g);
