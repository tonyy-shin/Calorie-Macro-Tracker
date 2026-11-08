"""
Phase 7 — manual food entry

Adds a user-owned food to foods_manual. Macros are per 100 g, the same
unit as foods_source, so manual foods plug into the foods view, search,
recipes, and logging with no special cases.

@author Tony Shin <tonyshin4065@gmail.com>
"""

import psycopg


def _clean_text(label, value):
    """Strip a text field; empty becomes None."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    value = value.strip()
    return value or None


def _clean_number(label, value, upper):
    """A real number (not a bool) between 0 and upper."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    if not 0 <= value <= upper:
        raise ValueError(f"{label} must be between 0 and {upper} per 100 g")
    return float(value)


def add_manual_food(conn, user_id, name, kcal, protein_g, carbs_g, fat_g,
                    brand=None, barcode=None):
    """
    Insert one row into foods_manual, owned by user_id.

    @param conn      psycopg connection
    @param user_id   id of the owning user
    @param name      food name (required)
    @param kcal      kcal per 100 g, 0-900
    @param protein_g protein per 100 g, 0-100
    @param carbs_g   carbs per 100 g, 0-100
    @param fat_g     fat per 100 g, 0-100
    @param brand     optional
    @param barcode   optional
    @return id of the new foods_manual row
    @raises ValueError on bad input or unknown user
    """
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise ValueError("user_id must be an int")

    name = _clean_text("name", name)
    if name is None:
        raise ValueError("name is required")
    brand = _clean_text("brand", brand)
    barcode = _clean_text("barcode", barcode)

    kcal = _clean_number("kcal", kcal, 900)          # pure fat is ~900 kcal/100 g
    protein_g = _clean_number("protein_g", protein_g, 100)
    carbs_g = _clean_number("carbs_g", carbs_g, 100)
    fat_g = _clean_number("fat_g", fat_g, 100)
    if protein_g + carbs_g + fat_g > 100.01:          # small float tolerance
        raise ValueError("protein + carbs + fat can't exceed 100 g per 100 g")

    sql = """
        insert into foods_manual
            (user_id, barcode, name, brand, kcal, protein_g, carbs_g, fat_g)
        values
            (%(user_id)s, %(barcode)s, %(name)s, %(brand)s,
             %(kcal)s, %(protein_g)s, %(carbs_g)s, %(fat_g)s)
        returning id
    """
    params = {
        "user_id": user_id, "barcode": barcode, "name": name, "brand": brand,
        "kcal": kcal, "protein_g": protein_g, "carbs_g": carbs_g, "fat_g": fat_g,
    }

    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()[0]
    except psycopg.errors.ForeignKeyViolation:
        raise ValueError(f"user {user_id} does not exist") from None
