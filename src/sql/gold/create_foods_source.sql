-- Phase 3 Gold: UNION ALL usda and off
-- Creates the final table foods_source
-- @author Tony Shin <tonyshin4065@gmail.com>

DROP TABLE IF EXISTS foods_source;

CREATE TABLE foods_source (
	id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
	barcode TEXT,
	name TEXT NOT NULL,
	brand TEXT,
	source TEXT NOT NULL,
	kcal DOUBLE PRECISION,
	protein_g DOUBLE PRECISION,
	carbs_g DOUBLE PRECISION,
	fat_g DOUBLE PRECISION,
	loaded_at TIMESTAMPTZ NOT NULL,
	calorie_check BOOLEAN
);

INSERT INTO foods_source (
	barcode,
	name,
	brand,
	source,
	kcal,
	protein_g,
	carbs_g,
	fat_g,
	calorie_check,
	loaded_at
)
SELECT barcode,
        name, 
        brand,
        source,
        kcal,
        protein_g,
        carbs_g,
        fat_g,
	calorie_check,
        loaded_at
FROM usda_food_gold

UNION ALL

SELECT barcode,
        product_name, 
        brand,
        source,
        kcal,
        protein_g,
        carbs_g,
        fat_g,
	calorie_check,
        loaded_at
FROM off_product_gold o
WHERE product_name IS NOT NULL
	AND (
		o.barcode IS NULL
		OR NOT EXISTS (
			SELECT 1 FROM usda_food_gold u WHERE u.barcode = o.barcode
		)
	)
