-- Phase 4: create foods_manual 
-- create a foods_manual table for manual food inputs coming from users
-- @author Tony Shin <tonyshin4065@gmail.com>

CREATE TABLE IF NOT EXISTS foods_manual (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id),
        barcode TEXT,
        name TEXT NOT NULL,
        brand TEXT,
        kcal DOUBLE PRECISION,
        protein_g DOUBLE PRECISION,
        carbs_g DOUBLE PRECISION,
        fat_g DOUBLE PRECISION,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
