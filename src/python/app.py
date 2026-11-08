"""
Phase 7 — Streamlit app

Login gate + five pages (Home, Calendar, Logging, Create recipe, My recipes).
All data work goes through the tested functions in auth.py,
meal_logging.py, recipes.py, manual_foods.py and app_queries.py; this
file is only UI.

Streamlit reruns this whole script top to bottom on every interaction.
Anything that must survive a rerun (logged-in user, the foods picked so
far) lives in st.session_state.

Run from the repo root:  streamlit run src/python/app.py

@author Tony Shin <tonyshin4065@gmail.com>
"""

import datetime as dt
import uuid

import psycopg
import streamlit as st

from app_queries import food_data_status, list_recipes, lookup_barcode
from auth import register_user, verify_user
from manual_foods import add_manual_food
from meal_editing import delete_meal, get_meal, get_meals_for_day, update_meal
from meal_logging import get_daily_rollup, log_ad_hoc_meal, search_foods
from off_api import OffUnavailable, fetch_product
from recipes import (create_recipe, delete_recipe, get_recipe,
                     log_recipe_meal, update_recipe)

# Barcode scanning is optional: needs `sudo apt install libzbar0` and
# `pip install pyzbar pillow`. Without them the camera option just hides.
try:
    from PIL import Image
    from pyzbar.pyzbar import decode as decode_barcode
    HAS_SCANNER = True
except ImportError:
    HAS_SCANNER = False

st.set_page_config(page_title="Macro Tracker", page_icon="🥗")

# Column order of search_foods' SELECT list (meal_logging.py). Keep in
# sync if that query changes. lookup_barcode returns dicts, which pass
# straight through as_food.
SEARCH_COLS = ("id", "name", "brand", "origin",
               "kcal", "protein_g", "carbs_g", "fat_g")
MACROS = ("kcal", "protein_g", "carbs_g", "fat_g")


# =====================================================================
# Connection
# =====================================================================
@st.cache_resource
def _connect():
    # Credentials come from .streamlit/secrets.toml, never from code.
    return psycopg.connect(**st.secrets["db"], autocommit=True)


def get_conn():
    """One shared connection; reconnect if Postgres dropped it."""
    conn = _connect()
    if conn.closed or conn.broken:
        _connect.clear()
        conn = _connect()
    return conn


conn = get_conn()


# =====================================================================
# Small helpers
# =====================================================================
def as_food(row):
    return row if isinstance(row, dict) else dict(zip(SEARCH_COLS, row, strict=True))


def fmt(value, digits=0):
    return "—" if value is None else f"{value:.{digits}f}"


def food_label(f):
    brand = f" · {f['brand']}" if f.get("brand") else ""
    mine = " (mine)" if f["origin"] == "manual" else ""
    if any(f[m] is None for m in MACROS):
        return f"{f['name']}{brand}{mine} — missing macros"
    return f"{f['name']}{brand}{mine} — {fmt(f['kcal'])} kcal/100 g"


def show_macros(totals):
    cols = st.columns(4)
    cols[0].metric("Calories", fmt(totals.get("kcal")))
    cols[1].metric("Protein", f"{fmt(totals.get('protein_g'))} g")
    cols[2].metric("Carbs", f"{fmt(totals.get('carbs_g'))} g")
    cols[3].metric("Fat", f"{fmt(totals.get('fat_g'))} g")


def flash(message):
    """Show a success message after the next rerun."""
    st.session_state.flash = message


# =====================================================================
# Login gate
# =====================================================================
def log_in(user_id, email):
    st.session_state.user_id = user_id
    st.session_state.email = email
    st.rerun()


def login_page():
    st.title("🥗 Macro Tracker")
    login_tab, register_tab = st.tabs(["Log in", "Create account"])

    with login_tab:
        with st.form("login"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Log in", type="primary"):
                user_id = verify_user(conn, email.strip(), password)
                if user_id:
                    log_in(user_id, email.strip())
                else:
                    st.error("Wrong email or password.")

    with register_tab:
        with st.form("register"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            confirm = st.text_input("Confirm password", type="password")
            if st.form_submit_button("Create account", type="primary"):
                if not email.strip() or not password:
                    st.error("Email and password are required.")
                elif password != confirm:
                    st.error("Passwords don't match.")
                elif len(password) < 8:
                    st.error("Use at least 8 characters.")
                else:
                    try:
                        new_id = register_user(conn, email.strip(), password)
                    except psycopg.errors.UniqueViolation:
                        new_id = None
                    if new_id:
                        log_in(new_id, email.strip())
                    else:
                        st.error("That email already has an account.")


if "user_id" not in st.session_state:
    login_page()
    st.stop()

uid = st.session_state.user_id
today = dt.date.today()


# =====================================================================
# Sidebar
# =====================================================================
with st.sidebar:
    st.write(f"Logged in as **{st.session_state.email}**")
    status = food_data_status(conn)
    if status and status["last_success"]:
        age = dt.datetime.now(dt.timezone.utc) - status["last_success"]
        when = ("today" if age.days == 0 else
                "yesterday" if age.days == 1 else f"{age.days} days ago")
        st.caption(f"Food data updated {when}")
        if status["last_failed"] or age.days >= 3:
            st.caption("⚠️ Daily update isn't running. Check "
                       "`journalctl --user -u off-update`.")
    else:
        st.caption("Food data: daily updates not set up yet")
    if st.button("Log out"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

if message := st.session_state.pop("flash", None):
    st.success(message)


# =====================================================================
# Reusable pieces
# =====================================================================
def day_view(day, prefix):
    """Totals for a day, then each meal with an Edit button."""
    rollup = get_daily_rollup(conn, uid, day) or {}
    show_macros(rollup)

    meals = get_meals_for_day(conn, uid, day)
    if not meals:
        st.caption("Nothing logged for this day.")
        return

    editing_key = f"{prefix}_editing"
    for m in meals:
        c1, c2, c3 = st.columns([5, 2, 1])
        label = m["meal_name"] or "Untitled"
        if m["source_type"] == "recipe":
            label += f" · {m['portions']:g} portion(s)"
        c1.write(label)
        c2.write(f"{fmt(m['kcal'])} kcal")
        if c3.button("✎", key=f"{prefix}_edit_{m['id']}", help="Edit or delete"):
            st.session_state[editing_key] = m["id"]
            st.rerun()

    meal_id = st.session_state.get(editing_key)
    if meal_id in {m["id"] for m in meals}:
        st.divider()
        meal_editor(meal_id, prefix)


def meal_editor(meal_id, prefix):
    """Edit name, date, and items (ad hoc) or portions (recipe); or delete."""
    k = f"{prefix}_m{meal_id}"

    # Load once per meal, before its widgets are drawn in this run.
    if st.session_state.get(f"{prefix}_loaded") != meal_id:
        meal = get_meal(conn, uid, meal_id)
        st.session_state[f"{k}_name"] = meal["meal_name"] or ""
        st.session_state[f"{k}_date"] = meal["log_date"]
        st.session_state[f"{k}_type"] = meal["source_type"]
        if meal["source_type"] == "recipe":
            st.session_state[f"{k}_portions"] = int(meal["portions"])
        else:
            st.session_state[f"{k}_basket"] = [
                {"row": uuid.uuid4().hex, **item} for item in meal["items"]]
        st.session_state.pop(f"{k}_confirm", None)
        st.session_state[f"{prefix}_loaded"] = meal_id

    is_recipe = st.session_state[f"{k}_type"] == "recipe"
    st.subheader("Edit meal")
    name = st.text_input("Meal name", key=f"{k}_name")
    new_date = st.date_input("Date", max_value=today, key=f"{k}_date")

    if is_recipe:
        portions = st.number_input("Portions", min_value=1, step=1, key=f"{k}_portions")
        st.caption("Macros scale with portions, using the numbers from when you logged it.")
        basket = None
    else:
        basket = food_picker(f"{k}_basket")

    def done(message):
        st.session_state.pop(f"{prefix}_editing", None)
        st.session_state.pop(f"{prefix}_loaded", None)
        flash(message)
        st.rerun()

    c1, c2 = st.columns(2)
    if c1.button("Save changes", type="primary", key=f"{k}_save",
                 disabled=(basket is not None and not basket)):
        try:
            if is_recipe:
                update_meal(conn, uid, meal_id, new_date, name, portions=int(portions))
            else:
                update_meal(conn, uid, meal_id, new_date, name, items=basket_items(basket))
        except ValueError as e:
            st.error(str(e))
        else:
            done("Meal updated.")
    if c2.button("Cancel", key=f"{k}_cancel"):
        st.session_state.pop(f"{prefix}_editing", None)
        st.session_state.pop(f"{prefix}_loaded", None)
        st.rerun()

    confirm = st.checkbox("Delete this meal", key=f"{k}_confirm")
    if confirm and st.button("Confirm delete", key=f"{k}_delete"):
        try:
            delete_meal(conn, uid, meal_id)
        except ValueError as e:
            st.error(str(e))
        else:
            done("Meal deleted.")


def manual_food_form(key):
    """'Can't find it?' form. The new food shows up in search right after."""
    with st.expander("Can't find it? Add a food manually"):
        with st.form(f"{key}_manual", clear_on_submit=True):
            name = st.text_input("Name")
            c1, c2 = st.columns(2)
            brand = c1.text_input("Brand (optional)")
            barcode = c2.text_input("Barcode (optional)")
            st.caption("Values per 100 g — check the nutrition label.")
            m = st.columns(4)
            kcal = m[0].number_input("kcal", min_value=0.0, max_value=900.0)
            protein = m[1].number_input("Protein g", min_value=0.0, max_value=100.0)
            carbs = m[2].number_input("Carbs g", min_value=0.0, max_value=100.0)
            fat = m[3].number_input("Fat g", min_value=0.0, max_value=100.0)
            if st.form_submit_button("Save food"):
                try:
                    add_manual_food(conn, uid, name, kcal, protein, carbs, fat,
                                    brand=brand, barcode=barcode)
                except ValueError as e:
                    st.error(str(e))
                else:
                    st.success(f"Saved {name.strip()}. Search for it above.")


def find_foods(key):
    """Search or barcode mode. Returns a list of food dicts."""
    mode = st.radio("Find a food", ["Search", "Barcode"], horizontal=True,
                    key=f"{key}_mode")

    if mode == "Search":
        term = st.text_input("Search foods", placeholder="e.g. banana",
                             key=f"{key}_q").strip()
        if not term:
            return []
        results = [as_food(r) for r in search_foods(conn, term, uid)]
        if not results:
            st.info("No matches.")
        return results

    code = st.text_input("Barcode", key=f"{key}_bc").strip()
    if HAS_SCANNER and st.toggle("Scan with camera", key=f"{key}_cam"):
        photo = st.camera_input("Point the camera at the barcode",
                                key=f"{key}_photo")
        if photo:
            found = decode_barcode(Image.open(photo))
            if found:
                code = found[0].data.decode("utf-8")
                st.caption(f"Scanned: {code}")
            else:
                st.warning("No barcode found. Try again, closer and in focus.")
    if not code:
        return []
    food = lookup_barcode(conn, code, uid)
    if food is not None:
        return [food]

    # Not in the local data (e.g. a product newer than the last export):
    # ask Open Food Facts live, once per barcode.
    try:
        with st.spinner("Not in the local database. Checking Open Food Facts..."):
            product = off_lookup(code)
    except OffUnavailable:
        st.warning("Couldn't reach Open Food Facts right now. "
                   "Try again, or add the food manually below.")
        return []
    if product is None:
        st.info("Open Food Facts doesn't have this barcode either. "
                "Add it manually below.")
        return []
    save_off_product_form(key, code, product)
    return []


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def off_lookup(code):
    """
    Cached so Streamlit's reruns don't repeat the call: OFF allows one
    API call per real scan. Errors aren't cached, so a retry can succeed.
    """
    return fetch_product(code)


def save_off_product_form(key, code, p):
    """Show an OFF product, prefilled, for the user to save as their own food."""
    title = p["name"] or "an unnamed product"
    if p["brand"]:
        title += f" ({p['brand']})"
    st.success(f"Found on Open Food Facts: {title}")

    labels = {"kcal": "calories", "protein_g": "protein",
              "carbs_g": "carbs", "fat_g": "fat"}
    missing = [labels[m] for m in MACROS if p[m] is None]
    if missing:
        st.warning(f"Open Food Facts has no {', '.join(missing)} for this "
                   "product. Fill them in from the label before saving.")

    def start(m, upper):
        # number_input refuses a default outside its range; clamp bad data
        return min(float(p[m] or 0.0), upper)

    with st.form(f"{key}_off_{code}"):
        name = st.text_input("Name", value=p["name"] or "")
        brand = st.text_input("Brand (optional)", value=p["brand"] or "")
        st.caption("Values per 100 g. Check them against the label.")
        c = st.columns(4)
        kcal = c[0].number_input("kcal", min_value=0.0, max_value=900.0,
                                 value=start("kcal", 900.0))
        protein = c[1].number_input("Protein g", min_value=0.0, max_value=100.0,
                                    value=start("protein_g", 100.0))
        carbs = c[2].number_input("Carbs g", min_value=0.0, max_value=100.0,
                                  value=start("carbs_g", 100.0))
        fat = c[3].number_input("Fat g", min_value=0.0, max_value=100.0,
                                value=start("fat_g", 100.0))
        if st.form_submit_button("Save to my foods", type="primary"):
            try:
                add_manual_food(conn, uid, name, kcal, protein, carbs, fat,
                                brand=brand, barcode=code)
            except ValueError as e:
                st.error(str(e))
            else:
                flash(f"Saved {name.strip()}. It's ready to add below.")
                st.rerun()


def food_picker(key):
    """
    Find foods, choose grams, collect them in a basket.
    The basket lives in st.session_state[key] so it survives reruns.
    Returns the basket (list of dicts).
    """
    basket = st.session_state.setdefault(key, [])

    results = find_foods(key)
    if results:
        choice = st.selectbox("Result", range(len(results)),
                              format_func=lambda i: food_label(results[i]),
                              key=f"{key}_pick")
        grams = st.number_input("Grams", min_value=1.0, value=100.0,
                                step=10.0, key=f"{key}_grams")
        if st.button("Add", key=f"{key}_add"):
            f = results[choice]
            basket.append({"row": uuid.uuid4().hex,
                           "food_id": f["id"], "food_origin": f["origin"],
                           "name": f["name"], "grams": grams,
                           **{m: f[m] for m in MACROS}})

    manual_food_form(key)

    if basket:
        st.markdown("**Added so far**")
        for item in list(basket):
            c1, c2, c3 = st.columns([5, 2, 1])
            if item["name"] is None:
                c1.warning("This food no longer exists. Remove it.")
            else:
                c1.write(item["name"])
            # Each row has its own id so widget keys survive removals.
            item["grams"] = c2.number_input(
                "Grams", min_value=1.0, value=float(item["grams"]),
                step=10.0, key=f"{key}_g_{item['row']}",
                label_visibility="collapsed")
            if c3.button("✕", key=f"{key}_rm_{item['row']}"):
                basket.remove(item)
                st.rerun()
        # Display-only preview; the stored snapshot is computed in SQL.
        preview = {m: sum((it[m] or 0) * it["grams"] / 100 for it in basket)
                   for m in MACROS}
        st.caption("Preview")
        show_macros(preview)
    return basket


def basket_items(basket):
    """The (food_id, food_origin, grams) tuples the backend expects."""
    return [(it["food_id"], it["food_origin"], it["grams"]) for it in basket]


# =====================================================================
# Tabs
# =====================================================================
# A keyed radio instead of st.tabs: st.tabs forgets which tab is open
# whenever the page reruns (e.g. after switching "From a recipe"), which
# snapped users back to Home. The radio's choice lives in session_state,
# and only the chosen page runs its queries.
PAGES = ["Home", "Calendar", "Logging", "Create recipe", "My recipes"]
page = st.radio("Page", PAGES, horizontal=True, key="page",
                label_visibility="collapsed")
st.divider()

if page == "Home":
    st.subheader(f"Today · {today:%a %b %d}")
    day_view(today, "home")

if page == "Calendar":
    day = st.date_input("Pick a day", value=today, max_value=today,
                        key="cal_date")
    day_view(day, "cal")

if page == "Logging":
    log_date = st.date_input("Date", value=today, max_value=today,
                             key="log_date")
    kind = st.radio("Meal type", ["Build a meal", "From a recipe"],
                    horizontal=True, key="log_kind")

    if kind == "Build a meal":
        meal_name = st.text_input("Meal name (optional)", key="adhoc_name")
        basket = food_picker("adhoc_basket")
        if st.button("Log meal", type="primary", disabled=not basket,
                     key="log_adhoc"):
            try:
                log_ad_hoc_meal(conn, uid, log_date, meal_name.strip() or None,
                                basket_items(basket))
            except ValueError as e:
                st.error(str(e))
            else:
                st.session_state.adhoc_basket = []
                flash(f"Logged {meal_name.strip() or 'meal'} for {log_date}.")
                st.rerun()

    else:
        recipes = list_recipes(conn, uid)
        if not recipes:
            st.info("No recipes yet. Make one in the Create recipe tab.")
        else:
            idx = st.selectbox("Recipe", range(len(recipes)),
                               format_func=lambda i: recipes[i]["name"],
                               key="log_recipe_pick")
            recipe = recipes[idx]
            if not recipe["complete"]:
                st.warning("An ingredient in this recipe is missing or has "
                           "no macros, so it can't be logged.")
            st.caption(f"Per portion (recipe makes {recipe['yield_portions']})")
            show_macros(recipe)
            portions = st.number_input("Portions", min_value=1, value=1,
                                       step=1, key="log_portions")
            if st.button("Log meal", type="primary", key="log_recipe",
                         disabled=not recipe["complete"]):
                try:
                    log_recipe_meal(conn, uid, log_date, recipe["id"],
                                    int(portions))
                except ValueError as e:
                    st.error(str(e))
                else:
                    flash(f"Logged {portions} × {recipe['name']} "
                          f"for {log_date}.")
                    st.rerun()

if page == "Create recipe":
    name = st.text_input("Recipe name", key="recipe_name")
    yield_portions = st.number_input("Makes how many portions?", min_value=1,
                                     value=4, step=1, key="recipe_yield")
    basket = food_picker("recipe_basket")
    if st.button("Save recipe", type="primary", key="save_recipe",
                 disabled=not (basket and name.strip())):
        try:
            create_recipe(conn, uid, name.strip(), int(yield_portions),
                          basket_items(basket))
        except ValueError as e:
            st.error(str(e))
        else:
            st.session_state.recipe_basket = []
            flash(f"Saved recipe {name.strip()}.")
            st.rerun()

if page == "My recipes":
    recipes = list_recipes(conn, uid)
    if not recipes:
        st.info("No recipes yet. Make one in the Create recipe tab.")
    else:
        names = {r["id"]: r["name"] for r in recipes}
        rid = st.selectbox("Recipe to edit", list(names), format_func=names.get,
                           key="edit_pick")

        # Load the chosen recipe into the edit widgets once per selection.
        # Must happen before those widgets are drawn in this run.
        if st.session_state.get("edit_loaded") != rid:
            rec = get_recipe(conn, uid, rid)
            st.session_state.edit_basket = [
                {"row": uuid.uuid4().hex, **item} for item in rec["items"]]
            st.session_state.edit_name = rec["name"]
            st.session_state.edit_yield = rec["yield_portions"]
            st.session_state.pop("edit_confirm", None)
            st.session_state.edit_loaded = rid

        name = st.text_input("Recipe name", key="edit_name")
        yield_portions = st.number_input("Makes how many portions?",
                                         min_value=1, step=1, key="edit_yield")
        st.caption("Change grams in the list, remove with ✕, or add more below. "
                   "Meals you already logged keep their original numbers.")
        basket = food_picker("edit_basket")

        if st.button("Save changes", type="primary", key="edit_save",
                     disabled=not (basket and name.strip())):
            try:
                update_recipe(conn, uid, rid, name.strip(), int(yield_portions),
                              basket_items(basket))
            except ValueError as e:
                st.error(str(e))
            else:
                st.session_state.edit_loaded = None   # reload fresh from the DB
                flash(f"Saved changes to {name.strip()}.")
                st.rerun()

        with st.expander("Delete this recipe"):
            st.caption("Meals you already logged from it stay in your history.")
            confirm = st.checkbox(f"Yes, delete {names[rid]}", key="edit_confirm")
            if st.button("Delete recipe", disabled=not confirm, key="edit_delete"):
                try:
                    delete_recipe(conn, uid, rid)
                except ValueError as e:
                    st.error(str(e))
                else:
                    st.session_state.edit_loaded = None
                    flash(f"Deleted {names[rid]}.")
                    st.rerun()
