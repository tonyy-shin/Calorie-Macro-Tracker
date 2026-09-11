-- Phase 6: join recipes, recipe_items, and foods
-- creates the full table with recipes and foods
-- @author Tony Shin <tonyshin4065@gmail.com>

SELECT
    r.id,
    r.name,
    SUM(f.kcal * ri.grams / 100.0) / r.yield_portions AS kcal_per_portion,
    SUM(f.protein_g * ri.grams / 100.0) / r.yield_portions AS protein_g_per_portion,
    SUM(f.carbs_g * ri.grams / 100.0) / r.yield_portions AS carbs_g_per_portion,
    SUM(f.fat_g * ri.grams / 100.0) / r.yield_portions AS fat_g_per_portion
FROM recipes r
JOIN recipe_items ri ON ri.recipe_id = r.id
JOIN foods f ON f.id = ri.food_id AND f.origin = ri.food_origin
GROUP BY r.id, r.name, r.yield_portions;
