-- Phase 2 Silver: null out physically impossible macro values in USDA silver
-- kcal > 900/100g, any macro > 100g/100g
-- @author Tony Shin <tonyshin4065@gmail.com>

UPDATE usda_food_silver
SET kcal = NULL
WHERE kcal > 900 OR kcal < 0;

UPDATE usda_food_silver
SET protein_g = NULL
WHERE protein_g > 100 OR protein_g < 0;

UPDATE usda_food_silver
SET carbs_g = NULL
WHERE carbs_g > 100 OR carbs_g < 0;

UPDATE usda_food_silver
SET fat_g = NULL
WHERE fat_g > 100 OR fat_g < 0;
