-- Phase 8 Bronze: Open Food Facts delta / JSONL dump, one raw line per row
-- Each line is one product as JSON, exactly as downloaded. Rebuilt for
-- every batch, so DROP + CREATE, and UNLOGGED (skips the write-ahead log:
-- nothing here needs to survive a crash).
-- @author Tony Shin <tonyshin4065@gmail.com>

DROP TABLE IF EXISTS off_delta;

CREATE UNLOGGED TABLE off_delta (
	line      TEXT,
	loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
