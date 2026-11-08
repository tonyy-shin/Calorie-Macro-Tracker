"""
@file test_meal_editing.py
Phase 7 - Editing logged meals
Tests for meal_editing.py: get_meals_for_day, get_meal, update_meal,
delete_meal. Uses January 1999 dates and throwaway users so real data is
never touched; all test rows are removed in the finally block.
@author Tony Shin <tonyshin4065@gmail.com>
"""

import uuid
from datetime import date

import psycopg

from meal_editing import delete_meal, get_meal, get_meals_for_day, update_meal
from meal_logging import get_daily_rollup, log_ad_hoc_meal
from recipes import create_recipe, delete_recipe, log_recipe_meal

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
day1 = date(1999, 1, 25)
day2 = date(1999, 1, 26)

conn = psycopg.connect(dbname="meal_tracker", user="tonyyshin", autocommit=True)
cur = conn.cursor()
user_ids = []

try:
        # --- setup: two users; user A owns two manual foods ---
        for who in ("a", "b"):
                cur.execute(
                        "insert into users (email, password) values (%s, %s) returning id",
                        (f"meal_edit_{who}_{tag}@example.com", "not-a-real-hash"),
                )
                user_ids.append(cur.fetchone()[0])
        user_a, user_b = user_ids

        insert_manual = """
                insert into foods_manual (user_id, name, kcal, protein_g, carbs_g, fat_g)
                values (%s, %s, %s, %s, %s, %s) returning id
        """
        cur.execute(insert_manual, (user_a, f"rice {tag}", 130.0, 3.0, 28.0, 0.0))
        rice = cur.fetchone()[0]
        cur.execute(insert_manual, (user_a, f"egg {tag}", 150.0, 12.0, 1.0, 10.0))
        egg = cur.fetchone()[0]

        # ad hoc: 200 g rice + 100 g egg = 260 + 150 = 410 kcal
        adhoc = log_ad_hoc_meal(conn, user_a, day1, "lunch",
                                [(rice, "manual", 200), (egg, "manual", 100)])
        # recipe: 100 g rice + 100 g egg, yield 2 -> 140 kcal/portion; log 2 = 280
        recipe_id = create_recipe(conn, user_a, f"egg rice {tag}", 2,
                                  [(rice, "manual", 100), (egg, "manual", 100)])
        rmeal = log_recipe_meal(conn, user_a, day1, recipe_id, 2)

        # =============================================================
        # get_meals_for_day / get_meal
        # =============================================================
        meals = get_meals_for_day(conn, user_a, day1)
        check("day lists both meals in log order", [m["id"] for m in meals] == [adhoc, rmeal])
        check("meal row carries snapshot kcal", close(meals[0]["kcal"], 410))
        check("other user sees no meals", get_meals_for_day(conn, user_b, day1) == [])

        m = get_meal(conn, user_a, adhoc)
        check("get_meal loads ad hoc meal", m["source_type"] == "ad_hoc" and m["meal_name"] == "lunch")
        check("ad hoc items loaded with names",
              [(i["food_id"], i["grams"], i["name"]) for i in m["items"]]
              == [(rice, 200.0, f"rice {tag}"), (egg, 100.0, f"egg {tag}")])
        check("recipe meal has no items", get_meal(conn, user_a, rmeal)["items"] == [])
        check("other user can't load it", get_meal(conn, user_b, adhoc) is None)

        # =============================================================
        # update_meal: ad hoc
        # =============================================================
        update_meal(conn, user_a, adhoc, day1, "  big lunch  ",
                    items=[(rice, "manual", 300)])
        m = get_meal(conn, user_a, adhoc)
        check("ad hoc name updated and trimmed", m["meal_name"] == "big lunch")
        check("ad hoc items replaced", [(i["food_id"], i["grams"]) for i in m["items"]] == [(rice, 300.0)])
        check("ad hoc snapshot recomputed: 390 kcal", close(m["kcal"], 390))
        check("ad hoc protein recomputed: 9 g", close(m["protein_g"], 9))

        update_meal(conn, user_a, adhoc, day1, "   ", items=[(rice, "manual", 300)])
        check("blank name stored as NULL", get_meal(conn, user_a, adhoc)["meal_name"] is None)

        # =============================================================
        # update_meal: recipe (scales snapshot, survives recipe deletion)
        # =============================================================
        update_meal(conn, user_a, rmeal, day1, "dinner", portions=3)
        m = get_meal(conn, user_a, rmeal)
        check("recipe meal portions updated", close(m["portions"], 3))
        check("recipe snapshot scaled 280 -> 420", close(m["kcal"], 420))

        delete_recipe(conn, user_a, recipe_id)
        update_meal(conn, user_a, rmeal, day1, "dinner", portions=1)
        check("recipe meal still editable after its recipe is deleted",
              close(get_meal(conn, user_a, rmeal)["kcal"], 140))

        # moving a meal to another day
        update_meal(conn, user_a, rmeal, day2, "dinner", portions=1)
        check("meal moved to new date",
              [x["id"] for x in get_meals_for_day(conn, user_a, day2)] == [rmeal]
              and [x["id"] for x in get_meals_for_day(conn, user_a, day1)] == [adhoc])
        check("daily rollup follows the move",
              close(get_daily_rollup(conn, user_a, day1)["kcal"], 390)
              and close(get_daily_rollup(conn, user_a, day2)["kcal"], 140))

        # =============================================================
        # rejections leave the meal as it was
        # =============================================================
        before = get_meal(conn, user_a, adhoc)
        expect_value_error("rejects another user's meal",
                lambda: update_meal(conn, user_b, adhoc, day1, "x", items=[(rice, "manual", 1)]))
        expect_value_error("rejects another user's manual food",
                lambda: update_meal(conn, user_a, adhoc, day1, "x", items=[(-1, "manual", 10)]))
        expect_value_error("rejects empty items for ad hoc",
                lambda: update_meal(conn, user_a, adhoc, day1, "x", items=[]))
        expect_value_error("rejects zero grams",
                lambda: update_meal(conn, user_a, adhoc, day1, "x", items=[(rice, "manual", 0)]))
        expect_value_error("rejects portions on ad hoc meal",
                lambda: update_meal(conn, user_a, adhoc, day1, "x", items=[(rice, "manual", 10)], portions=2))
        expect_value_error("rejects items on recipe meal",
                lambda: update_meal(conn, user_a, rmeal, day2, "x", items=[(rice, "manual", 10)]))
        expect_value_error("rejects zero portions",
                lambda: update_meal(conn, user_a, rmeal, day2, "x", portions=0))
        expect_value_error("rejects fractional portions",
                lambda: update_meal(conn, user_a, rmeal, day2, "x", portions=1.5))
        expect_value_error("rejects non-date log_date",
                lambda: update_meal(conn, user_a, adhoc, "1999-01-25", "x", items=[(rice, "manual", 10)]))
        expect_value_error("rejects non-int meal_id",
                lambda: update_meal(conn, user_a, str(adhoc), day1, "x", items=[(rice, "manual", 10)]))
        after = get_meal(conn, user_a, adhoc)
        check("rejected updates left the meal untouched", before == after)

        # =============================================================
        # delete_meal
        # =============================================================
        expect_value_error("delete rejects another user's meal",
                lambda: delete_meal(conn, user_b, adhoc))
        check("meal still there after rejected delete", get_meal(conn, user_a, adhoc) is not None)

        delete_meal(conn, user_a, adhoc)
        check("meal gone after delete", get_meal(conn, user_a, adhoc) is None)
        cur.execute("select count(*) from meal_log_items where meal_log_id = %s", (adhoc,))
        check("its meal_log_items are gone", cur.fetchone()[0] == 0)
        check("rollup drops to 0 for that day", close(get_daily_rollup(conn, user_a, day1)["kcal"], 0))
        expect_value_error("deleting it again raises", lambda: delete_meal(conn, user_a, adhoc))

        delete_meal(conn, user_a, rmeal)
        check("recipe meal deleted", get_meals_for_day(conn, user_a, day2) == [])

finally:
        cur.execute(
                "delete from meal_log_items where meal_log_id in "
                "(select id from meal_log where user_id = any(%s))", (user_ids,))
        cur.execute("delete from meal_log where user_id = any(%s)", (user_ids,))
        cur.execute(
                "delete from recipe_items where recipe_id in "
                "(select id from recipes where user_id = any(%s))", (user_ids,))
        cur.execute("delete from recipes where user_id = any(%s)", (user_ids,))
        cur.execute("delete from foods_manual where user_id = any(%s)", (user_ids,))
        cur.execute("delete from users where id = any(%s)", (user_ids,))
        conn.close()

print(f"\n{passed} passed, {failed} failed")
