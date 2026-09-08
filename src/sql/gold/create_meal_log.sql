-- Phase 5: create meal log table
-- creates the table for when users save meals for later use (meal preps)
-- @author Tony Shin <tonyshin4065@gmail.com>

CREATE TABLE IF NOT EXISTS meal_log (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id),
        log_date DATE NOT NULL,
        meal_name TEXT,
        source_type TEXT NOT NULL,
        recipe_id BIGINT REFERENCES recipes(id),
        portions DOUBLE PRECISION,
        kcal DOUBLE PRECISION NOT NULL,
        protein_g DOUBLE PRECISION NOT NULL,
        carbs_g DOUBLE PRECISION NOT NULL,
        fat_g DOUBLE PRECISION NOT NULL,
        logged_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

