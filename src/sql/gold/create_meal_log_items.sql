-- Phase 5: create meal_log_items table
-- creates the meal_log_items table that contain the ingredients for each meal_log
-- @author Tony Shin <tonyshin4065@gmail.com>

CREATE TABLE IF NOT EXISTS meal_log_items (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        meal_log_id BIGINT NOT NULL REFERENCES meal_log(id),
        food_id BIGINT NOT NULL,
        food_origin TEXT NOT NULL,
        grams DOUBLE PRECISION NOT NULL
);
