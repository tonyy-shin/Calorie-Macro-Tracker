-- Phase 8b Bronze: USDA generic foods (SR Legacy + Foundation Foods)
-- food.csv and food_nutrient.csv, loaded exactly as downloaded, all TEXT.
-- Separate from the original usda_* bronze tables so the original Phase 1
-- load is untouched. Rebuilt on every load, so DROP + CREATE.
-- Columns are a superset of what each FDC release has used; the loader
-- COPYs with the file's own header (HEADER MATCH), so a column the file
-- doesn't have just stays NULL, and a column it has but this table doesn't
-- stops the load with a clear error instead of loading shifted data.
-- @author Tony Shin <tonyshin4065@gmail.com>

DROP TABLE IF EXISTS usda_generic_food;

CREATE TABLE usda_generic_food (
	fdc_id           TEXT,
	data_type        TEXT,
	description      TEXT,
	food_category_id TEXT,
	publication_date TEXT,
	market_country   TEXT,
	trade_channel    TEXT,
	microbe_data     TEXT,
	dataset          TEXT,                       -- set by the loader: 'sr_legacy' / 'foundation'
	loaded_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TABLE IF EXISTS usda_generic_food_nutrient;

CREATE TABLE usda_generic_food_nutrient (
	id                  TEXT,
	fdc_id              TEXT,
	nutrient_id         TEXT,
	amount              TEXT,
	data_points         TEXT,
	derivation_id       TEXT,
	min                 TEXT,
	max                 TEXT,
	median              TEXT,
	loq                 TEXT,
	footnote            TEXT,
	min_year_acquired   TEXT,
	percent_daily_value TEXT,
	loaded_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
