-- Phase 3 Gold: dedup usda_silver's barcode 
-- Get rid of usda_silver's duplicate barcodes
-- @author Tony Shin <tonyshin4065@gmail.com>


CREATE TABLE usda_food_gold AS

WITH ranked AS (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY barcode
               ORDER BY
                   (kcal IS NOT NULL)::INT
                 + (protein_g IS NOT NULL)::INT
                 + (carbs_g IS NOT NULL)::INT
                 + (fat_g IS NOT NULL)::INT DESC,
                   loaded_at DESC
           ) AS rn
    FROM usda_food_silver
    WHERE barcode IS NOT NULL
)
SELECT fdc_id, barcode, name, brand, source, kcal, protein_g, carbs_g, fat_g, loaded_at, calorie_check
FROM ranked
WHERE rn = 1

UNION ALL

SELECT fdc_id, barcode, name, brand, source, kcal, protein_g, carbs_g, fat_g, loaded_at, calorie_check
FROM usda_food_silver
WHERE barcode IS NULL;
