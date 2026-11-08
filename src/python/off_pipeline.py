"""
Phase 8 - Open Food Facts incremental ingestion

Keeps foods_source current with Open Food Facts.

    python src/python/off_pipeline.py          # apply any new daily deltas
    python src/python/off_pipeline.py --full   # one-time full refresh

Daily (default): OFF publishes one delta file per day listing every product
that changed, and keeps the last 14 days. The job applies every file it
hasn't applied yet, oldest first, each in ONE transaction: it either lands
completely or not at all, and failures are logged in pipeline_runs.

Full (--full): streams OFF's full JSONL dump through the same SQL, in
batches, without saving it to disk. Needed once now (the original import is
older than 14 days of deltas), and again if the laptop is ever off for more
than 14 days. Safe to stop and rerun: every step is an idempotent upsert.

Python only moves bytes: download, decompress, COPY into bronze, run the
.sql files, record the run. All transformation is in src/sql/.

@author Tony Shin <tonyshin4065@gmail.com>
"""

import argparse
import datetime as dt
import email.utils
import gzip
import os
import pathlib
import re
import signal
import sys
import traceback

import psycopg
import requests

REPO = pathlib.Path(__file__).resolve().parents[2]
SQL_DIR = REPO / "src" / "sql"
DATA_DIR = REPO / "data" / "off_delta"          # gitignored scratch space

DELTA_BASE = "https://static.openfoodfacts.org/data/delta/"
FULL_URL = "https://static.openfoodfacts.org/data/openfoodfacts-products.jsonl.gz"
USER_AGENT = "CalorieMacroTracker/0.1 (https://github.com/tonyy-shin/Calorie-Macro-Tracker)"
# Peer auth over the Unix socket, same as the test files. Override with
# MEAL_TRACKER_DSN, e.g. "dbname=meal_tracker user=tonyyshin host=localhost".
DSN = os.environ.get("MEAL_TRACKER_DSN", "dbname=meal_tracker user=tonyyshin")

BATCH_LINES = 50_000
# Postgres advisory lock id: only one run (daily or --full) at a time
LOCK_ID = 80_250_001
DELTA_NAME = re.compile(r"_(\d+)_(\d+)\.json\.gz$")

SETUP_STEPS = [
    "app/create_pipeline_runs.sql",
    "gold/add_foods_source_off_tracking.sql",
]
BATCH_STEPS = [
    "bronze/create_off_delta.sql",
    "silver/create_off_delta_silver.sql",
    "silver/null_off_delta_outliers.sql",
    "silver/add_off_delta_calorie_check.sql",
    "gold/upsert_off_delta.sql",               # must stay last: its rowcount is used
]
COPY_LINES = ("COPY off_delta (line) FROM STDIN "
              "WITH (FORMAT csv, DELIMITER E'\\x01', QUOTE E'\\x02')")


def log(msg):
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# =====================================================================
# Network (only place that talks to Open Food Facts)
# =====================================================================
def http_get(url, stream=False):
    r = requests.get(url, headers={"User-Agent": USER_AGENT},
                     stream=stream, timeout=(15, 300))
    r.raise_for_status()
    return r


def fetch_index():
    """Names of the delta files OFF currently offers."""
    text = http_get(DELTA_BASE + "index.txt").text
    return [line.strip() for line in text.splitlines() if DELTA_NAME.search(line.strip())]


def download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with http_get(url, stream=True) as r, open(tmp, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    tmp.rename(dest)
    return dest


def delta_times(name):
    """(first_change, last_change) as UTC datetimes, from the file name."""
    start, end = DELTA_NAME.search(name).groups()
    to_dt = lambda t: dt.datetime.fromtimestamp(int(t), dt.timezone.utc)
    return to_dt(start), to_dt(end)


# =====================================================================
# Database
# =====================================================================
def run_sql(cur, relpath):
    cur.execute((SQL_DIR / relpath).read_text())


def setup(conn):
    with conn.transaction(), conn.cursor() as cur:
        for step in SETUP_STEPS:
            run_sql(cur, step)


def load_batch(cur, lines):
    """bronze -> silver -> gold for one batch of raw JSON lines.
    @return rows inserted or changed in foods_source"""
    run_sql(cur, BATCH_STEPS[0])
    with cur.copy(COPY_LINES) as copy:
        for line in lines:
            copy.write(line)
    for step in BATCH_STEPS[1:]:
        run_sql(cur, step)
    return cur.rowcount


def batches(line_iter, size=BATCH_LINES):
    batch = []
    for line in line_iter:
        if line.strip():
            batch.append(line)
            if len(batch) >= size:
                yield batch
                batch = []
    if batch:
        yield batch


def start_run(log_conn, run_type, file_name, note=None):
    return log_conn.execute(
        "insert into pipeline_runs (source, run_type, file_name, status, note) "
        "values ('off', %s, %s, 'running', %s) returning id",
        (run_type, file_name, note)).fetchone()[0]


def finish_run(log_conn, run_id, status, rows_read=None, rows_loaded=None,
               data_through=None, error=None):
    log_conn.execute(
        "update pipeline_runs set status = %s, rows_read = %s, rows_loaded = %s, "
        "data_through = %s, error = %s, finished_at = now() where id = %s",
        (status, rows_read, rows_loaded, data_through, error, run_id))


def applied_files(log_conn):
    rows = log_conn.execute(
        "select file_name from pipeline_runs "
        "where source = 'off' and run_type = 'delta' and status = 'success'").fetchall()
    return {r[0] for r in rows}


def current_through(log_conn):
    """How current foods_source is: latest data_through of a successful run."""
    return log_conn.execute(
        "select max(data_through) from pipeline_runs "
        "where source = 'off' and status = 'success'").fetchone()[0]


# =====================================================================
# Jobs
# =====================================================================
def apply_deltas(conn, log_conn):
    """Apply every new delta file, oldest first. Stops at the first failure
    so files are never applied out of order. @return files applied"""
    available = sorted(fetch_index(), key=lambda n: delta_times(n)[0])
    done = applied_files(log_conn)
    pending = [n for n in available if n not in done]
    log(f"{len(available)} delta files offered, {len(pending)} new")
    if not pending:
        return 0

    note = None
    through = current_through(log_conn)
    oldest_start = delta_times(available[0])[0]
    if through is None:
        note = "no full refresh recorded; run with --full once"
    elif through < oldest_start:
        note = (f"gap: data is current to {through:%Y-%m-%d} but the oldest "
                f"delta starts {oldest_start:%Y-%m-%d}; run with --full")
    if note:
        log(f"WARNING: {note}")

    for name in pending:
        run_id = start_run(log_conn, "delta", name, note)
        path = DATA_DIR / name
        try:
            download(DELTA_BASE + name, path)
            read = loaded = 0
            with conn.transaction(), conn.cursor() as cur:   # whole file or nothing
                with gzip.open(path, "rb") as f:
                    for batch in batches(f):
                        loaded += load_batch(cur, batch)
                        read += len(batch)
            finish_run(log_conn, run_id, "success", read, loaded,
                       data_through=delta_times(name)[1])
            log(f"{name}: {read:,} products read, {loaded:,} rows added or changed")
        except Exception as e:
            finish_run(log_conn, run_id, "failed",
                       error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}"[:4000])
            log(f"FAILED on {name}: {e}")
            raise
        finally:
            path.unlink(missing_ok=True)
    return len(pending)


def full_refresh(conn, log_conn, url=FULL_URL):
    """Stream the full dump through the same SQL, one transaction per batch."""
    run_id = start_run(log_conn, "backfill", url)
    read = loaded = 0
    try:
        with http_get(url, stream=True) as r:
            # the dump is regenerated nightly; its Last-Modified says how fresh it is
            stamp = r.headers.get("Last-Modified")
            through = (email.utils.parsedate_to_datetime(stamp) if stamp
                       else dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1))
            r.raw.decode_content = True
            with gzip.GzipFile(fileobj=r.raw) as f:
                for batch in batches(f):
                    with conn.transaction(), conn.cursor() as cur:
                        loaded += load_batch(cur, batch)
                    read += len(batch)
                    if read % (BATCH_LINES * 20) == 0:
                        log(f"full refresh: {read:,} products read, {loaded:,} changed")
        finish_run(log_conn, run_id, "success", read, loaded, data_through=through)
        log(f"full refresh done: {read:,} products read, {loaded:,} rows added or changed")
    except BaseException as e:   # includes Ctrl+C, so the run isn't left 'running'
        finish_run(log_conn, run_id, "failed", read, loaded,
                   error=f"{type(e).__name__}: {e}"[:4000])
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--full", action="store_true",
                        help="stream the full OFF dump (one-time / after a gap)")
    args = parser.parse_args(argv)

    with psycopg.connect(DSN) as conn, psycopg.connect(DSN, autocommit=True) as log_conn:
        # Held until log_conn closes. If another run (e.g. a background
        # --full refresh) holds it, step aside: that run catches up on
        # deltas itself when it finishes.
        if not log_conn.execute("select pg_try_advisory_lock(%s)", (LOCK_ID,)).fetchone()[0]:
            log("another update is already running; nothing to do")
            return 0
        setup(conn)
        if args.full:
            full_refresh(conn, log_conn)
            apply_deltas(conn, log_conn)        # then catch up to today
        else:
            apply_deltas(conn, log_conn)
        with conn.cursor() as cur:
            cur.execute("analyze foods_source")
    return 0


if __name__ == "__main__":
    # `systemctl stop` sends SIGTERM: turn it into a normal exit so the run
    # is marked failed in pipeline_runs instead of left as 'running'.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)        # non-zero so systemd marks the run failed and retries
