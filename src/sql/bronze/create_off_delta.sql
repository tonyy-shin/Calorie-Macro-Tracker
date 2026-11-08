-- Phase 8 Bronze: Open Food Facts delta / JSONL dump, one raw line per row
-- Each line is one product as JSON, exactly as downloaded. Rebuilt for
-- every batch, so DROP + CREATE.
-- @author Tony Shin <tonyshin4065@gmail.com>

DROP TABLE IF EXISTS off_delta;

CREATE TABLE off_delta (
	line      TEXT,
	loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
