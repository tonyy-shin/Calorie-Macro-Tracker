# Meal Prep Macro Tracker — Project Overview

## What this project actually is

Not a CRUD app. It's a **data pipeline** — bulk food data ingested,
transformed, and served through a schema that keeps pipeline-owned and
user-owned data physically separate — with a small multi-user app on top
that consumes it. The pipeline is the portfolio piece; the app is what
makes it usable.

A recruiter looking at your GitHub should see ingestion, transformation,
and a schema with real tradeoffs in it — not just forms writing to a
table.

---

## One database, many tables

This is **one Postgres database**, not several. A Postgres database is a
hard boundary — one connection queries one database, no native
cross-database join. What gives you "separate storage that still combines
into one queryable whole" is **tables plus a view that unions them** —
that's `foods_source` / `foods_manual`, and it's the same pattern the
recipe and meal-log tables use. A `schema` (a namespace inside one
database) exists if you ever want Postgres to enforce the pipeline/user
split structurally instead of by naming convention — not needed yet.

---

## Architecture: medallion (bronze → silver → gold), all in SQL

- **Bronze** — raw USDA and Open Food Facts dumps, loaded via `COPY`
  exactly as downloaded, untouched.
- **Silver** — the transform step, done as SQL (`FILTER`, `CASE`,
  conditional aggregation), not pandas. USDA's long-format nutrients get
  pivoted, OFF's mixed per-serving/per-100g fields get reconciled, and a
  calorie sanity check (`kcal ≈ protein_g*4 + carbs_g*4 + fat_g*9`) filters
  bad rows.
- **Gold** — `foods_source`, plus `recipes` and `meal_log` built on top of
  it. What the app actually queries.

Python's only job anywhere in the pipeline is moving bytes: download a
dump or delta file, decompress it, hand it to `COPY`. pandas, if used at
all, is a scratchpad for exploring a new file — never a pipeline
dependency.

---

## Ingestion cadence: backfill vs. incremental

- **USDA FoodData Central** — Branded Foods update monthly, Foundation
  Foods twice a year, no changes-only feed. Stays a **full bulk download +
  staging-table swap**, scheduled monthly.
- **Open Food Facts** — changes daily. They publish daily delta files
  listing exactly what changed. This becomes a **daily incremental job**:
  download the delta, `ON CONFLICT` upsert into `foods_source`. Full
  reload only for the initial backfill.

Neither source wants bulk consumers looping over their live per-product
API — both expect exports/deltas instead. The pipeline never calls the
live API.

---

## Auth and per-user data

Every user-owned table gets a `user_id`. That's `foods_manual`, `recipes`,
and `meal_log` — not `foods_source` or `pipeline_runs`, which are shared
pipeline data nobody owns individually.

One assumption worth stating explicitly: **manual food entries are scoped
per user, not shared globally.** If they weren't, one person typing in
"grandma's chili powder" would silently show up in everyone else's search
results. That means `foods_manual` needs `user_id`, and the `foods` view
needs to carry it through so lookups can filter correctly:

```sql
CREATE VIEW foods AS
SELECT id, barcode, name, brand, 'source' AS origin, NULL::BIGINT AS user_id,
       kcal, protein_g, carbs_g, fat_g
FROM foods_source
UNION ALL
SELECT id, barcode, name, brand, 'manual' AS origin, user_id,
       kcal, protein_g, carbs_g, fat_g
FROM foods_manual;
```

```sql
-- a lookup now needs: pipeline food, OR my own manual entry
SELECT * FROM foods
WHERE barcode = %s AND (origin = 'source' OR user_id = %s);
```

Two rules for the auth layer itself, since this is the first place
user-typed input decides what data someone can see:

- **Never store a plaintext password.** Hash with `bcrypt` or `passlib`
  before it touches a table; compare hashes on login, never raw strings.
- **Every value goes through a query parameter, never a formatted-in
  string.** You've been safe on this by accident so far. Now it's a real
  boundary.

Streamlit has no built-in login system. The standard pattern: a login form
writes `user_id` into `st.session_state` on success; every tab checks for
it before rendering.

---

## Tables at a glance

| Table | Owner | What it holds |
|---|---|---|
| `users` | — | One row per account: email and a hashed password. Everything else keys off `id` here. |
| `foods_source` | pipeline | Ingredient and packaged-food data pulled from USDA and Open Food Facts. Rebuilt monthly (USDA) or kept current daily (OFF). Nobody's `user_id` — it's shared. |
| `foods_manual` | user | Foods a user typed in by hand because a barcode came back empty. Scoped to `user_id` so entries don't leak between accounts. |
| `foods` *(view, not a table)* | — | `foods_source UNION ALL foods_manual`. Every lookup in the app — search, barcode, recipe building — reads from this, never from the two tables directly. |
| `recipes` | user | A saved meal: a name and a yield in portions. The macros aren't stored here — they're computed from `recipe_items` on the fly. |
| `recipe_items` | user | The ingredient list for a recipe — which food, how many grams, one row per ingredient. |
| `meal_log` | user | One row per meal actually logged, on a given date. Carries a snapshot of that meal's total macros at the moment it was logged, whether it came from a recipe or was built ad hoc. This is what the daily and calendar rollups query. |
| `meal_log_items` | user | The individual foods behind an ad-hoc `meal_log` row — empty for recipe-based meals, since those are already fully described by `recipe_id` + `portions`. |
| `pipeline_runs` | pipeline | One row per backfill or delta job run — source, whether it succeeded, how many rows moved. What lets a scheduled job tell you it failed instead of failing silently. |

---

## Data model

```sql
CREATE TABLE users (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- pipeline-owned, nobody's user_id. Monthly full-swap (USDA) or
-- initial full-swap + daily upserts (OFF).
CREATE TABLE foods_source (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    barcode    TEXT UNIQUE,
    name       TEXT NOT NULL,
    brand      TEXT,
    source     TEXT NOT NULL,             -- 'usda' or 'off'
    kcal       DOUBLE PRECISION,
    protein_g  DOUBLE PRECISION,
    carbs_g    DOUBLE PRECISION,
    fat_g      DOUBLE PRECISION,
    loaded_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- user-owned. The pipeline never writes here.
CREATE TABLE foods_manual (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(id),
    barcode    TEXT,
    name       TEXT NOT NULL,
    brand      TEXT,
    kcal       DOUBLE PRECISION,
    protein_g  DOUBLE PRECISION,
    carbs_g    DOUBLE PRECISION,
    fat_g      DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- unified read surface — every lookup in the app goes through this
CREATE VIEW foods AS
SELECT id, barcode, name, brand, 'source' AS origin, NULL::BIGINT AS user_id,
       kcal, protein_g, carbs_g, fat_g
FROM foods_source
UNION ALL
SELECT id, barcode, name, brand, 'manual' AS origin, user_id,
       kcal, protein_g, carbs_g, fat_g
FROM foods_manual;

-- user-owned: a recipe combines several foods with a yield
CREATE TABLE recipes (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id        BIGINT NOT NULL REFERENCES users(id),
    name           TEXT NOT NULL,
    yield_portions INTEGER NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE recipe_items (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recipe_id   BIGINT NOT NULL REFERENCES recipes(id),
    food_id     BIGINT NOT NULL,
    food_origin TEXT NOT NULL,      -- 'source' or 'manual'
    grams       DOUBLE PRECISION NOT NULL
);

-- one row per logged meal, whether it came from a recipe or was built
-- ad hoc out of several individually-found foods
CREATE TABLE meal_log (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users(id),
    log_date     DATE NOT NULL,
    meal_name    TEXT,
    source_type  TEXT NOT NULL,        -- 'recipe' or 'ad_hoc'
    recipe_id    BIGINT REFERENCES recipes(id),
    portions     DOUBLE PRECISION,
    kcal         DOUBLE PRECISION NOT NULL,   -- snapshot, computed at log time
    protein_g    DOUBLE PRECISION NOT NULL,
    carbs_g      DOUBLE PRECISION NOT NULL,
    fat_g        DOUBLE PRECISION NOT NULL,
    logged_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE meal_log_items (   -- populated for ad_hoc meals only
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    meal_log_id  BIGINT NOT NULL REFERENCES meal_log(id),
    food_id      BIGINT NOT NULL,
    food_origin  TEXT NOT NULL,
    grams        DOUBLE PRECISION NOT NULL
);

-- tracks every pipeline backfill and delta run
CREATE TABLE pipeline_runs (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source      TEXT NOT NULL,           -- 'usda' or 'off'
    run_type    TEXT NOT NULL,           -- 'backfill' or 'delta'
    run_date    DATE NOT NULL,
    rows_loaded INTEGER,
    status      TEXT NOT NULL,           -- 'success' or 'failed'
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Macros always stored **per 100g**. Nothing else is ever a stored total —
recipe per-portion macros and daily rollups are both queries:

```sql
-- recipe per-portion macros
SELECT
    r.id, r.name,
    SUM(f.kcal * ri.grams / 100.0) / r.yield_portions AS kcal_per_portion,
    SUM(f.protein_g * ri.grams / 100.0) / r.yield_portions AS protein_g_per_portion
FROM recipes r
JOIN recipe_items ri ON ri.recipe_id = r.id
JOIN foods f ON f.id = ri.food_id AND f.origin = ri.food_origin
GROUP BY r.id, r.name, r.yield_portions;

-- daily rollup — no join, no branching on source_type, because
-- meal_log already carries the snapshot totals
SELECT log_date, SUM(kcal), SUM(protein_g), SUM(carbs_g), SUM(fat_g)
FROM meal_log
WHERE user_id = %s AND log_date = %s
GROUP BY log_date;
```

---

## UI: four tabs, one login gate

- **Home** — the daily rollup query above for today, plus the list of
  `meal_name`s logged so far.
- **Calendar** — a date picker feeding the same query against a chosen
  past date; the same query over a date range gives a trend view later.
- **Logging** — pick a date, then either select a saved recipe and enter
  portions (computes `per-portion macros × portions`, inserts one
  `meal_log` row), or build a meal ad hoc from several searched/scanned/
  manually-entered foods (one `meal_log_items` row each, summed into one
  `meal_log` header).
- **Create recipe** — name, yield, and repeated ingredient rows using the
  same food lookup as Logging → writes to `recipes` + `recipe_items`.

Search ("banana" → results) is one query against `foods`:

```sql
SELECT * FROM foods
WHERE name ILIKE '%' || %s || '%' AND (origin = 'source' OR user_id = %s)
LIMIT 20;
```

Barcode scan and manual entry feed the same lookup — three ways in, one
table underneath.

---

## Key principles (why, not just what)

- **Tables, not databases, for the source/manual split.** Schemas exist if
  you later want Postgres enforcing the pipeline/user boundary
  structurally.
- **Physical separation over a source column.** The pipeline script
  cannot touch manual, recipe, or log data — not by convention, by table
  boundary.
- **`UNION ALL`, not `UNION`.** No dedup needed; avoids an unnecessary
  sort/hash at scale.
- **Composite `(food_id, food_origin)` key, reused everywhere.**
  `recipe_items` and `meal_log_items` both point at "a row in `foods`" and
  both use the same pair — one pattern, multiple consumers.
- **Transform logic lives in SQL, not pandas.** Python only fetches and
  decompresses files.
- **Staging table + transactional swap for backfills; upsert for
  incrementals.** Match the mechanism to how often the source actually
  changes.
- **Indexes after loading, `COPY` instead of row-by-row inserts.**
- **Macros stored per 100g, always** — recipe and daily totals are
  queries, never stored columns.
- **`meal_log` snapshots its totals at log time**, regardless of source.
  Editing a recipe next month shouldn't rewrite what you already logged
  eating this month — and it's what keeps the daily rollup query free of
  any join back to recipes or foods.
- **Manual foods are scoped per user.** One person's hand-typed entry
  shouldn't appear in someone else's search results.
- **Every user-facing query is parameterized, never string-built**,
  especially now that login input is a real trust boundary.

---

## Build order

**Phase 0 — Environment**
Install Postgres locally. Python virtualenv with `psycopg` and `requests`.

**Phase 1 — Bronze**
Download the USDA and OFF full dumps, decompress, `COPY` raw rows into
bronze tables with a `loaded_at` column.

**Phase 2 — Silver → Gold (initial backfill)**
SQL transform: pivot USDA's nutrients, reconcile OFF's units, apply the
calorie sanity check. Stage, verify row count, transactional swap into
`foods_source`, index `barcode`. Reused unchanged as USDA's monthly job.

**Phase 3 — Users and auth**
Create `users`. Build password hashing and the login form; wire
`st.session_state` to hold the current `user_id`. Everything after this
phase needs it, so it comes before any user-owned table gets real data.

**Phase 4 — Manual entries + the view**
Create `foods_manual` (with `user_id`) and the `foods` view. Prove the
barcode/search lookup, scoped correctly to the logged-in user, before any
UI.

**Phase 5 — Logging**
Create `meal_log` and `meal_log_items`. Build the ad hoc path first
(search → add grams → save), then the daily rollup query.

**Phase 6 — Recipes**
Create `recipes` and `recipe_items`. Write the per-portion query, then the
recipe-based logging path into `meal_log` (`source_type = 'recipe'`).

**Phase 7 — Streamlit app**
Wire all four tabs behind the login gate. By this point it's mostly
plumbing — the hard design decisions are already made.

**Phase 8 — Incremental ingestion**
OFF daily delta job with `ON CONFLICT` upsert, logged in `pipeline_runs`.
Cron for OFF daily, USDA monthly.

**Phase 9 — Extensions**
Daily targets, trend charts, schemas for pipeline/user separation if you
want Postgres enforcing it rather than table naming.

---

## Learn in this order

1. SQL — `SELECT`, `JOIN`, `GROUP BY`, conditional aggregation, later
   window functions.
2. `psycopg` + `COPY` — bulk loading from Python into Postgres.
3. Idempotency and transactional DDL.
4. Password hashing and session state — the layer that makes per-user
   data actually private.
5. `ON CONFLICT` upserts and cron scheduling.
6. Streamlit — a weekend, once everything under it works.
