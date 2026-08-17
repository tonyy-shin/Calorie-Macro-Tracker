# Calorie & Macro Tracker

A data pipeline project, not a CRUD app. Bulk nutrition data from USDA and
Open Food Facts is ingested, transformed through a bronze → silver → gold
architecture in SQL, and served through a small multi-user Streamlit app.
The pipeline is the portfolio piece; the app is what makes it usable.

## Why this project exists

Most beginner tracker apps are just forms writing to a table. This one is
built to demonstrate real data engineering fundamentals: bulk ingestion,
SQL-based transformation, idempotent reloads, and a schema with actual
tradeoffs — not just a food log.

## Tech stack

- **PostgreSQL** — single `meal_tracker` database
- **Python** (psycopg3) — moves bytes only; no transform logic in Python
- **SQL** — all typing, cleaning, and transformation logic (bronze/silver/gold)
- **Streamlit** — thin app layer on top of the finished schema
- **Data sources** — [USDA FoodData Central](https://fdc.nal.usda.gov/) (bulk CSV) and [Open Food Facts](https://world.openfoodfacts.org/) (bulk + daily deltas)

## Architecture

**Medallion pattern, entirely in SQL:**

- **Bronze** — raw USDA and Open Food Facts dumps, loaded via `COPY` exactly
  as downloaded, untouched.
- **Silver** — SQL transform step (`FILTER`, `CASE`, conditional
  aggregation). USDA's long-format nutrients get pivoted, OFF's mixed
  per-serving/per-100g fields get reconciled, and a calorie sanity check
  (`kcal ≈ protein_g*4 + carbs_g*4 + fat_g*9`) filters bad rows.
- **Gold** — `foods_source`, plus `recipes` and `meal_log` built on top.
  What the app actually queries.

**One database, nine objects** — tables plus a `UNION ALL` view keep
pipeline-owned data (`foods_source`) and user-owned data (`foods_manual`)
physically separate while still queryable as one surface:

| Table | Owner | Purpose |
|---|---|---|
| `users` | — | Accounts: email + hashed password |
| `foods_source` | pipeline | USDA + OFF nutrition data, shared |
| `foods_manual` | user | Hand-typed entries, scoped per user |
| `foods` *(view)* | — | `foods_source UNION ALL foods_manual` |
| `recipes` | user | Saved meals: name + yield in portions |
| `recipe_items` | user | Ingredient list per recipe |
| `meal_log` | user | Logged meals; snapshots macros at log time |
| `meal_log_items` | user | Ad-hoc meal components |
| `pipeline_runs` | pipeline | Ingestion job history — source, status, row counts |

Full schema and design rationale: [`meal-prep-tracker-overview.md`](./meal-prep-tracker-overview.md)

## Key design decisions

- **ELT, not ETL** — Python only fetches and decompresses files; all
  transformation happens in SQL.
- **Bulk CSV over live API** — both sources rate-limit or discourage bulk
  API polling; flat exports map cleanly onto `COPY`.
- **Staging table + transactional swap for USDA** (monthly, full reload) —
  **`ON CONFLICT` upsert for Open Food Facts** (daily deltas). Ingestion
  mechanism matches how often each source actually changes.
- **Macros stored per 100g, always** — recipe and daily totals are
  computed via query, never stored as totals.
- **`meal_log` snapshots totals at log time** — editing a recipe later
  doesn't retroactively change what was already logged.
- **Manual foods are scoped per user** via `user_id` — one person's
  hand-typed entry never leaks into another user's search results.

## Project status

- ✅ **Phase 0 — Environment**: PostgreSQL + Python venv set up, connectivity confirmed
- 🔄 **Phase 1 — Bronze ingestion**: Landing raw USDA FoodData Central CSVs (`food`, `nutrient`, `food_nutrient`, `branded_food`) into bronze tables
- ⬜ Phase 2 — Silver/Gold transform (initial backfill)
- ⬜ Phase 3 — Users and auth
- ⬜ Phase 4 — Manual entries + unified `foods` view
- ⬜ Phase 5 — Meal logging
- ⬜ Phase 6 — Recipes
- ⬜ Phase 7 — Streamlit app
- ⬜ Phase 8 — Incremental (OFF daily delta) ingestion
- ⬜ Phase 9 — Extensions (targets, trend charts)

## Setup

```bash
# clone and enter the project
git clone https://github.com/tonyyshin/Calorie-Macro-Tracker-Project.git
cd Calorie-Macro-Tracker-Project

# python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# postgres
createdb meal_tracker
export PG_PASSWORD='your_password_here'
```

Raw data files (USDA/OFF exports) are not committed to this repo — download
them separately from the sources linked above and place them locally before
running ingestion scripts.

## License

MIT