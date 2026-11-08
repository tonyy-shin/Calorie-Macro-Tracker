-- Phase 8 Silver: Open Food Facts delta
-- Parses each raw JSON line and casts the macros with the same regex guard
-- as off_product_silver. Lines that aren't valid JSON are skipped instead
-- of failing the whole run (pg_input_is_valid needs PostgreSQL 16+).
-- Field names match the CSV export's: energy-kcal_100g -> kcal, etc.
--
-- Performance: each line is parsed to JSONB exactly ONCE. "OFFSET 0" stops
-- Postgres from inlining the subquery; without it the planner copies
-- line::JSONB into every place j is used and re-parses each ~15 KB product
-- 14 times (measured: 21 s -> 3 s per 20k products).
-- UNLOGGED: rebuilt every batch, so it skips the write-ahead log.
-- @author Tony Shin <tonyshin4065@gmail.com>

DROP TABLE IF EXISTS off_delta_silver;

CREATE UNLOGGED TABLE off_delta_silver AS
WITH fields AS (
	SELECT
		j->>'code'            AS code,
		j->>'product_name'    AS product_name,
		j->>'product_name_en' AS product_name_en,
		j->>'brands'          AS brands,
		j->>'last_modified_t' AS modified_text,
		j->'nutriments'       AS n,
		loaded_at
	FROM (
		SELECT line::JSONB AS j, loaded_at
		FROM off_delta
		WHERE pg_input_is_valid(line, 'jsonb')
		OFFSET 0
	) parsed
)
SELECT
	NULLIF(BTRIM(code), '') AS barcode,
	COALESCE(NULLIF(BTRIM(product_name), ''),
	         NULLIF(BTRIM(product_name_en), '')) AS product_name,
	NULLIF(BTRIM(brands), '') AS brand,
	'off' AS source,

	CASE
		WHEN n->>'energy-kcal_100g' ~ '^[0-9]*\.?[0-9]+$'
		THEN (n->>'energy-kcal_100g')::DOUBLE PRECISION
		ELSE NULL
	END AS kcal,

	CASE
		WHEN n->>'proteins_100g' ~ '^[0-9]*\.?[0-9]+$'
		THEN (n->>'proteins_100g')::DOUBLE PRECISION
		ELSE NULL
	END AS protein_g,

	CASE
		WHEN n->>'carbohydrates_100g' ~ '^[0-9]*\.?[0-9]+$'
		THEN (n->>'carbohydrates_100g')::DOUBLE PRECISION
		ELSE NULL
	END AS carbs_g,

	CASE
		WHEN n->>'fat_100g' ~ '^[0-9]*\.?[0-9]+$'
		THEN (n->>'fat_100g')::DOUBLE PRECISION
		ELSE NULL
	END AS fat_g,

	CASE
		WHEN modified_text ~ '^[0-9]+$'
		THEN modified_text::BIGINT
		ELSE NULL
	END AS source_modified_t,

	loaded_at
FROM fields;
