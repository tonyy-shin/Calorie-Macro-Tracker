"""
Phase 8b - USDA generic foods (SR Legacy + Foundation Foods)

Loads USDA's plain, unbranded foods ("Bananas, raw", "Milk, whole, 3.25%
milkfat", "Egg, whole, raw, fresh") into foods_source, so everyday
ingredients are easy to find. One-time job; safe to rerun (e.g. when USDA
publishes a new Foundation Foods release): it upserts by USDA's fdc_id, so
existing rows keep their ids and a rerun with no changes writes nothing.

    python src/python/usda_generic_load.py                     # SR Legacy (default)
    python src/python/usda_generic_load.py --only foundation   # see note below

Foundation Foods: the 2026-10-29 release ships no food.csv / food_nutrient.csv
(only lab and sample files), so it can't be loaded from that zip. SR Legacy
already covers the same everyday foods. If a later release includes those two
files again, update DATASETS["foundation"] and run with --only foundation.

Can run while an Open Food Facts update is running: it uses its own bronze
and silver tables and only adds rows without barcodes.

Python only moves bytes: download the zip, stream food.csv and
food_nutrient.csv into bronze with COPY, run the .sql files, log the run.

@author Tony Shin <tonyshin4065@gmail.com>
"""

import argparse
import csv
import datetime as dt
import io
import os
import pathlib
import sys
import traceback
import zipfile

import psycopg
import requests

REPO = pathlib.Path(__file__).resolve().parents[2]
SQL_DIR = REPO / "src" / "sql"
DATA_DIR = REPO / "data" / "usda"                 # gitignored

BASE = "https://fdc.nal.usda.gov/fdc-datasets/"
# Files from https://fdc.nal.usda.gov/download-datasets/
# SR Legacy is final (2018) and will never change. Foundation Foods gets new
# releases; the 2026-10-29 one lacks food.csv / food_nutrient.csv (see above).
DATASETS = {
    "sr_legacy": "FoodData_Central_sr_legacy_food_csv_2018-04.zip",
    "foundation": "FoodData_Central_foundation_food_csv_2026-10-29.zip",
}
USER_AGENT = "CalorieMacroTracker/0.1 (https://github.com/tonyy-shin/Calorie-Macro-Tracker)"
DSN = os.environ.get("MEAL_TRACKER_DSN", "dbname=meal_tracker user=tonyyshin")
LOCK_ID = 80_250_002          # one USDA load at a time (OFF jobs use 80_250_001)

SETUP_STEPS = [
    "app/create_pipeline_runs.sql",
    "gold/add_foods_source_source_id.sql",
]
BRONZE = "bronze/create_usda_generic.sql"
TRANSFORM_STEPS = [
    "silver/create_usda_generic_silver.sql",
    "silver/null_usda_generic_outliers.sql",
    "silver/add_usda_generic_calorie_check.sql",
    "gold/upsert_usda_generic.sql",             # must stay last: its rowcount is used
]
# Needs the original Phase 1 bronze table usda_food; skipped if it's absent.
CLEANUP = "gold/remove_usda_non_food_rows.sql"
FILES = {"food.csv": "usda_generic_food",
         "food_nutrient.csv": "usda_generic_food_nutrient"}


def log(msg):
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def download(name):
    """Download a dataset zip once; reuse it if already there."""
    dest = DATA_DIR / name
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with requests.get(BASE + name, headers={"User-Agent": USER_AGENT},
                      stream=True, timeout=(15, 300)) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.rename(dest)
    return dest


def run_sql(cur, relpath):
    cur.execute((SQL_DIR / relpath).read_text())


def table_columns(cur, table):
    cur.execute("select column_name from information_schema.columns "
                "where table_name = %s order by ordinal_position", (table,))
    return [r[0] for r in cur.fetchall()]


def copy_member(cur, zf, member, table):
    """COPY one CSV from the zip into a bronze table using the file's own
    header as the column list. HEADER MATCH makes Postgres verify it."""
    with zf.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        header = next(csv.reader([text.readline()]))
        known = set(table_columns(cur, table))
        unknown = [c for c in header if c not in known]
        if unknown:
            raise RuntimeError(f"{member}: columns {unknown} aren't in {table}; "
                               f"file header is {header}")
        cols = ", ".join(header)
        with cur.copy(f"COPY {table} ({cols}) FROM STDIN "
                      "WITH (FORMAT csv, HEADER MATCH)") as copy:
            copy.write(",".join(f'"{c}"' if "," in c else c for c in header) + "\n")
            while chunk := text.read(1 << 20):
                copy.write(chunk)
    cur.execute(f"select count(*) from {table}")
    return cur.fetchone()[0]


def find(zf, filename):
    matches = [m for m in zf.namelist() if m.rsplit("/", 1)[-1] == filename]
    if not matches:
        listing = "\n  ".join(zf.namelist()[:40])
        raise RuntimeError(f"{filename} not found in {zf.filename}. The zip contains:\n  {listing}")
    return matches[0]


def load(conn, log_conn, datasets):
    run_id = log_conn.execute(
        "insert into pipeline_runs (source, run_type, file_name, status) "
        "values ('usda', 'backfill', %s, 'running') returning id",
        (", ".join(DATASETS[d] for d in datasets),)).fetchone()[0]
    try:
        # downloads first, outside any transaction
        paths = {d: download(DATASETS[d]) for d in datasets}
        # setup adds a column / index to foods_source: that briefly locks the
        # table, so it gets its own short transaction instead of holding the
        # lock for the whole load (which would freeze the app meanwhile)
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("set local lock_timeout = '10min'")
            for step in SETUP_STEPS:
                run_sql(cur, step)
        with conn.transaction(), conn.cursor() as cur:       # all or nothing
            run_sql(cur, BRONZE)
            for d in datasets:
                with zipfile.ZipFile(paths[d]) as zf:
                    for filename, table in FILES.items():
                        n = copy_member(cur, zf, find(zf, filename), table)
                        log(f"{d}: {filename} -> {table} ({n:,} rows so far)")
                cur.execute("update usda_generic_food set dataset = %s where dataset is null", (d,))
            cur.execute("select count(*) from usda_generic_food")
            read = cur.fetchone()[0]
            for step in TRANSFORM_STEPS:
                run_sql(cur, step)
            loaded = cur.rowcount
            removed = 0
            cur.execute("select to_regclass('usda_food') is not null")
            if cur.fetchone()[0]:
                run_sql(cur, CLEANUP)
                removed = cur.rowcount
            cur.execute("select count(*), count(*) filter (where kcal is not null "
                        "and protein_g is not null and carbs_g is not null "
                        "and fat_g is not null) from usda_generic_silver")
            foods, complete = cur.fetchone()
        log_conn.execute(
            "update pipeline_runs set status = 'success', rows_read = %s, rows_loaded = %s, "
            "note = %s, finished_at = now() where id = %s",
            (read, loaded, f"{foods:,} generic foods, {complete:,} with all four macros; "
                           f"{removed:,} old non-food / duplicate rows removed", run_id))
        log(f"done: {foods:,} generic foods ({complete:,} with all four macros), "
            f"{loaded:,} rows added or changed, {removed:,} old non-food rows removed")
        return loaded
    except BaseException as e:
        log_conn.execute(
            "update pipeline_runs set status = 'failed', error = %s, finished_at = now() "
            "where id = %s", (f"{type(e).__name__}: {e}"[:4000], run_id))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Load USDA generic foods")
    parser.add_argument("--only", choices=sorted(DATASETS), action="append",
                        help="load just this dataset (repeatable)")
    args = parser.parse_args(argv)
    datasets = args.only or ["sr_legacy"]

    with psycopg.connect(DSN) as conn, psycopg.connect(DSN, autocommit=True) as log_conn:
        if not log_conn.execute("select pg_try_advisory_lock(%s)", (LOCK_ID,)).fetchone()[0]:
            log("another USDA load is already running; nothing to do")
            return 0
        load(conn, log_conn, datasets)
        conn.execute("analyze foods_source")
        conn.commit()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
