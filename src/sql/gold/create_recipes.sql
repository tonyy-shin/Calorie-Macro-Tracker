-- Phase 6: create recipes table
-- creates the recipes table that contains user saved recipes 
-- @author Tony Shin <tonyshin4065@gmail.com>

CREATE TABLE IF NOT EXISTS recipes (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id),
        name TEXT NOT NULL,
        yield_portions INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
