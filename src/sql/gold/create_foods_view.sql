-- Phase 4: create foods view
-- unify foods_source and foods_manual into one view for the app
-- @author Tony Shin <tonyshin4065@gmail.com>


DROP VIEW IF EXISTS foods;

CREATE VIEW foods AS
SELECT
        id,
        barcode,
        name,
        brand,
        'source' AS origin,
        NULL::BIGINT AS user_id,
        kcal,
        protein_g,
        carbs_g,
        fat_g
FROM foods_source
UNION ALL
SELECT
        id,
        barcode,
        name,
        brand,
        'manual' AS origin,
        user_id,
        kcal,
        protein_g,
        carbs_g,
        fat_g
FROM foods_manual;
