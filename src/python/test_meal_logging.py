"""
@file test_meal_logging.py
Tests the meal_logging
@author Claude Code & Tony Shin <tonyshin4065@gmail.com>
"""

import datetime
import psycopg
from meal_logging import log_ad_hoc_meal

# use the same dbname/user you use in your other scripts
conn = psycopg.connect(dbname="meal_tracker", user="tonyyshin", autocommit=True)
today = datetime.date.today()

with conn.cursor() as cur:
        cur.execute("select id from users order by id limit 1;")
        row = cur.fetchone()
        if row is None:
                raise SystemExit("no users in the users table, create one first")
        user_id = row[0]

        cur.execute("select count(*) from meal_log;")
        before = cur.fetchone()[0]

# Test 1: happy path
print("Test 1: happy path")
with conn.cursor() as cur:
        cur.execute("""
                select id, origin, name, kcal, protein_g from foods
                where origin = 'source'
                        and kcal is not null and protein_g is not null
                        and carbs_g is not null and fat_g is not null
                limit 2;
        """)
        good = cur.fetchall()

for food_id, origin, name, kcal, protein in good:
        print(f"  using {food_id} {name!r}: {kcal} kcal / {protein} g protein per 100g")

items = [(good[0][0], good[0][1], 150.0), (good[1][0], good[1][1], 80.0)]
expected_kcal = good[0][3] * 150 / 100 + good[1][3] * 80 / 100

meal_id = log_ad_hoc_meal(conn, user_id, today, "test meal", items)
print("  logged meal_log id:", meal_id)

with conn.cursor() as cur:
        cur.execute("select source_type, kcal, protein_g, carbs_g, fat_g from meal_log where id = %s;", (meal_id,))
        header = cur.fetchone()
        print("  header:", header)
        print(f"  expected kcal: {expected_kcal:.2f}, saved kcal: {header[1]:.2f}")

        cur.execute("select count(*) from meal_log_items where meal_log_id = %s;", (meal_id,))
        print("  item rows:", cur.fetchone()[0], "(expected 2)")

# ---------- Test 2: missing macros should fail ----------
print("=== Test 2: missing macros ===")
with conn.cursor() as cur:
        cur.execute("""
                select id from foods_source
                where kcal is null or protein_g is null or carbs_g is null or fat_g is null
                limit 1;
        """)
        row = cur.fetchone()

if row is None:
        print("  skipped: no foods with missing macros in foods_source")
else:
        try:
                log_ad_hoc_meal(conn, user_id, today, "should fail", [(good[0][0], "source", 100.0), (row[0], "source", 50.0)])
                print("  FAIL: did not raise")
        except ValueError as e:
                print("  PASS: raised:", e)

# ---------- Test 3: food that doesn't exist should fail ----------
print("=== Test 3: bad reference ===")
try:
        log_ad_hoc_meal(conn, user_id, today, "should fail", [(999999999, "manual", 100.0)])
        print("  FAIL: did not raise")
except ValueError as e:
        print("  PASS: raised:", e)

# ---------- Test 4: bad grams should fail ----------
print("=== Test 4: bad grams ===")
try:
        log_ad_hoc_meal(conn, user_id, today, "should fail", [(good[0][0], "source", -50.0)])
        print("  FAIL: did not raise")
except ValueError as e:
        print("  PASS: raised:", e)

# ---------- Check failures wrote nothing ----------
with conn.cursor() as cur:
        cur.execute("select count(*) from meal_log;")
        after = cur.fetchone()[0]
print("=== Failures wrote nothing:", after - before == 1, "===")   # only Test 1's meal should be new

# ---------- Cleanup ----------
with conn.transaction():
        with conn.cursor() as cur:
                cur.execute("delete from meal_log_items where meal_log_id = %s;", (meal_id,))
                cur.execute("delete from meal_log where id = %s;", (meal_id,))
print("cleaned up test meal", meal_id)

conn.close()
