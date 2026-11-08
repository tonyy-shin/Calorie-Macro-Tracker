-- Phase 8b Silver: three way calorie flag for USDA generic foods.
-- Same rule as add_calorie_check.sql: stated kcal vs 4/4/9 formula, 20%
-- tolerance. NULL when any input is missing, TRUE/FALSE otherwise.
-- @author Tony Shin <tonyshin4065@gmail.com>

ALTER TABLE usda_generic_silver ADD COLUMN calorie_check BOOLEAN;

UPDATE usda_generic_silver
SET calorie_check =
    CASE
        WHEN kcal IS NULL OR protein_g IS NULL OR carbs_g IS NULL OR fat_g IS NULL
            THEN NULL
        WHEN ABS(kcal - (protein_g * 4 + carbs_g * 4 + fat_g * 9)) <= 0.20 * kcal
            THEN TRUE
        ELSE FALSE
    END;
