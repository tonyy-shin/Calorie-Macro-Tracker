"""
@file test_recipes.py
Phase 6 - Recipes
Tests for recipes.py: create_recipe and log_recipe_meal, plus a check that
get_daily_rollup picks up recipe-based meals. Uses January 1999 dates and
throwaway users so real data is never touched; all test rows are removed
in the finally block.
@author Tony Shin <tonyshin4065@gmail.com>
"""

import uuid
from datetime import date

import psycopg

from recipes import create_recipe, log_recipe_meal
from meal_logging import get_daily_rollup

passed = 0
failed = 0


def check(label, condition):
        global passed, failed
        if condition:
                passed += 1
                print(f"PASS  {label}")
        else:
                failed += 1
                print(f"FAIL  {label}")


def expect_value_error(label, fn):
        try:
                fn()
        except ValueError:
                check(label, True)
                return
        except Exception as e:
                check(f"{label} (raised {type(e).__name__}: {e})", False)
                return
        check(f"{label} (no error raised)", False)


def close(a, b):
        return a is not None and abs(a - b) < 1e-6


tag = uuid.uuid4().hex[:8]
test_date = date(1999, 1, 10)

conn = psycopg.connect(dbname="meal_tracker", user="tonyyshin", autocommit=True)

user_a = None
user_b = None

try:
        cur = conn.cursor()

        # --- setup: two users, manual foods owned by user A ---
        cur.execute(
                "insert into users (email, password) values (%s, %s) returning id",
                (f"test_recipes_a_{tag}@example.com", "not-a-real-hash"),
        )
        user_a = cur.fetchone()[0]
        cur.execute(
                "insert into users (email, password) values (%s, %s) returning id",
                (f"test_recipes_b_{tag}@example.com", "not-a-real-hash"),
        )
        user_b = cur.fetchone()[0]

        # per 100g: chicken 165 kcal / 31 p / 0 c / 4 f, rice 130 / 3 / 28 / 0
        cur.execute(
                "insert into foods_manual (user_id, name, kcal, protein_g, carbs_g, fat_g) "
                "values (%s, %s, 165, 31, 0, 4) returning id",
                (user_a, f"chicken_{tag}"),
        )
        chicken_id = cur.fetchone()[0]
        cur.execute(
                "insert into foods_manual (user_id, name, kcal, protein_g, carbs_g, fat_g) "
                "values (%s, %s, 130, 3, 28, 0) returning id",
                (user_a, f"rice_{tag}"),
        )
        rice_id = cur.fetchone()[0]
        cur.execute(
                "insert into foods_manual (user_id, name, kcal, protein_g, carbs_g, fat_g) "
                "values (%s, %s, null, 10, 10, 10) returning id",
                (user_a, f"nullkcal_{tag}"),
        )
        null_food_id = cur.fetchone()[0]

        bowl_items = [
                (chicken_id, "manual", 600),
                (rice_id, "manual", 400),
        ]
        bowl_name = f"Chicken rice bowl {tag}"

        # =============================================================
        # create_recipe
        # =============================================================
        recipe_id = create_recipe(conn, user_a, bowl_name, 4, bowl_items)
        check("create_recipe returns an int id", isinstance(recipe_id, int))

        cur.execute(
                "select name, yield_portions, user_id from recipes where id = %s",
                (recipe_id,),
        )
        row = cur.fetchone()
        check("recipes row has correct name/yield/owner",
              row == (bowl_name, 4, user_a))

        cur.execute(
                "select count(*) from recipe_items where recipe_id = %s",
                (recipe_id,),
        )
        check("recipe_items has 2 rows", cur.fetchone()[0] == 2)

        expect_value_error("create_recipe rejects empty name",
                lambda: create_recipe(conn, user_a, "", 4, bowl_items))
        expect_value_error("create_recipe rejects whitespace-only name",
                lambda: create_recipe(conn, user_a, "   ", 4, bowl_items))
        expect_value_error("create_recipe rejects yield 0",
                lambda: create_recipe(conn, user_a, bowl_name, 0, bowl_items))
        expect_value_error("create_recipe rejects non-numeric yield",
                lambda: create_recipe(conn, user_a, bowl_name, "4", bowl_items))
        expect_value_error("create_recipe rejects nonexistent food",
                lambda: create_recipe(conn, user_a, bowl_name, 4,
                                      [(-1, "manual", 100)]))
        expect_value_error("create_recipe rejects food with NULL macros",
                lambda: create_recipe(conn, user_a, bowl_name, 4,
                                      [(null_food_id, "manual", 100)]))
        expect_value_error("create_recipe rejects another user's manual food",
                lambda: create_recipe(conn, user_b, bowl_name, 4, bowl_items))

        cur.execute("select count(*) from recipes where user_id = %s", (user_b,))
        check("rejected recipe left no partial write", cur.fetchone()[0] == 0)

        # =============================================================
        # log_recipe_meal
        # =============================================================
        # whole recipe: 1510 kcal, 198 p, 112 c, 24 f -> /4 per portion
        # 2 portions = 755 kcal, 99 p, 56 c, 12 f
        meal_id = log_recipe_meal(conn, user_a, test_date, recipe_id, 2)
        check("log_recipe_meal returns an int id", isinstance(meal_id, int))

        cur.execute(
                "select meal_name, source_type, recipe_id, portions, "
                "kcal, protein_g, carbs_g, fat_g from meal_log where id = %s",
                (meal_id,),
        )
        name, stype, rid, portions, kcal, p, c, f = cur.fetchone()
        check("meal_name defaults to recipe name", name == bowl_name)
        check("source_type is 'recipe'", stype == "recipe")
        check("recipe_id stored", rid == recipe_id)
        check("portions stored", close(portions, 2))
        check("kcal snapshot = 755", close(kcal, 755))
        check("protein snapshot = 99", close(p, 99))
        check("carbs snapshot = 56", close(c, 56))
        check("fat snapshot = 12", close(f, 12))

        cur.execute(
                "select count(*) from meal_log_items where meal_log_id = %s",
                (meal_id,),
        )
        check("no meal_log_items for recipe meal", cur.fetchone()[0] == 0)

        # explicit name, 1 portion = 377.5 kcal
        meal_id_2 = log_recipe_meal(conn, user_a, test_date, recipe_id, 1,
                                    "  Lunch  ")
        cur.execute("select meal_name, kcal from meal_log where id = %s",
                    (meal_id_2,))
        name2, kcal2 = cur.fetchone()
        check("explicit meal_name is stripped and stored", name2 == "Lunch")
        check("1 portion kcal = 377.5", close(kcal2, 377.5))

        # --- rejections ---
        cur.execute("select count(*) from meal_log where user_id = %s", (user_a,))
        logs_before = cur.fetchone()[0]

        expect_value_error("rejects another user's recipe",
                lambda: log_recipe_meal(conn, user_b, test_date, recipe_id, 1))
        expect_value_error("rejects nonexistent recipe",
                lambda: log_recipe_meal(conn, user_a, test_date, -1, 1))
        expect_value_error("rejects portions 0",
                lambda: log_recipe_meal(conn, user_a, test_date, recipe_id, 0))
        expect_value_error("rejects negative portions",
                lambda: log_recipe_meal(conn, user_a, test_date, recipe_id, -1))
        expect_value_error("rejects string portions",
                lambda: log_recipe_meal(conn, user_a, test_date, recipe_id, "2"))
        expect_value_error("rejects bool portions",
                lambda: log_recipe_meal(conn, user_a, test_date, recipe_id, True))
        expect_value_error("rejects fractional portions (whole numbers only)",
                lambda: log_recipe_meal(conn, user_a, test_date, recipe_id, 1.5))
        expect_value_error("rejects bool recipe_id",
                lambda: log_recipe_meal(conn, user_a, test_date, True, 1))
        expect_value_error("rejects whitespace-only meal_name",
                lambda: log_recipe_meal(conn, user_a, test_date, recipe_id, 1, "   "))

        # broken ingredient: bypass create_recipe to simulate a food that
        # disappeared from foods (e.g. after a USDA full swap)
        cur.execute(
                "insert into recipes (user_id, name, yield_portions) "
                "values (%s, %s, 2) returning id",
                (user_a, f"broken_{tag}"),
        )
        broken_id = cur.fetchone()[0]
        cur.execute(
                "insert into recipe_items (recipe_id, food_id, food_origin, grams) "
                "values (%s, %s, 'manual', 200), (%s, -1, 'manual', 100)",
                (broken_id, chicken_id, broken_id),
        )
        expect_value_error("rejects recipe with an unresolvable ingredient",
                lambda: log_recipe_meal(conn, user_a, test_date, broken_id, 1))

        cur.execute("select count(*) from meal_log where user_id = %s", (user_a,))
        check("rejected logs wrote nothing", cur.fetchone()[0] == logs_before)

        # =============================================================
        # daily rollup picks up recipe meals
        # =============================================================
        rollup = get_daily_rollup(conn, user_a, test_date)
        check("rollup kcal = 755 + 377.5", close(rollup["kcal"], 1132.5))
        check("rollup protein = 99 + 49.5", close(rollup["protein_g"], 148.5))
        check("rollup meal_names in log order",
              rollup["meal_names"] == [bowl_name, "Lunch"])

finally:
        cur = conn.cursor()
        ids = [u for u in (user_a, user_b) if u is not None]
        if ids:
                cur.execute(
                        "delete from meal_log_items where meal_log_id in "
                        "(select id from meal_log where user_id = any(%s))", (ids,))
                cur.execute("delete from meal_log where user_id = any(%s)", (ids,))
                cur.execute(
                        "delete from recipe_items where recipe_id in "
                        "(select id from recipes where user_id = any(%s))", (ids,))
                cur.execute("delete from recipes where user_id = any(%s)", (ids,))
                cur.execute("delete from foods_manual where user_id = any(%s)", (ids,))
                cur.execute("delete from users where id = any(%s)", (ids,))
        conn.close()

print(f"\n{passed} passed, {failed} failed")
