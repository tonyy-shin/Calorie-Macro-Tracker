-- Phase 3 Gold: dedup off_product_silver's barcode
-- Get rid of off_silver's duplicate barcodes
-- @author Tony Shin <tonyshin4065@gmail.com>

DROP TABLE IF EXISTS off_product_gold;

CREATE TABLE off_product_gold AS

WITH ranked AS (
	SELECT *,
	ROW_NUMBER() OVER (
		PARTITION BY barcode
		ORDER BY
			(carbs_g IS NOT NULL)::INT
			+ (fat_g IS NOT NULL)::INT
			+ (kcal IS NOT NULL)::INT
			+ (protein_g IS NOT NULL)::INT DESC,
			loaded_at DESC
	) AS rn
	FROM off_product_silver
	WHERE barcode is NOT NULL
)
SELECT off_id, barcode, product_name, brand, source, kcal, protein_g, carbs_g, fat_g, loaded_at, calorie_check
FROM ranked
WHERE rn = 1

UNION ALL

SELECT off_id, barcode, product_name, brand, source, kcal, protein_g, carbs_g, fat_g, loaded_at, calorie_check
FROM off_product_silver
WHERE barcode IS NULL;
