-- Phase 6: create recipe_items table
-- create recipe_items table containing recipe ingredients
-- @author Tony Shin <tonyshin4065@gmail.com>

CREATE TABLE IF NOT EXISTS recipe_items(
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        recipe_id BIGINT NOT NULL REFERENCES recipes(id),
        food_id BIGINT NOT NULL,
        food_origin TEXT NOT NULL,
        grams DOUBLE PRECISION NOT NULL
);
