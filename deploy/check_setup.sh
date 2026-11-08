#!/usr/bin/env bash
# Checks that every part of Calorie-Macro-Tracker is in place: files, Python
# packages, database, daily update schedule, desktop launcher, and tests.
# Read-only except for the test suites, which clean up after themselves.
#
#   bash deploy/check_setup.sh            everything, including tests
#   bash deploy/check_setup.sh --no-tests skip the test suites
#
# @author Tony Shin <tonyshin4065@gmail.com>

cd "$(dirname "$0")/.." || exit 1
PY="$HOME/venv/bin/python"
DB="meal_tracker"
pass=0; fail=0; warn=0

ok()   { echo "  ✓ $1"; pass=$((pass + 1)); }
bad()  { echo "  ✗ $1"; fail=$((fail + 1)); }
note() { echo "  ! $1"; warn=$((warn + 1)); }
sql()  { psql -d "$DB" -Atqc "$1" 2>/dev/null; }

has() {   # has <file> <text that must be in it> <label>
    if [ ! -f "$1" ]; then bad "$3 — missing $1"
    elif grep -qF -- "$2" "$1"; then ok "$3"
    else bad "$3 — $1 is an old version (no '$2')"
    fi
}

echo "== Files"
has src/python/app.py                  'PAGES = ["Home"'                 "app.py (pages, editing, barcode, sidebar status)"
has src/python/app.py                  'SEARCH_COLS'                     "app.py search column fix"
has src/python/app.py                  'food_data_status'                "app.py food data status"
has src/python/app_queries.py          'def barcode_variants'            "app_queries.py"
has src/python/manual_foods.py         'def add_manual_food'             "manual_foods.py"
has src/python/off_api.py              'def fetch_product'               "off_api.py"
has src/python/meal_logging.py         "(origin = 'manual') desc"        "meal_logging.py ranked search"
has src/python/recipes.py              'def update_recipe'               "recipes.py editing"
has src/python/meal_editing.py         'def update_meal'                 "meal_editing.py"
has src/python/off_pipeline.py         'LOCK_ID'                         "off_pipeline.py (lock + clean stop)"
has src/sql/app/create_pipeline_runs.sql            'pipeline_runs'      "create_pipeline_runs.sql"
has src/sql/gold/add_foods_source_off_tracking.sql  'foods_source_barcode_key' "add_foods_source_off_tracking.sql"
has src/sql/bronze/create_off_delta.sql             'UNLOGGED'           "bronze create_off_delta.sql (fast)"
has src/sql/silver/create_off_delta_silver.sql      'OFFSET 0'           "silver create_off_delta_silver.sql (fast)"
has src/sql/silver/null_off_delta_outliers.sql      'off_delta_silver'   "null_off_delta_outliers.sql"
has src/sql/silver/add_off_delta_calorie_check.sql  'calorie_check'      "add_off_delta_calorie_check.sql"
has src/sql/gold/upsert_off_delta.sql               'ON CONFLICT (barcode)' "upsert_off_delta.sql"
has src/sql/silver/null_off_outliers.sql            'UPDATE off_product_silver' "null_off_outliers.sql bug fix"
has src/python/usda_generic_load.py     'def load'                        "usda_generic_load.py"
has src/sql/gold/upsert_usda_generic.sql            'source_id'          "upsert_usda_generic.sql"
has src/sql/gold/remove_usda_non_food_rows.sql      'sub_sample_food'    "remove_usda_non_food_rows.sql"
has src/python/meal_logging.py         '(barcode is null) desc'          "meal_logging.py generic-first search"
has deploy/systemd/off-update.service  'off_pipeline.py'                 "off-update.service"
has deploy/systemd/off-update.timer    'Persistent=true'                 "off-update.timer"
has deploy/launcher/macro-tracker.sh   'watchdog'                        "launcher (closes with the tab)"
for t in test_manual_foods test_barcode test_meal_logging test_recipes test_recipe_editing test_meal_editing test_off_pipeline test_usda_generic; do
    [ -f "src/python/$t.py" ] && ok "$t.py present" || bad "$t.py missing"
done
[ -f "work_log/11_07_2026.md" ] && ok "worklog 11_07_2026.md" || note "worklog work_log/11_07_2026.md not saved yet"

echo "== Secrets and git"
[ -f .streamlit/secrets.toml ] && ok ".streamlit/secrets.toml exists" || bad ".streamlit/secrets.toml missing"
git check-ignore -q .streamlit/secrets.toml && ok "secrets.toml is gitignored" || bad "secrets.toml is NOT gitignored"
git check-ignore -q src/python/.x.swp && ok "*.swp ignored" || note "*.swp not in .gitignore"
if git ls-files --error-unmatch .streamlit/secrets.toml >/dev/null 2>&1; then bad "secrets.toml is committed to git!"; fi
changes=$(git status --porcelain | wc -l)
[ "$changes" -eq 0 ] && ok "everything committed" || note "$changes uncommitted change(s) — commit tonight's work"

echo "== Python packages ($PY)"
for m in streamlit psycopg bcrypt requests; do
    "$PY" -c "import $m" 2>/dev/null && ok "$m" || bad "$m not installed (pip install $m)"
done
"$PY" -c "import pyzbar.pyzbar, PIL" 2>/dev/null && ok "pyzbar (camera scanning)" \
    || note "pyzbar not installed — camera scanning hidden (typing barcodes still works)"

echo "== Database"
if ! sql "select 1" >/dev/null; then
    bad "can't connect to $DB (is Postgres running?)"
else
    v=$(sql "show server_version_num"); [ "${v:-0}" -ge 160000 ] && ok "PostgreSQL 16+ ($(sql 'show server_version'))" || bad "PostgreSQL 16+ needed (have $(sql 'show server_version'))"
    for t in users foods_source foods_manual recipes recipe_items meal_log meal_log_items pipeline_runs; do
        [ "$(sql "select to_regclass('$t') is not null")" = "t" ] && ok "table $t" || bad "table $t missing"
    done
    [ "$(sql "select to_regclass('foods') is not null")" = "t" ] && ok "view foods" || bad "view foods missing"
    [ "$(sql "select count(*) from information_schema.columns where table_name='foods_source' and column_name='source_modified_t'")" = "1" ] \
        && ok "foods_source.source_modified_t" || bad "foods_source.source_modified_t missing (run the pipeline once)"
    [ "$(sql "select count(*) from pg_indexes where indexname='foods_source_barcode_key'")" = "1" ] \
        && ok "unique barcode index" || bad "unique barcode index missing"
    [ "$(sql "select count(*) from pg_indexes where tablename='foods_source' and indexdef like '%gin_trgm_ops%'")" -ge 1 ] \
        && ok "name search index (pg_trgm)" || note "no pg_trgm index on foods_source.name — searches will be slow"
    echo "   foods_source: $(sql "select to_char(count(*), 'FM9,999,999') from foods_source") rows"
    g=$(sql "select count(*) from foods_source where source = 'usda' and source_id is not null" )
    [ "${g:-0}" -gt 0 ] && ok "USDA generic foods loaded ($g)" || note "USDA generic foods not loaded (python src/python/usda_generic_load.py)"

    echo "== Open Food Facts updates"
    last=$(sql "select run_type || ' ' || status || ' ' || coalesce(to_char(finished_at, 'YYYY-MM-DD HH24:MI'), 'still going') from pipeline_runs order by id desc limit 1")
    echo "   latest run: ${last:-none}"
    full=$(sql "select count(*) from pipeline_runs where run_type='backfill' and status='success'")
    running=$(sql "select count(*) from pipeline_runs where status='running'")
    if [ "${full:-0}" -ge 1 ]; then ok "full refresh completed"
    elif systemctl --user is-active -q off-full-refresh 2>/dev/null; then note "full refresh still running — check again later"
    else bad "no successful full refresh and none running"
    fi
    if [ "${running:-0}" -gt 0 ] && ! systemctl --user is-active -q off-full-refresh 2>/dev/null \
            && ! systemctl --user is-active -q off-update 2>/dev/null; then
        note "$running run(s) marked 'running' but nothing is running (stale rows)"
    fi
fi

echo "== Daily schedule"
systemctl --user is-enabled -q off-update.timer 2>/dev/null && ok "off-update.timer enabled" || bad "off-update.timer not enabled"
systemctl --user is-active -q off-update.timer 2>/dev/null && ok "off-update.timer active, next: $(systemctl --user show off-update.timer -p NextElapseUSecRealtime --value)" || bad "off-update.timer not active"
[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" = "yes" ] && ok "linger on (runs when logged out)" || note "linger off (runs only while logged in)"

echo "== Desktop launcher"
D="$HOME/.local/share/applications/macro-tracker.desktop"
[ -f "$D" ] && ok "macro-tracker.desktop installed" || bad "launcher not installed (bash deploy/launcher/install.sh)"
[ -f "$HOME/.local/share/icons/macro-tracker.svg" ] && ok "icon installed" || bad "icon missing"
if [ -f "$D" ]; then
    exe=$(grep -m1 '^Exec=' "$D" | cut -d= -f2-)
    [ -x "$exe" ] && ok "launcher script executable" || bad "launcher script not found/executable: $exe"
fi

if [ "$1" != "--no-tests" ]; then
    echo "== Tests"
    for t in test_manual_foods test_barcode test_meal_logging test_recipes test_recipe_editing test_meal_editing test_off_pipeline test_usda_generic; do
        [ -f "src/python/$t.py" ] || continue
        out=$( cd src/python && "$PY" "$t.py" 2>&1 )
        summary=$(echo "$out" | grep -E "passed|ALL PASSED|SKIP" | tail -1)
        if echo "$out" | grep -q "^SKIP"; then note "$t: $summary"
        elif echo "$out" | grep -qE "^(FAIL|  FAIL)|[1-9][0-9]* failed|Traceback"; then bad "$t: ${summary:-crashed} (run it alone to see why)"
        else ok "$t: $summary"
        fi
    done
fi

echo
echo "$pass ok, $warn to look at, $fail problems"
[ "$fail" -eq 0 ]
