-- Phase 8b Silver: USDA generic foods, one row per food with per-100 g macros
-- Pivots the long-format food_nutrient rows with conditional aggregation.
-- Only real foods: Foundation releases also ship sample / sub-sample /
-- acquisition rows (lab records, not foods), which are excluded here.
--
-- Nutrient ids (FDC), first available wins:
--   kcal    1008 Energy (kcal) -> 2048 Atwater specific -> 2047 Atwater general
--           (Foundation foods often report only the Atwater values)
--   protein 1003
--   carbs   1005 by difference -> 1050 by summation
--   fat     1004 total lipid   -> 1085 total fat (NLEA)
-- @author Tony Shin <tonyshin4065@gmail.com>

DROP TABLE IF EXISTS usda_generic_silver;

CREATE TABLE usda_generic_silver AS
WITH amounts AS (
	SELECT
		fdc_id,
		nutrient_id,
		CASE
			WHEN amount ~ '^[0-9]*\.?[0-9]+$'
			THEN amount::DOUBLE PRECISION
			ELSE NULL
		END AS amount
	FROM usda_generic_food_nutrient
	WHERE nutrient_id IN ('1008', '2048', '2047', '1003', '1005', '1050', '1004', '1085')
),
pivoted AS (
	SELECT
		fdc_id,
		MAX(amount) FILTER (WHERE nutrient_id = '1008') AS kcal_1008,
		MAX(amount) FILTER (WHERE nutrient_id = '2048') AS kcal_2048,
		MAX(amount) FILTER (WHERE nutrient_id = '2047') AS kcal_2047,
		MAX(amount) FILTER (WHERE nutrient_id = '1003') AS protein_1003,
		MAX(amount) FILTER (WHERE nutrient_id = '1005') AS carbs_1005,
		MAX(amount) FILTER (WHERE nutrient_id = '1050') AS carbs_1050,
		MAX(amount) FILTER (WHERE nutrient_id = '1004') AS fat_1004,
		MAX(amount) FILTER (WHERE nutrient_id = '1085') AS fat_1085
	FROM amounts
	GROUP BY fdc_id
)
SELECT
	f.fdc_id                                   AS source_id,
	NULLIF(BTRIM(f.description), '')           AS name,
	f.data_type,
	f.dataset,
	'usda'                                     AS source,
	COALESCE(p.kcal_1008, p.kcal_2048, p.kcal_2047) AS kcal,
	p.protein_1003                             AS protein_g,
	COALESCE(p.carbs_1005, p.carbs_1050)       AS carbs_g,
	COALESCE(p.fat_1004, p.fat_1085)           AS fat_g,
	f.loaded_at
FROM usda_generic_food f
LEFT JOIN pivoted p ON p.fdc_id = f.fdc_id          -- keep foods with no macro rows
WHERE f.data_type IN ('sr_legacy_food', 'foundation_food')
	AND f.fdc_id ~ '^[0-9]+$';
