"""
Phase 7 - Live Open Food Facts lookup for one scanned barcode

Used only when a scanned barcode isn't in the local database. Open Food
Facts allows its live API for apps as long as 1 API call = 1 real user
scan; bulk data still comes only from the pipeline's exports. The app
caches each lookup so Streamlit reruns don't repeat the call.

Nothing here writes to the database. A found product is shown to the user,
who saves it into their own foods_manual, so the pipeline-owned
foods_source table is never touched by the app.

@author Tony Shin <tonyshin4065@gmail.com>
"""

import requests

API_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
FIELDS = "code,product_name,brands,nutriments"
# OFF asks API users to identify their app in the User-Agent.
USER_AGENT = "CalorieMacroTracker/0.1 (https://github.com/tonyy-shin/Calorie-Macro-Tracker)"


class OffUnavailable(Exception):
    """Open Food Facts couldn't be reached or returned an error."""


def _number(value):
    """OFF sometimes sends numbers as strings, or junk. None if unusable."""
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def parse_product(body):
    """
    Turn an OFF API response body into the app's food shape.
    @param body - decoded JSON from the product endpoint
    @return dict: barcode, name, brand, kcal, protein_g, carbs_g, fat_g
            (all per 100 g; any macro may be None), or None if not found
    """
    if not isinstance(body, dict) or body.get("status") != 1:
        return None
    product = body.get("product") or {}
    n = product.get("nutriments") or {}

    kcal = _number(n.get("energy-kcal_100g"))
    if kcal is None:
        kj = _number(n.get("energy-kj_100g"))
        if kj is not None:
            kcal = kj / 4.184          # label gave kJ only

    name = (product.get("product_name") or "").strip() or None
    brand = (product.get("brands") or "").split(",")[0].strip() or None
    return {
        "barcode": str(product.get("code") or body.get("code") or ""),
        "name": name,
        "brand": brand,
        "kcal": kcal,
        "protein_g": _number(n.get("proteins_100g")),
        "carbs_g": _number(n.get("carbohydrates_100g")),
        "fat_g": _number(n.get("fat_100g")),
    }


def fetch_product(barcode, timeout=8):
    """
    Look up one barcode on Open Food Facts.
    @return parsed product dict, or None if OFF doesn't have it
    @raises OffUnavailable on network errors, timeouts, or 5xx/429
    """
    try:
        r = requests.get(
            API_URL.format(barcode=barcode),
            params={"fields": FIELDS},
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise OffUnavailable(str(e)) from None

    if r.status_code == 404:           # v2 answers 404 for unknown products
        return None
    if r.status_code >= 400:
        raise OffUnavailable(f"HTTP {r.status_code}")
    try:
        return parse_product(r.json())
    except ValueError:
        raise OffUnavailable("response was not JSON") from None
