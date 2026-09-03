-- Phase 2 Silver: three way calorie flag.
-- Compares stated kcal against 4/4/9 formula from protein/carbs/fat,
-- 20% tolerance. NULL when any input is missing, TRUE/FALSE otherwise
-- @author Tony Shin <tonyshin4065@gmail.com>

ALTER TABLE usda_food_silver
 ADD COLUMN calorie_check BOOLEAN;

UPDATE usda_food_silver
SET calorie_check =
    CASE
        WHEN kcal IS NULL OR protein_g IS NULL OR carbs_g IS NULL OR fat_g IS NULL
            THEN NULL
        WHEN ABS(kcal - (protein_g * 4 + carbs_g * 4 + fat_g * 9)) <= 0.20 * kcal
            THEN TRUE
        ELSE FALSE
    END;

ALTER TABLE off_product_silver ADD COLUMN calorie_check BOOLEAN;

UPDATE off_product_silver
SET calorie_check =
    CASE
        WHEN kcal IS NULL OR protein_g IS NULL OR carbs_g IS NULL OR fat_g IS NULL
            THEN NULL
        WHEN ABS(kcal - (protein_g * 4 + carbs_g * 4 + fat_g * 9)) <= 0.20 * kcal
            THEN TRUE
        ELSE FALSE
    END;
