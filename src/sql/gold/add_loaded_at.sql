-- Phase 3 Gold: add missing loaded_at column
-- loaded_at indicates when the data was loaded
-- @author Tony Shin <tonyshin4065@gmail.com>

ALTER TABLE  usda_food_silver
ADD COLUMN loaded_at TIMESTAMPTZ;

UPDATE usda_food_silver s
SET loaded_at = f.loaded_at
FROM usda_food f
WHERE s.fdc_id = f.fdc_id;
