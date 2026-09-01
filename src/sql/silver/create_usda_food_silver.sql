-- Phase 2: silver transform of USDA
-- pivots long format usda_food_nutrient into wide format 
-- joins food description + brand/barcode
-- @author Tony Shin <tonyshin4065@gmail.com>

CREATE TABLE usda_food_silver AS
WITH pivoted AS (
	SELECT fdc_id,
	MAX(amount) FILTER (WHERE nutrient_id = '1008') AS kcal,
	MAX(amount) FILTER (WHERE nutrient_id = '1003') AS protein_g,
	MAX(amount) FILTER (WHERE nutrient_id = '1005') AS carbs_g,
	MAX(amount) FILTER (WHERE nutrient_id = '1004') AS fat_g
	FROM usda_food_nutrient
	GROUP BY fdc_id
)
SELECT 
	f.fdc_id,
	bf.gtin_upc AS barcode,
	f.description AS name,
	COALESCE(bf.brand_owner, bf.brand_name) AS brand,
	'usda' AS source,
	p.kcal::DOUBLE PRECISION AS kcal,
	p.protein_g::DOUBLE PRECISION AS protein_g,
	p.carbs_g:: DOUBLE PRECISION AS carbs_g,
	p.fat_g::DOUBLE PRECISION AS fat_g
FROM usda_food f
LEFT JOIN pivoted p ON p.fdc_id = f.fdc_id
LEFT JOIN usda_branded_food bf ON bf.fdc_id = f.fdc_id;


