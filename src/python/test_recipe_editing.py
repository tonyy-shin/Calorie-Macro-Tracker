"""
@file test_recipe_editing.py
Phase 7 - Recipe editing
Tests for get_recipe, update_recipe and delete_recipe in recipes.py.
Uses a January 1999 date and throwaway users so real data is never
touched; all test rows are removed in the finally block.
@author Tony Shin <tonyshin4065@gmail.com>
"""

import uuid
from datetime import date

import psycopg

from recipes import create_recipe, delete_recipe, get_recipe, log_recipe_meal, update_recipe

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
test_date = date(1999, 1, 20)

conn = psycopg.connect(dbname="meal_tracker", user="tonyyshin", autocommit=True)
cur = conn.cursor()
user_ids = []

try:
        # --- setup: two users; user A owns two manual foods ---
        for who in ("a", "b"):
                cur.execute(
                        "insert into users (email, password) values (%s, %s) returning id",
                        (f"recipe_edit_{who}_{tag}@example.com", "not-a-real-hash"),
                )
                user_ids.append(cur.fetchone()[0])
        user_a, user_b = user_ids

        insert_manual = """
                insert into foods_manual (user_id, name, kcal, protein_g, carbs_g, fat_g)
                values (%s, %s, %s, %s, %s, %s) returning id
        """
        cur.execute(insert_manual, (user_a, f"oats {tag}", 400.0, 10.0, 60.0, 8.0))
        oats = cur.fetchone()[0]
        cur.execute(insert_manual, (user_a, f"milk {tag}", 60.0, 3.0, 5.0, 3.0))
        milk = cur.fetchone()[0]

        recipe_id = create_recipe(conn, user_a, f"porridge {tag}", 2,
                                  [(oats, "manual", 100), (milk, "manual", 200)])

        # =============================================================
        # get_recipe
        # =============================================================
        rec = get_recipe(conn, user_a, recipe_id)
        check("get_recipe returns the recipe", rec is not None and rec["id"] == recipe_id)
        check("name and yield loaded",
              rec["name"] == f"porridge {tag}" and rec["yield_portions"] == 2)
        check("two items, in insert order",
              [i["food_id"] for i in rec["items"]] == [oats, milk])
        check("item carries grams, name and macros",
              close(rec["items"][1]["grams"], 200)
              and rec["items"][1]["name"] == f"milk {tag}"
              and close(rec["items"][1]["kcal"], 60))
        check("other user can't load it", get_recipe(conn, user_b, recipe_id) is None)
        check("missing recipe returns None", get_recipe(conn, user_a, -1) is None)

        # log one meal before editing, to prove the snapshot survives
        meal_id = log_recipe_meal(conn, user_a, test_date, recipe_id, 1)
        cur.execute("select kcal from meal_log where id = %s", (meal_id,))
        kcal_before = cur.fetchone()[0]
        # whole recipe 400 + 120 = 520 kcal, / 2 portions = 260
        check("logged meal snapshot = 260 kcal", close(kcal_before, 260))

        # =============================================================
        # update_recipe
        # =============================================================
        update_recipe(conn, user_a, recipe_id, f"  big porridge {tag}  ", 4,
                      [(oats, "manual", 150), (milk, "manual", 300)])
        rec = get_recipe(conn, user_a, recipe_id)
        check("name updated and trimmed", rec["name"] == f"big porridge {tag}")
        check("yield updated", rec["yield_portions"] == 4)
        check("grams updated",
              [i["grams"] for i in rec["items"]] == [150.0, 300.0])

        update_recipe(conn, user_a, recipe_id, f"oat only {tag}", 1, [(oats, "manual", 50)])
        rec = get_recipe(conn, user_a, recipe_id)
        check("ingredient removed", [i["food_id"] for i in rec["items"]] == [oats])
        cur.execute("select count(*) from recipe_items where recipe_id = %s", (recipe_id,))
        check("old recipe_items rows replaced, not appended", cur.fetchone()[0] == 1)

        cur.execute("select kcal from meal_log where id = %s", (meal_id,))
        check("past meal_log snapshot unchanged by edits", close(cur.fetchone()[0], kcal_before))

        # rejections, each must leave the recipe as it was
        expect_value_error("rejects another user's recipe",
                lambda: update_recipe(conn, user_b, recipe_id, "x", 1, [(oats, "manual", 50)]))
        expect_value_error("rejects another user's manual food",
                lambda: update_recipe(conn, user_b, recipe_id, "x", 1, [(oats, "manual", 50)]))
        expect_value_error("rejects empty name",
                lambda: update_recipe(conn, user_a, recipe_id, "  ", 1, [(oats, "manual", 50)]))
        expect_value_error("rejects zero yield",
                lambda: update_recipe(conn, user_a, recipe_id, "x", 0, [(oats, "manual", 50)]))
        expect_value_error("rejects empty items",
                lambda: update_recipe(conn, user_a, recipe_id, "x", 1, []))
        expect_value_error("rejects nonexistent food",
                lambda: update_recipe(conn, user_a, recipe_id, "x", 1, [(-1, "manual", 50)]))
        expect_value_error("rejects nonexistent recipe",
                lambda: update_recipe(conn, user_a, -1, "x", 1, [(oats, "manual", 50)]))
        expect_value_error("rejects non-int recipe_id",
                lambda: update_recipe(conn, user_a, str(recipe_id), "x", 1, [(oats, "manual", 50)]))

        rec = get_recipe(conn, user_a, recipe_id)
        check("rejected updates left the recipe untouched",
              rec["name"] == f"oat only {tag}" and rec["yield_portions"] == 1
              and [(i["food_id"], i["grams"]) for i in rec["items"]] == [(oats, 50.0)])

        # =============================================================
        # delete_recipe
        # =============================================================
        expect_value_error("delete rejects another user's recipe",
                lambda: delete_recipe(conn, user_b, recipe_id))
        check("recipe still there after rejected delete",
              get_recipe(conn, user_a, recipe_id) is not None)

        delete_recipe(conn, user_a, recipe_id)
        check("recipe gone after delete", get_recipe(conn, user_a, recipe_id) is None)
        cur.execute("select count(*) from recipe_items where recipe_id = %s", (recipe_id,))
        check("its recipe_items are gone", cur.fetchone()[0] == 0)

        cur.execute("select meal_name, recipe_id, kcal from meal_log where id = %s", (meal_id,))
        name, rid, kcal = cur.fetchone()
        check("logged meal kept, name and snapshot intact",
              name == f"porridge {tag}" and close(kcal, kcal_before))
        check("logged meal's recipe link cleared", rid is None)

        expect_value_error("deleting it again raises", lambda: delete_recipe(conn, user_a, recipe_id))

finally:
        cur.execute("delete from meal_log where user_id = any(%s)", (user_ids,))
        cur.execute(
                "delete from recipe_items where recipe_id in "
                "(select id from recipes where user_id = any(%s))", (user_ids,))
        cur.execute("delete from recipes where user_id = any(%s)", (user_ids,))
        cur.execute("delete from foods_manual where user_id = any(%s)", (user_ids,))
        cur.execute("delete from users where id = any(%s)", (user_ids,))
        conn.close()

print(f"\n{passed} passed, {failed} failed")
