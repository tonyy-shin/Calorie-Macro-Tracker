-- Phase 8 Silver: three way calorie flag for the OFF delta.
-- Same rule as add_calorie_check.sql: stated kcal vs 4/4/9 formula, 20%
-- tolerance. NULL when any input is missing, TRUE/FALSE otherwise.
-- @author Tony Shin <tonyshin4065@gmail.com>

ALTER TABLE off_delta_silver ADD COLUMN calorie_check BOOLEAN;

UPDATE off_delta_silver
SET calorie_check =
    CASE
        WHEN kcal IS NULL OR protein_g IS NULL OR carbs_g IS NULL OR fat_g IS NULL
            THEN NULL
        WHEN ABS(kcal - (protein_g * 4 + carbs_g * 4 + fat_g * 9)) <= 0.20 * kcal
            THEN TRUE
        ELSE FALSE
    END;
