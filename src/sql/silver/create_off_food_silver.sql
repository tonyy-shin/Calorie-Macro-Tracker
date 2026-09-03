-- Phase 2 Silver: Open Food Facts
-- Casts TEXT -> DOUBLE PRECISION with regex guard
-- Shapes columns to match usda_food_silver
-- A generated surrogate key is used to mirror fdc_id's role in usda_food_silver
-- @author Tony Shin <tonyshin4065@gmail.com>

DROP TABLE 
IF EXISTS off_product_silver;

CREATE TABLE off_product_silver AS
SELECT
	code as barcode,
	product_name,
	brands AS brand,
	'off' AS source,

	CASE
		WHEN energy_kcal_100g ~ '^[0-9]*\.?[0-9]+$'
		THEN energy_kcal_100g::DOUBLE PRECISION
		ELSE NULL
	END AS kcal,

	CASE 
                WHEN proteins_100g ~ '^[0-9]*\.?[0-9]+$'
                THEN proteins_100g::DOUBLE PRECISION
                ELSE NULL
        END AS protein_g,

	CASE 
                WHEN carbohydrates_100g ~ '^[0-9]*\.?[0-9]+$'
                THEN carbohydrates_100g::DOUBLE PRECISION
                ELSE NULL
        END AS carbs_g,

	CASE 
                WHEN fat_100g ~ '^[0-9]*\.?[0-9]+$'
                THEN fat_100g::DOUBLE PRECISION
                ELSE NULL
        END AS fat_g,
	
	loaded_at
FROM off_product;

ALTER TABLE off_product_silver
ADD COLUMN off_id
BIGINT GENERATED ALWAYS AS IDENTITY;
