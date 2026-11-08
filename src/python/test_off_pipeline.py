"""
@file test_off_pipeline.py
Phase 8 - tests for off_pipeline.py, end to end against the real database,
with Open Food Facts replaced by local fake files (no network).

Checks: existing rows updated in place (ids unchanged), new products
inserted, USDA rows never overwritten, older data never overwrites newer,
unchanged rows not counted, bad lines skipped, reruns skip applied files,
a failed file leaves nothing behind and stops later files, the full-refresh
path, and gap detection. Test rows use barcodes starting with 99<random>
and file names containing a random tag; all are removed in finally.

Run: python src/python/test_off_pipeline.py
@author Tony Shin <tonyshin4065@gmail.com>
"""

import email.utils
import sys
import gzip
import io
import json
import pathlib
import shutil
import tempfile
import uuid
import datetime as dt

import psycopg

import off_pipeline as job

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


def close(a, b):
    return a is not None and abs(a - b) < 1e-6


tag = uuid.uuid4().hex[:8]
n = str(int(tag, 16) % 10**6).zfill(6)
B = {k: f"99{n}{k:02d}" for k in range(1, 12)}       # test barcodes
fixtures = pathlib.Path(tempfile.mkdtemp(prefix="off_test_"))
job.DATA_DIR = fixtures / "downloads"


def product(code, name=None, t=None, kcal=None, p=None, c=None, f=None, **extra):
    d = {"code": code, "nutriments": {}}
    if name is not None:
        d["product_name"] = name
    if t is not None:
        d["last_modified_t"] = t
    for key, v in (("energy-kcal_100g", kcal), ("proteins_100g", p),
                   ("carbohydrates_100g", c), ("fat_100g", f)):
        if v is not None:
            d["nutriments"][key] = v
    d.update(extra)
    return json.dumps(d, ensure_ascii=False)


def write_delta(name, lines):
    with gzip.open(fixtures / name, "wb") as fh:
        fh.write(("\n".join(lines) + "\n").encode("utf-8"))
    return name


def delta_name(start, end):
    return f"test{tag}_products_{start}_{end}.json.gz"


offered = []
job.fetch_index = lambda: list(offered)
def fake_download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(fixtures / url.rsplit("/", 1)[1], dest)
    return dest


job.download = fake_download


def row(cur, barcode):
    cur.execute("select id, name, brand, source, kcal, protein_g, carbs_g, fat_g, "
                "calorie_check, source_modified_t from foods_source where barcode = %s",
                (barcode,))
    return cur.fetchone()


def last_run(cur, file_name):
    cur.execute("select status, rows_read, rows_loaded, note, error, data_through "
                "from pipeline_runs where file_name = %s order by id desc limit 1",
                (file_name,))
    return cur.fetchone()


conn = psycopg.connect(job.DSN)
log_conn = psycopg.connect(job.DSN, autocommit=True)
cur = log_conn.cursor()

# This test rebuilds the same bronze/silver tables the real job uses, so it
# must never run at the same time as an update (e.g. a background --full).
if not cur.execute("select pg_try_advisory_lock(%s)", (job.LOCK_ID,)).fetchone()[0]:
    print("SKIP: an Open Food Facts update is running right now; run this test after it finishes")
    raise SystemExit(0)

try:
    job.setup(conn)
    conn.commit()

    # --- existing rows, as left by the original import ---
    cur.execute("insert into foods_source (barcode, name, brand, source, kcal, protein_g, "
                "carbs_g, fat_g, loaded_at) values (%s, 'Old name', null, 'off', 100, 1, 1, 1, now()) "
                "returning id", (B[1],))
    off_id = cur.fetchone()[0]
    cur.execute("insert into foods_source (barcode, name, brand, source, kcal, protein_g, "
                "carbs_g, fat_g, loaded_at) values (%s, 'USDA name', null, 'usda', 50, 2, 3, 1, now()) "
                "returning id", (B[2],))
    usda_id = cur.fetchone()[0]

    # =============================================================
    # delta 1
    # =============================================================
    d1 = write_delta(delta_name(1000, 2000), [
        product(B[1], "New name", 1500, 250, 10, 30, 10, brands="  Acme  "),
        product(B[1], "Stale dup", 1400, 999, 1, 1, 1),            # older duplicate
        product(B[3], "Brand new", 1600, 400, 20, 50, 13),
        product(B[2], "OFF version", 1700, 999, 9, 9, 9),          # collides with USDA
        product(B[4], None, 1700, 100, 1, 1, 1),                   # no name -> skipped
        product(B[5], "Bad numbers", 1700, "abc", 5000, "12.5", 2),
        product(B[6], None, 1700, 50, 1, 10, 0, product_name_en="English name"),
        product(B[7], 'Bob\'s "Best" \\ back\tslash café 한글', 1700, 100, 2, 20, 1),
        "{not valid json",
        "",
    ])
    offered[:] = [d1]
    applied = job.apply_deltas(conn, log_conn)
    check("delta 1 applied", applied == 1)

    r = row(cur, B[1])
    check("existing OFF row updated IN PLACE (same id)", r[0] == off_id, r)
    check("newest duplicate in the file wins", r[1] == "New name" and close(r[4], 250), r)
    check("brand trimmed", r[2] == "Acme", r)
    check("calorie_check computed (250 vs 250)", r[8] is True, r)
    check("source_modified_t stored", r[9] == 1500, r)

    check("new product inserted", row(cur, B[3]) is not None and row(cur, B[3])[1] == "Brand new")
    r = row(cur, B[2])
    check("USDA row NOT overwritten", r[0] == usda_id and r[1] == "USDA name" and r[3] == "usda", r)
    check("nameless product skipped", row(cur, B[4]) is None)
    r = row(cur, B[5])
    check("non-numeric kcal -> NULL, impossible protein -> NULL",
          r[4] is None and r[5] is None and close(r[6], 12.5), r)
    check("calorie_check NULL when a macro is missing", r[8] is None, r)
    check("product_name_en fallback", row(cur, B[6])[1] == "English name")
    check("quotes, backslash, tab and unicode survive COPY",
          row(cur, B[7])[1] == 'Bob\'s "Best" \\ back\tslash café 한글', row(cur, B[7]))

    run = last_run(cur, d1)
    check("run logged as success", run[0] == "success", run)
    check("rows_read counts non-empty lines (9)", run[1] == 9, run)
    check("rows_loaded = 1 update + 4 inserts", run[2] == 5, run)
    check("data_through = file's last change",
          run[5] == dt.datetime.fromtimestamp(2000, dt.timezone.utc), run)
    check("downloaded file cleaned up", not (job.DATA_DIR / d1).exists())

    # rerun: nothing new
    check("rerun skips already-applied file", job.apply_deltas(conn, log_conn) == 0)

    # =============================================================
    # delta 2: stale data, unchanged data, one new product
    # =============================================================
    d2 = write_delta(delta_name(2000, 3000), [
        product(B[1], "Older edit", 1200, 111, 1, 1, 1),            # older than stored 1500
        product(B[3], "Brand new", 1600, 400, 20, 50, 13),          # identical
        product(B[8], "Another", 2500, 300, 10, 40, 10),
    ])
    offered[:] = [d1, d2]
    check("only the new file is applied", job.apply_deltas(conn, log_conn) == 1)
    check("older data does not overwrite newer", row(cur, B[1])[1] == "New name")
    check("delta 2 counts only real changes (1)", last_run(cur, d2)[2] == 1, last_run(cur, d2))

    # =============================================================
    # failure: corrupt file stops the run, nothing partial, later file waits
    # =============================================================
    d3 = delta_name(3000, 4000)
    with open(fixtures / d3, "wb") as fh:
        fh.write(gzip.compress((product(B[9], "Half written", 3500, 1, 1, 1, 1) + "\n").encode())[:-12])
    d4 = write_delta(delta_name(4000, 5000), [product(B[10], "After the failure", 4500, 1, 0, 0, 0)])
    offered[:] = [d1, d2, d3, d4]
    try:
        job.apply_deltas(conn, log_conn)
        check("corrupt file raises", False, "no error")
    except Exception:
        check("corrupt file raises", True)
    run = last_run(cur, d3)
    check("failure logged with error text", run[0] == "failed" and run[4], run)
    check("no partial write from the failed file", row(cur, B[9]) is None)
    check("later file not applied past a failure", row(cur, B[10]) is None)

    # fixed file -> both apply in order on the next run
    write_delta(d3, [product(B[9], "Now complete", 3500, 1, 0, 0, 0)])
    check("next run retries the failed file and continues", job.apply_deltas(conn, log_conn) == 2)
    check("retried file applied", row(cur, B[9]) is not None)
    check("later file applied", row(cur, B[10]) is not None)

    # =============================================================
    # full refresh (streamed dump, batched)
    # =============================================================
    dump = gzip.compress(("\n".join([
        product(B[1], "From full dump", 6000, 300, 15, 30, 12),
        product(B[11], "Only in dump", 6000, 200, 5, 30, 5),
    ]) + "\n").encode())
    stamp = dt.datetime(2026, 11, 7, 3, 0, tzinfo=dt.timezone.utc)

    class FakeStream:
        headers = {"Last-Modified": email.utils.format_datetime(stamp, usegmt=True)}
        raw = io.BytesIO(dump)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    real_http_get = job.http_get
    job.http_get = lambda url, stream=False: FakeStream()
    old_batch = job.BATCH_LINES
    job.BATCH_LINES = 1                     # force several batches
    try:
        job.full_refresh(conn, log_conn, url=f"test{tag}-dump")
    finally:
        job.http_get = real_http_get
        job.BATCH_LINES = old_batch
    r = row(cur, B[1])
    check("full refresh updates in place (same id)", r[0] == off_id and r[1] == "From full dump", r)
    check("full refresh inserts new products", row(cur, B[11]) is not None)
    run = last_run(cur, f"test{tag}-dump")
    check("backfill logged with dump's Last-Modified as data_through",
          run[0] == "success" and run[5] == stamp and run[2] == 2, run)

    # =============================================================
    # gap detection: newest data is older than the oldest delta offered
    # =============================================================
    far = 4_000_000_000                     # year 2096
    d5 = write_delta(delta_name(far, far + 86400), [product(B[11], "Only in dump", 6000, 200, 5, 30, 5)])
    offered[:] = [d5]
    job.apply_deltas(conn, log_conn)
    run = last_run(cur, d5)
    check("gap noted on the run", run[3] is not None and "gap" in run[3], run)
    check("still applied despite the gap", run[0] == "success", run)

    # the app reads through the foods view: the updated row is visible there
    cur.execute("select name from foods where id = %s and origin = 'source'", (off_id,))
    check("updated row visible through foods view under the same id",
          cur.fetchone()[0] == "From full dump")

finally:
    conn.rollback()
    cur.execute("delete from foods_source where barcode like %s", (f"99{n}%",))
    cur.execute("delete from pipeline_runs where file_name like %s", (f"%{tag}%",))
    conn.close()
    log_conn.close()
    shutil.rmtree(fixtures, ignore_errors=True)

print(f"\n{passed} passed, {failed} failed")
