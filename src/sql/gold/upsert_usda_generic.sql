-- Phase 8b Gold: upsert USDA generic foods into foods_source
-- Keyed by (source, source_id = fdc_id), never by barcode (they have none).
-- Same rules as the Open Food Facts upsert: existing rows are updated IN
-- PLACE (ids never change), and unchanged rows aren't rewritten, so a rerun
-- reports 0. Foods without a name are skipped.
-- @author Tony Shin <tonyshin4065@gmail.com>

INSERT INTO foods_source (
	barcode, name, brand, source, source_id,
	kcal, protein_g, carbs_g, fat_g,
	calorie_check, loaded_at
)
SELECT
	NULL, name, NULL, source, source_id,
	kcal, protein_g, carbs_g, fat_g,
	calorie_check, loaded_at
FROM usda_generic_silver
WHERE name IS NOT NULL
ON CONFLICT (source, source_id) WHERE source_id IS NOT NULL
DO UPDATE SET
	name          = EXCLUDED.name,
	kcal          = EXCLUDED.kcal,
	protein_g     = EXCLUDED.protein_g,
	carbs_g       = EXCLUDED.carbs_g,
	fat_g         = EXCLUDED.fat_g,
	calorie_check = EXCLUDED.calorie_check,
	loaded_at     = EXCLUDED.loaded_at
WHERE (foods_source.name, foods_source.kcal, foods_source.protein_g,
       foods_source.carbs_g, foods_source.fat_g)
      IS DISTINCT FROM
      (EXCLUDED.name, EXCLUDED.kcal, EXCLUDED.protein_g,
       EXCLUDED.carbs_g, EXCLUDED.fat_g);
