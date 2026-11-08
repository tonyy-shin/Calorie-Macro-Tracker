"""
Phase 7 — read queries the Streamlit app needs that don't exist yet

list_recipes   — a user's recipes with per-portion macros (Logging tab)
lookup_barcode — one food by barcode, scoped to the user (barcode mode)

@author Tony Shin <tonyshin4065@gmail.com>
"""

from psycopg.rows import dict_row


def list_recipes(conn, user_id):
    """
    All of a user's recipes with per-portion macros, computed in SQL.

    LEFT JOIN so a recipe whose ingredient vanished (e.g. after a USDA
    refresh regenerates ids) still shows up, flagged complete = false,
    instead of silently disappearing.

    @return list of dicts: id, name, yield_portions, kcal, protein_g,
            carbs_g, fat_g (per portion), complete
    """
    sql = """
        select
            r.id,
            r.name,
            r.yield_portions,
            sum(f.kcal      * ri.grams / 100.0) / r.yield_portions as kcal,
            sum(f.protein_g * ri.grams / 100.0) / r.yield_portions as protein_g,
            sum(f.carbs_g   * ri.grams / 100.0) / r.yield_portions as carbs_g,
            sum(f.fat_g     * ri.grams / 100.0) / r.yield_portions as fat_g,
            bool_and(f.kcal is not null and f.protein_g is not null
                     and f.carbs_g is not null and f.fat_g is not null)
                as complete
        from recipes r
        join recipe_items ri on ri.recipe_id = r.id
        left join foods f
               on f.id = ri.food_id
              and f.origin = ri.food_origin
              and (f.origin = 'source' or f.user_id = r.user_id)
        where r.user_id = %s
        group by r.id, r.name, r.yield_portions
        order by r.name
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (user_id,))
        return cur.fetchall()


def barcode_variants(barcode):
    """
    The same product's barcode is stored in different lengths by different
    sources: a US UPC-A is 12 digits on the package, but OFF often stores
    it as 13 (EAN-13, leading 0) and USDA as 12 or 14 (GTIN-14). Scanners
    also report UPC-A as EAN-13. Try every zero-padded length.

    @return list of candidate strings (empty if the input has no digits)
    """
    digits = "".join(ch for ch in str(barcode) if ch.isdigit())
    core = digits.lstrip("0")
    if not core:
        return []
    variants = {digits, core}
    for length in (8, 12, 13, 14):
        if len(core) <= length:
            variants.add(core.zfill(length))
    return sorted(variants)


def lookup_barcode(conn, barcode, user_id):
    """
    One food by barcode, matching any zero-padded form of it.
    Order: the user's own manual entry (lets them override bad source
    data), then rows with all four macros, then an exact string match.

    @return dict with the foods view columns, or None
    """
    variants = barcode_variants(barcode)
    if not variants:
        return None
    sql = """
        select id, barcode, name, brand, origin, user_id,
               kcal, protein_g, carbs_g, fat_g
        from foods
        where barcode = any(%(variants)s)
          and (origin = 'source' or user_id = %(user_id)s)
        order by
            (origin = 'manual') desc,
            (kcal is not null and protein_g is not null
             and carbs_g is not null and fat_g is not null) desc,
            (barcode = %(exact)s) desc,
            id
        limit 1
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"variants": variants, "user_id": user_id,
                          "exact": str(barcode).strip()})
        return cur.fetchone()


def food_data_status(conn):
    """
    When Open Food Facts data last updated, from pipeline_runs.
    @return dict: last_success (datetime or None), last_failed (bool,
            True if the most recent run failed), or None if the pipeline
            has never run (table doesn't exist yet)
    """
    sql = """
        select
            max(finished_at) filter (where status = 'success'),
            (array_agg(status order by started_at desc))[1] = 'failed'
        from pipeline_runs
        where source = 'off'
    """
    if conn.execute("select to_regclass('pipeline_runs')").fetchone()[0] is None:
        return None
    last_success, last_failed = conn.execute(sql).fetchone()
    return {"last_success": last_success, "last_failed": bool(last_failed)}
