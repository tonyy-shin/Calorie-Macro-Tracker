"""
Phase 7 — tests for manual_foods.add_manual_food

Creates two throwaway users tagged with a UUID, runs every path, and
deletes everything it made in finally.

Run: python src/python/test_manual_foods.py

@author Tony Shin <tonyshin4065@gmail.com>
"""

import uuid

import psycopg

from manual_foods import add_manual_food

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}")


def expect_value_error(label, fn):
    try:
        fn()
    except ValueError:
        check(label, True)
    except Exception as e:
        check(f"{label} (raised {type(e).__name__}: {e})", False)
    else:
        check(f"{label} (no error raised)", False)


def close(a, b, tol=1e-6):
    return a is not None and abs(a - b) < tol


def main():
    conn = psycopg.connect(dbname="meal_tracker", user="tonyyshin",
                           autocommit=True)
    cur = conn.cursor()
    tag = uuid.uuid4().hex[:8]
    user_ids = []

    try:
        for who in ("a", "b"):
            cur.execute(
                "insert into users (email, password) values (%s, %s) "
                "returning id",
                (f"test_{who}_{tag}@example.com", "not-a-real-hash"),
            )
            user_ids.append(cur.fetchone()[0])
        user_a, user_b = user_ids

        # =============================================================
        # happy path
        # =============================================================
        food_id = add_manual_food(conn, user_a, "  Grandma's chili  ",
                                  120, 8.5, 10, 5,
                                  brand="Home", barcode=f"test{tag}")
        check("returns an int id", isinstance(food_id, int))

        cur.execute(
            "select user_id, name, brand, barcode, kcal, protein_g, "
            "carbs_g, fat_g from foods_manual where id = %s",
            (food_id,),
        )
        uid, name, brand, barcode, kcal, p, c, f = cur.fetchone()
        check("owned by user_a", uid == user_a)
        check("name is trimmed", name == "Grandma's chili")
        check("brand stored", brand == "Home")
        check("barcode stored", barcode == f"test{tag}")
        check("kcal stored", close(kcal, 120))
        check("protein stored", close(p, 8.5))
        check("carbs stored", close(c, 10))
        check("fat stored", close(f, 5))

        # optional fields: blank becomes NULL
        bare_id = add_manual_food(conn, user_a, "Plain rice", 130, 2.7, 28, 0.3,
                                  brand="   ", barcode="")
        cur.execute("select brand, barcode from foods_manual where id = %s",
                    (bare_id,))
        check("blank brand/barcode stored as NULL",
              cur.fetchone() == (None, None))

        # =============================================================
        # visibility through the foods view
        # =============================================================
        cur.execute(
            "select count(*) from foods where id = %s and origin = 'manual' "
            "and user_id = %s",
            (food_id, user_a),
        )
        check("visible in foods view as manual, owned by user_a",
              cur.fetchone()[0] == 1)

        cur.execute(
            "select count(*) from foods where id = %s and origin = 'manual' "
            "and (origin = 'source' or user_id = %s)",
            (food_id, user_b),
        )
        check("hidden from user_b under the ownership filter",
              cur.fetchone()[0] == 0)

        # =============================================================
        # rejections
        # =============================================================
        expect_value_error("rejects empty name",
            lambda: add_manual_food(conn, user_b, "   ", 100, 1, 1, 1))
        expect_value_error("rejects None name",
            lambda: add_manual_food(conn, user_b, None, 100, 1, 1, 1))
        expect_value_error("rejects negative kcal",
            lambda: add_manual_food(conn, user_b, "x", -1, 1, 1, 1))
        expect_value_error("rejects kcal over 900",
            lambda: add_manual_food(conn, user_b, "x", 901, 1, 1, 1))
        expect_value_error("rejects protein over 100",
            lambda: add_manual_food(conn, user_b, "x", 100, 101, 0, 0))
        expect_value_error("rejects macros summing over 100 g",
            lambda: add_manual_food(conn, user_b, "x", 500, 40, 40, 40))
        expect_value_error("rejects None macro",
            lambda: add_manual_food(conn, user_b, "x", 100, None, 1, 1))
        expect_value_error("rejects string macro",
            lambda: add_manual_food(conn, user_b, "x", "100", 1, 1, 1))
        expect_value_error("rejects bool macro",
            lambda: add_manual_food(conn, user_b, "x", True, 1, 1, 1))
        expect_value_error("rejects non-int user_id",
            lambda: add_manual_food(conn, str(user_b), "x", 100, 1, 1, 1))
        expect_value_error("rejects nonexistent user",
            lambda: add_manual_food(conn, -1, "x", 100, 1, 1, 1))

        cur.execute("select count(*) from foods_manual where user_id = %s",
                    (user_b,))
        check("rejected inputs left no partial writes",
              cur.fetchone()[0] == 0)

        # edge: macros summing to exactly 100 are allowed
        edge_id = add_manual_food(conn, user_b, "Edge", 400, 33.4, 33.3, 33.3)
        check("macros summing to exactly 100 g accepted",
              isinstance(edge_id, int))

    finally:
        cur.execute("delete from foods_manual where user_id = any(%s)",
                    (user_ids,))
        cur.execute("delete from users where id = any(%s)", (user_ids,))
        conn.close()

    print(f"\n{passed} passed, {failed} failed")


if __name__ == "__main__":
    main()
