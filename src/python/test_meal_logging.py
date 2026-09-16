"""
@file test_meal_logging.py
Tests everything in meal_logging: search_foods, log_ad_hoc_meal, get_daily_rollup.
Uses January 1999 dates so real log data is never touched, creates a temp
second user and three foods_manual rows, and removes all of it at the end.
@author Claude & Tony Shin <tonyshin4065@gmail.com>
"""

import datetime
import sys
import uuid
import psycopg
from meal_logging import search_foods, log_ad_hoc_meal, get_daily_rollup

LOG_DATE = datetime.date(1999, 1, 10)           # log_ad_hoc_meal tests
ROLLUP_DATE = datetime.date(1999, 1, 15)        # get_daily_rollup tests
ADJACENT_DATE = datetime.date(1999, 1, 16)
EMPTY_DATE = datetime.date(1999, 1, 20)
TEST_DATES = [LOG_DATE, ROLLUP_DATE, ADJACENT_DATE, EMPTY_DATE]
MACROS = ("kcal", "protein_g", "carbs_g", "fat_g")
TOL = 1e-6

failures = 0


def check(label, condition, detail=""):
        global failures
        if condition:
                print(f"  PASS: {label}")
        else:
                failures += 1
                print(f"  FAIL: {label}  {detail}")


def close_all(got, expected):
        return all(abs(g - e) < TOL for g, e in zip(got, expected))


def count_rows(cur, user_id, log_date):
        cur.execute("""
                select (select count(*) from meal_log
                        where user_id = %s and log_date = %s),
                       (select count(*) from meal_log_items mli
                        join meal_log ml on ml.id = mli.meal_log_id
                        where ml.user_id = %s and ml.log_date = %s);
        """, (user_id, log_date, user_id, log_date))
        return cur.fetchone()


def expect_rejected(cur, label, user_id, items):
        """bad input must raise ValueError AND write nothing"""
        before = count_rows(cur, user_id, LOG_DATE)
        try:
                log_ad_hoc_meal(conn, user_id, LOG_DATE, "should fail", items)
                raised = "did not raise"
        except ValueError as e:
                raised = None
                msg = str(e)
        except Exception as e:
                raised = f"raised {type(e).__name__} instead of ValueError: {e}"
        after = count_rows(cur, user_id, LOG_DATE)
        check(f"{label} -> ValueError" + ("" if raised else f" ({msg})"),
              raised is None, raised or "")
        check(f"{label} -> nothing written", before == after,
              f"rows before {before}, after {after}")


def macro_lookup(cur, food_id, origin):
        cur.execute("""
                select kcal, protein_g, carbs_g, fat_g from foods
                where id = %s and origin = %s;
        """, (food_id, origin))
        return cur.fetchone()


def expected(cur, items):
        totals = [0.0] * 4
        for food_id, origin, grams in items:
                for i, v in enumerate(macro_lookup(cur, food_id, origin)):
                        totals[i] += v * grams / 100.0
        return totals


conn = psycopg.connect(dbname="meal_tracker", user="tonyyshin", autocommit=True)
cur = conn.cursor()

# ---------- setup ----------
cur.execute("select id from users order by id limit 1;")
row = cur.fetchone()
if row is None:
        raise SystemExit("no users in the users table, create one first")
user_id = row[0]

cur.execute("select count(*) from meal_log where user_id = %s and log_date = any(%s);",
            (user_id, TEST_DATES))
if cur.fetchone()[0] > 0:
        raise SystemExit("test dates already have meal_log rows for this user, aborting")

# password column name from the catalog, not guessed
cur.execute("""
        select column_name from information_schema.columns
        where table_name = 'users' and column_name in ('password', 'password_hash');
""")
pw_col = cur.fetchone()[0]

tag = uuid.uuid4().hex[:8]
other_user_id = None
manual_ids = []

try:
        cur.execute(f"insert into users (email, {pw_col}) values (%s, %s) returning id;",
                    (f"meal_logging_test_{tag}@example.com", "not-a-real-hash"))
        other_user_id = cur.fetchone()[0]

        # unique term so only this run's manual rows can match it
        term = f"zztest{tag}"
        mine_name = f"{term} mine"
        theirs_name = f"{term} theirs"
        insert_manual = """
                insert into foods_manual (user_id, name, kcal, protein_g, carbs_g, fat_g)
                values (%s, %s, %s, %s, %s, %s) returning id;
        """
        cur.execute(insert_manual, (user_id, mine_name, 200.0, 10.0, 20.0, 5.0))
        mine_id = cur.fetchone()[0]
        cur.execute(insert_manual, (other_user_id, theirs_name, 100.0, 5.0, 5.0, 5.0))
        theirs_id = cur.fetchone()[0]
        cur.execute(insert_manual, (user_id, f"{term} nomacro", None, None, None, None))
        nomacro_id = cur.fetchone()[0]
        manual_ids = [mine_id, theirs_id, nomacro_id]

        # source foods with full macros, ids above every manual id so
        # (id, 'manual') is guaranteed not to exist
        cur.execute("""
                select id from foods_source
                where kcal is not null and protein_g is not null
                        and carbs_g is not null and fat_g is not null
                        and id > (select coalesce(max(id), 0) + 1000 from foods_manual)
                limit 2;
        """)
        src1_id, src2_id = [r[0] for r in cur.fetchall()]

        # ================= search_foods =================
        print("=== search_foods ===")
        rows = search_foods(conn, "chicken", user_id)
        check("common term returns results", len(rows) > 0)
        check("results capped at 20", len(rows) <= 20, f"got {len(rows)}")
        check("every row matches the term",
              all(any(isinstance(v, str) and "chicken" in v.lower() for v in r) for r in rows))

        rows = search_foods(conn, term.upper(), user_id)
        names = [v for r in rows for v in r if isinstance(v, str)]
        check("own manual food visible (upper-case term, ILIKE)", mine_name in names, names)
        check("other user's manual food hidden", theirs_name not in names, names)

        rows = search_foods(conn, term, other_user_id)
        names = [v for r in rows for v in r if isinstance(v, str)]
        check("other user sees only their own manual food",
              theirs_name in names and mine_name not in names, names)

        rows = search_foods(conn, f"{tag}nomatch'; drop table users; --", user_id)
        check("injection-shaped term returns nothing", len(rows) == 0)
        cur.execute("select to_regclass('users') is not null;")
        check("users table still exists", cur.fetchone()[0])

        # ================= log_ad_hoc_meal =================
        print("=== log_ad_hoc_meal ===")
        happy_items = [(src1_id, "source", 150.0), (mine_id, "manual", 100.0)]
        meal_id = log_ad_hoc_meal(conn, user_id, LOG_DATE, "happy path", happy_items)
        check("returns an id", isinstance(meal_id, int), repr(meal_id))

        cur.execute("""
                select user_id, log_date, meal_name, source_type, recipe_id,
                       kcal, protein_g, carbs_g, fat_g
                from meal_log where id = %s;
        """, (meal_id,))
        uid, ldate, mname, stype, rid, *snap = cur.fetchone()
        check("header user/date/name correct",
              (uid, ldate, mname) == (user_id, LOG_DATE, "happy path"),
              (uid, ldate, mname))
        check("source_type 'ad_hoc', recipe_id null",
              stype == "ad_hoc" and rid is None, (stype, rid))
        want = expected(cur, happy_items)
        check("snapshot macros match hand-computed (source + manual)",
              close_all(snap, want), f"saved {snap}, expected {want}")

        cur.execute("select food_id, food_origin, grams from meal_log_items where meal_log_id = %s;",
                    (meal_id,))
        saved = sorted((f, o, float(g)) for f, o, g in cur.fetchall())
        check("meal_log_items match input", saved == sorted(happy_items), saved)

        expect_rejected(cur, "missing macros", user_id, [(nomacro_id, "manual", 100.0)])
        expect_rejected(cur, "nonexistent food", user_id, [(999999999, "manual", 100.0)])
        expect_rejected(cur, "source id labeled 'manual'", user_id, [(src1_id, "manual", 100.0)])
        expect_rejected(cur, "other user's manual food", user_id, [(theirs_id, "manual", 100.0)])
        expect_rejected(cur, "zero grams", user_id, [(src1_id, "source", 0.0)])
        expect_rejected(cur, "negative grams", user_id, [(src1_id, "source", -50.0)])
        expect_rejected(cur, "empty item list", user_id, [])
        expect_rejected(cur, "good item + bad item", user_id,
                        [(src1_id, "source", 100.0), (999999999, "source", 50.0)])

        # ================= get_daily_rollup =================
        print("=== get_daily_rollup ===")
        r = get_daily_rollup(conn, user_id, EMPTY_DATE)
        check("empty day: totals all 0", all(r[k] == 0 for k in MACROS), r)
        check("empty day: meal_names == []", r["meal_names"] == [], r["meal_names"])

        meal_a = [(src1_id, "source", 150.0)]
        meal_b = [(src2_id, "source", 80.0), (mine_id, "manual", 50.0)]
        exp_day = [a + b for a, b in zip(expected(cur, meal_a), expected(cur, meal_b))]

        log_ad_hoc_meal(conn, user_id, ROLLUP_DATE, "rollup lunch", meal_a)
        log_ad_hoc_meal(conn, user_id, ROLLUP_DATE, "rollup dinner", meal_b)
        log_ad_hoc_meal(conn, other_user_id, ROLLUP_DATE, "other user meal", meal_a)
        log_ad_hoc_meal(conn, user_id, ADJACENT_DATE, "next day meal", meal_a)
        log_ad_hoc_meal(conn, user_id, ADJACENT_DATE, None, meal_a)

        r = get_daily_rollup(conn, user_id, ROLLUP_DATE)
        got = [r[k] for k in MACROS]
        check("two meals: totals match hand-computed sum",
              close_all(got, exp_day), f"got {got}, expected {exp_day}")
        check("two meals: names in log order, other user + next day excluded",
              r["meal_names"] == ["rollup lunch", "rollup dinner"], r["meal_names"])

        r = get_daily_rollup(conn, other_user_id, ROLLUP_DATE)
        check("other user sees only their own meal",
              r["meal_names"] == ["other user meal"]
              and close_all([r[k] for k in MACROS], expected(cur, meal_a)), r)

        r = get_daily_rollup(conn, user_id, ADJACENT_DATE)
        check("null meal_name comes back as 'Untitled'",
              r["meal_names"] == ["next day meal", "Untitled"], r["meal_names"])

except Exception as e:
        failures += 1
        print(f"  CRASH: {type(e).__name__}: {e}")

finally:
        # ---------- cleanup: items -> headers -> manual foods -> temp user ----------
        ids = [user_id] + ([other_user_id] if other_user_id else [])
        with conn.transaction():
                cur.execute("""
                        delete from meal_log_items where meal_log_id in (
                                select id from meal_log
                                where user_id = any(%s) and log_date = any(%s));
                """, (ids, TEST_DATES))
                cur.execute("delete from meal_log where user_id = any(%s) and log_date = any(%s);",
                            (ids, TEST_DATES))
                if manual_ids:
                        cur.execute("delete from foods_manual where id = any(%s);", (manual_ids,))
                if other_user_id:
                        cur.execute("delete from users where id = %s;", (other_user_id,))
        print("cleaned up test meals, manual foods, and temp user")
        conn.close()

print()
print("=== ALL PASSED ===" if failures == 0 else f"=== {failures} FAILURE(S) ===")
sys.exit(1 if failures else 0)
