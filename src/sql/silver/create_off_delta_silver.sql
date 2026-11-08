-- Phase 8 Silver: Open Food Facts delta
-- Parses each raw JSON line and casts the macros with the same regex guard
-- as off_product_silver. Lines that aren't valid JSON are skipped instead
-- of failing the whole run (pg_input_is_valid needs PostgreSQL 16+).
-- Field names match the CSV export's: energy-kcal_100g -> kcal, etc.
-- @author Tony Shin <tonyshin4065@gmail.com>

DROP TABLE IF EXISTS off_delta_silver;

CREATE TABLE off_delta_silver AS
WITH parsed AS (
	SELECT line::JSONB AS j, loaded_at
	FROM off_delta
	WHERE pg_input_is_valid(line, 'jsonb')
),
fields AS (
	SELECT
		NULLIF(BTRIM(j->>'code'), '') AS barcode,
		COALESCE(NULLIF(BTRIM(j->>'product_name'), ''),
		         NULLIF(BTRIM(j->>'product_name_en'), '')) AS product_name,
		NULLIF(BTRIM(j->>'brands'), '') AS brand,
		j->'nutriments'->>'energy-kcal_100g'   AS kcal_text,
		j->'nutriments'->>'proteins_100g'      AS protein_text,
		j->'nutriments'->>'carbohydrates_100g' AS carbs_text,
		j->'nutriments'->>'fat_100g'           AS fat_text,
		j->>'last_modified_t'                  AS modified_text,
		loaded_at
	FROM parsed
)
SELECT
	barcode,
	product_name,
	brand,
	'off' AS source,

	CASE
		WHEN kcal_text ~ '^[0-9]*\.?[0-9]+$'
		THEN kcal_text::DOUBLE PRECISION
		ELSE NULL
	END AS kcal,

	CASE
		WHEN protein_text ~ '^[0-9]*\.?[0-9]+$'
		THEN protein_text::DOUBLE PRECISION
		ELSE NULL
	END AS protein_g,

	CASE
		WHEN carbs_text ~ '^[0-9]*\.?[0-9]+$'
		THEN carbs_text::DOUBLE PRECISION
		ELSE NULL
	END AS carbs_g,

	CASE
		WHEN fat_text ~ '^[0-9]*\.?[0-9]+$'
		THEN fat_text::DOUBLE PRECISION
		ELSE NULL
	END AS fat_g,

	CASE
		WHEN modified_text ~ '^[0-9]+$'
		THEN modified_text::BIGINT
		ELSE NULL
	END AS source_modified_t,

	loaded_at
FROM fields;
