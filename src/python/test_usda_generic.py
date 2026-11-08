"""
@file test_usda_generic.py
Phase 8b - tests for usda_generic_load.py, end to end against the real
database, with USDA's zip files replaced by small fake ones (no network).

Checks: SR Legacy + Foundation foods loaded with per-100 g macros, nutrient
fallbacks (Atwater kcal, carbs by summation, NLEA fat), lab-record rows
excluded, outliers nulled, quoted CSV fields, rerun = no changes and same
ids, old non-food / duplicate rows removed unless something references
them, a bad file header fails cleanly with nothing written, and generic
foods rank ahead of branded ones in search. All test rows are removed.

Run: python src/python/test_usda_generic.py
@author Tony Shin <tonyshin4065@gmail.com>
"""

import csv
import io
import pathlib
import shutil
import tempfile
import uuid
import zipfile

import psycopg

import usda_generic_load as job
from meal_logging import search_foods

passed = 0
failed = 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"PASS  {label}")
    else:
        failed += 1
        print(f"FAIL  {label} {detail}")


def close(a, b, tol=1e-6):
    return a is not None and abs(a - b) < tol


tag = uuid.uuid4().hex[:8]
n = str(int(tag, 16) % 10**5).zfill(5)
fid = lambda k: f"9{n}{k:03d}"                      # fake fdc_ids
tmp = pathlib.Path(tempfile.mkdtemp(prefix="usda_test_"))


def csv_text(header, rows, bom=False):
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")   # FDC quotes every field
    w.writerow(header)
    w.writerows(rows)
    return ("﻿" if bom else "") + buf.getvalue()


def make_zip(name, folder, food_rows, nutrient_rows, food_header=None, nutrient_header=None, bom=False):
    food_header = food_header or ["fdc_id", "data_type", "description", "food_category_id", "publication_date"]
    nutrient_header = nutrient_header or ["id", "fdc_id", "nutrient_id", "amount", "data_points",
                                          "derivation_id", "min", "max", "median", "footnote",
                                          "min_year_acquired"]
    with zipfile.ZipFile(tmp / name, "w") as z:
        z.writestr(f"{folder}/food.csv", csv_text(food_header, food_rows, bom))
        z.writestr(f"{folder}/food_nutrient.csv", csv_text(nutrient_header, nutrient_rows, bom))
        z.writestr(f"{folder}/nutrient.csv", "ignored\n")
    return name


def nut(rows, width=11):
    """[(fdc_id, nutrient_id, amount), ...] -> food_nutrient rows of `width` fields"""
    return [[str(i), f, nid, amt] + [""] * (width - 4) for i, (f, nid, amt) in enumerate(rows, 1)]


SR = f"sr_{tag}.zip"
FD = f"foundation_{tag}.zip"
make_zip(SR, "FoodData_Central_sr_legacy_food_csv_2018-04",
    [[fid(1), "sr_legacy_food", f"Bananas, raw {tag}", "9", "2019-04-01"],
     [fid(2), "sr_legacy_food", f'Cheese, cheddar, "sharp" {tag}', "1", "2019-04-01"],
     [fid(3), "sr_legacy_food", f"No nutrients {tag}", "1", "2019-04-01"],
     [fid(4), "sr_legacy_food", f"Impossible {tag}", "1", "2019-04-01"]],
    nut([(fid(1), "1008", "89"), (fid(1), "1003", "1.09"), (fid(1), "1005", "22.84"), (fid(1), "1004", "0.33"),
         (fid(1), "1079", "2.6"),                                   # fiber: ignored
         (fid(2), "1008", "403"), (fid(2), "1003", "24.9"), (fid(2), "1005", "1.28"), (fid(2), "1004", "33.1"),
         (fid(4), "1008", "5000"), (fid(4), "1003", "-3"), (fid(4), "1005", "abc"), (fid(4), "1004", "10")]))
make_zip(FD, "FoodData_Central_foundation_food_csv_2026-10-29",
    [[fid(10), "foundation_food", f"Bananas, overripe, raw {tag}", "9", "2020-10-30"],
     [fid(11), "sample_food", f"BANANAS, RIPE {tag}", "9", "2020-10-30"],          # lab record
     [fid(12), "foundation_food", f"Milk, whole {tag}", "1", "2020-10-30"]],
    nut([(fid(10), "2047", "85"), (fid(10), "2048", "89"), (fid(10), "1003", "0.73"),
         (fid(10), "1050", "20.1"), (fid(10), "1085", "0.22"),           # Atwater kcal, carbs by summation, NLEA fat
         (fid(11), "1008", "90"),
         (fid(12), "1008", "61"), (fid(12), "2047", "70"), (fid(12), "1003", "3.27"),
         (fid(12), "1005", "4.63"), (fid(12), "1050", "9.9"), (fid(12), "1004", "3.2")], width=13),
    food_header=["fdc_id", "data_type", "description", "food_category_id", "publication_date"],
    nutrient_header=["id", "fdc_id", "nutrient_id", "amount", "data_points", "derivation_id",
                     "min", "max", "median", "loq", "footnote", "min_year_acquired", "percent_daily_value"],
    bom=True)

job.DATASETS = {"sr_legacy": SR, "foundation": FD}
job.download = lambda name: tmp / name

conn = psycopg.connect(job.DSN)
log_conn = psycopg.connect(job.DSN, autocommit=True)
cur = log_conn.cursor()


def usda_row(source_id):
    cur.execute("select id, name, kcal, protein_g, carbs_g, fat_g, calorie_check, barcode "
                "from foods_source where source = 'usda' and source_id = %s", (source_id,))
    return cur.fetchone()


def run(label=None):
    return job.load(conn, log_conn, ["sr_legacy", "foundation"])


usda_food_ids = []
try:
    # ---- the original bronze table has the old rows' descriptions ----
    have_usda_food = cur.execute("select to_regclass('usda_food') is not null").fetchone()[0]
    if have_usda_food:
        cols = {r[0] for r in cur.execute(
            "select column_name from information_schema.columns where table_name = 'usda_food'")}
        old = [(fid(50), "sub_sample_food", f"BANANAS, RIPE {tag}"),
               (fid(51), "foundation_food", f"Old foundation {tag}"),
               (fid(52), "market_acquisition", f"Referenced sample {tag}"),
               (fid(53), "sample_food", f"Also branded {tag}"),
               (fid(54), "branded_food", f"Also branded {tag}")]
        for f, dtype, desc in old:
            if "loaded_at" in cols:
                cur.execute("insert into usda_food (fdc_id, data_type, description, loaded_at) "
                            "values (%s, %s, %s, now())", (f, dtype, desc))
            else:
                cur.execute("insert into usda_food (fdc_id, data_type, description) values (%s, %s, %s)",
                            (f, dtype, desc))
            usda_food_ids.append(f)

    # ---- old rows in foods_source, as the original pipeline left them ----
    def old_row(name):
        return cur.execute("insert into foods_source (barcode, name, source, loaded_at) "
                           "values (null, %s, 'usda', now()) returning id", (name,)).fetchone()[0]
    junk_id = old_row(f"BANANAS, RIPE {tag}")
    old_foundation_id = old_row(f"Old foundation {tag}")
    referenced_id = old_row(f"Referenced sample {tag}")
    branded_name_id = old_row(f"Also branded {tag}")
    # a recipe points at one of them: it must survive the cleanup
    user_id = cur.execute("insert into users (email, password) values (%s, 'x') returning id",
                          (f"usda_{tag}@example.com",)).fetchone()[0]
    recipe_id = cur.execute("insert into recipes (user_id, name, yield_portions) values (%s, 'r', 1) "
                            "returning id", (user_id,)).fetchone()[0]
    cur.execute("insert into recipe_items (recipe_id, food_id, food_origin, grams) "
                "values (%s, %s, 'source', 100)", (recipe_id, referenced_id))

    # =============================================================
    # first load
    # =============================================================
    loaded = run()
    r = usda_row(fid(1))
    check("SR Legacy food loaded", r is not None and r[1] == f"Bananas, raw {tag}", r)
    check("per-100 g macros from nutrients 1008/1003/1005/1004",
          close(r[2], 89) and close(r[3], 1.09) and close(r[4], 22.84) and close(r[5], 0.33), r)
    check("no barcode on generic foods", r[7] is None, r)
    check("calorie_check TRUE (89 vs 4/4/9 = 98.7, within 20%)", r[6] is True, r)
    check("quoted description with commas and quotes", usda_row(fid(2))[1] == f'Cheese, cheddar, "sharp" {tag}')
    r = usda_row(fid(3))
    check("food with no nutrient rows kept, macros NULL", r is not None and r[2] is None and r[3] is None, r)
    r = usda_row(fid(4))
    check("kcal 5000 nulled, negative protein and non-numeric carbs -> NULL",
          r[2] is None and r[3] is None and r[4] is None and close(r[5], 10), r)

    r = usda_row(fid(10))
    check("Foundation: Atwater-specific kcal (2048) preferred over general (2047)", close(r[2], 89), r)
    check("Foundation: carbs by summation (1050) when 1005 missing", close(r[4], 20.1), r)
    check("Foundation: NLEA fat (1085) when 1004 missing", close(r[5], 0.22), r)
    r = usda_row(fid(12))
    check("1008 kcal preferred over Atwater; 1005 carbs over 1050",
          close(r[2], 61) and close(r[4], 4.63), r)
    check("lab record (sample_food) excluded", usda_row(fid(11)) is None)
    check("BOM + extra columns (loq, percent_daily_value) handled", usda_row(fid(12)) is not None)
    check("rows added = 6 foods (4 SR Legacy + 2 Foundation)", loaded == 6, loaded)

    if have_usda_food:
        exists = lambda i: cur.execute("select 1 from foods_source where id = %s", (i,)).fetchone() is not None
        check("old lab-record row removed", not exists(junk_id))
        check("old macro-less Foundation duplicate removed", not exists(old_foundation_id))
        check("row referenced by a recipe kept", exists(referenced_id))
        check("name that is also a branded food kept", exists(branded_name_id))
    else:
        print("SKIP  cleanup checks (no usda_food table)")

    run_row = cur.execute("select status, rows_loaded, note from pipeline_runs "
                          "where file_name like %s order by id desc limit 1", (f"%{tag}%",)).fetchone()
    check("run logged as success with a summary note",
          run_row[0] == "success" and "generic foods" in run_row[2], run_row)

    # =============================================================
    # rerun: nothing changes, ids stay
    # =============================================================
    banana_id = usda_row(fid(1))[0]
    check("rerun writes nothing", run() == 0)
    check("rerun keeps ids", usda_row(fid(1))[0] == banana_id)
    cur.execute("select count(*) from foods_source where source = 'usda' and source_id like %s",
                (f"9{n}%",))
    check("rerun adds no duplicates (still 6 foods)", cur.fetchone()[0] == 6)

    # a changed value updates in place
    make_zip(SR, "x", [[fid(1), "sr_legacy_food", f"Bananas, raw {tag}", "9", "2019-04-01"]],
             nut([(fid(1), "1008", "90"), (fid(1), "1003", "1.1"), (fid(1), "1005", "23"), (fid(1), "1004", "0.3")]))
    run()
    r = usda_row(fid(1))
    check("changed values update in place (same id)", r[0] == banana_id and close(r[2], 90), r)

    # =============================================================
    # search ranking: generic before branded exact match
    # =============================================================
    term = f"zzgen{tag}"
    cur.execute("insert into foods_source (barcode, name, source, kcal, protein_g, carbs_g, fat_g, loaded_at) "
                "values (%s, %s, 'off', 100, 1, 1, 1, now())", (f"98{n}777", term))
    cur.execute("insert into foods_source (barcode, name, source, source_id, kcal, protein_g, carbs_g, fat_g, loaded_at) "
                "values (null, %s, 'usda', %s, 100, 1, 1, 1, now())", (f"{term}s, raw", fid(99)))
    names = [row[1] for row in search_foods(conn, term, user_id)]
    conn.rollback()
    check("generic food ranks above a branded exact match",
          names[:2] == [f"{term}s, raw", term], names)

    # =============================================================
    # bad header: fails cleanly, nothing written
    # =============================================================
    before = cur.execute("select count(*) from foods_source where source = 'usda'").fetchone()[0]
    make_zip(SR, "x", [[fid(5), "sr_legacy_food", f"Never loaded {tag}", "1", "x", "surprise"]], [],
             food_header=["fdc_id", "data_type", "description", "food_category_id", "publication_date", "new_column"])
    try:
        run()
        check("unknown column raises", False, "no error")
    except RuntimeError as e:
        check("unknown column raises a clear error", "new_column" in str(e), str(e))
    conn.rollback()
    check("nothing written by the failed load",
          cur.execute("select count(*) from foods_source where source = 'usda'").fetchone()[0] == before)
    check("failed run logged",
          cur.execute("select status from pipeline_runs where file_name like %s order by id desc limit 1",
                      (f"%{tag}%",)).fetchone()[0] == "failed")

finally:
    conn.rollback()
    cur.execute("delete from recipe_items where recipe_id in (select id from recipes where name = 'r' "
                "and user_id in (select id from users where email = %s))", (f"usda_{tag}@example.com",))
    cur.execute("delete from recipes where user_id in (select id from users where email = %s)",
                (f"usda_{tag}@example.com",))
    cur.execute("delete from users where email = %s", (f"usda_{tag}@example.com",))
    cur.execute("delete from foods_source where name like %s or source_id like %s or barcode = %s",
                (f"%{tag}%", f"9{n}%", f"98{n}777"))
    if usda_food_ids:
        cur.execute("delete from usda_food where fdc_id = any(%s)", (usda_food_ids,))
    cur.execute("delete from pipeline_runs where file_name like %s", (f"%{tag}%",))
    conn.close()
    log_conn.close()
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{passed} passed, {failed} failed")
