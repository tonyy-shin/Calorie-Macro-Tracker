"""
Phase 7 - tests for barcode lookup
barcode_variants and lookup_barcode (app_queries.py), and parse_product /
fetch_product (off_api.py). The live API is never called: fetch_product is
tested with a fake requests.get. Throwaway users; cleaned up in finally.

Run: python src/python/test_barcode.py

@author Tony Shin <tonyshin4065@gmail.com>
"""

import uuid

import psycopg
import requests

import off_api
from app_queries import barcode_variants, lookup_barcode
from off_api import OffUnavailable, fetch_product, parse_product

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


def close(a, b, tol=1e-6):
    return a is not None and abs(a - b) < tol


# =====================================================================
# barcode_variants (no database)
# =====================================================================
v = barcode_variants("049000028911")              # UPC-A as printed
check("UPC-A gets EAN-13 form", "0049000028911" in v, v)
check("UPC-A gets GTIN-14 form", "00049000028911" in v, v)
check("UPC-A keeps itself", "049000028911" in v, v)
check("EAN-13 gets UPC-A form", "049000028911" in barcode_variants("0049000028911"))
check("spaces and dashes ignored", "049000028911" in barcode_variants(" 0 49000-028911 "))
check("EAN-8 kept", "12345670" in barcode_variants("12345670"))
check("empty input gives nothing", barcode_variants("") == [] and barcode_variants("000") == [])

# =====================================================================
# parse_product (no network)
# =====================================================================
found = {
    "code": "3017620422003", "status": 1, "status_verbose": "product found",
    "product": {
        "code": "3017620422003", "product_name": " Nutella ",
        "brands": "Ferrero, Nutella",
        "nutriments": {"energy-kcal_100g": 539, "proteins_100g": 6.3,
                       "carbohydrates_100g": "57.5", "fat_100g": 30.9},
    },
}
p = parse_product(found)
check("found product parsed", p is not None and p["name"] == "Nutella", p)
check("first brand only", p["brand"] == "Ferrero", p)
check("barcode carried", p["barcode"] == "3017620422003", p)
check("macros parsed, string number accepted",
      close(p["kcal"], 539) and close(p["carbs_g"], 57.5) and close(p["fat_g"], 30.9), p)

check("status 0 means not found",
      parse_product({"code": "1", "status": 0, "status_verbose": "product not found"}) is None)
check("junk body is not found", parse_product("nope") is None and parse_product(None) is None)

kj_only = {"status": 1, "product": {"product_name": "Juice",
           "nutriments": {"energy-kj_100g": 184.1, "proteins_100g": 0.5}}}
p = parse_product(kj_only)
check("kJ converted to kcal when kcal missing", close(p["kcal"], 44.0, 0.01), p)
check("missing macros come back as None", p["carbs_g"] is None and p["fat_g"] is None, p)

bad = {"status": 1, "product": {"product_name": "", "nutriments":
       {"energy-kcal_100g": "n/a", "proteins_100g": -3, "fat_100g": True}}}
p = parse_product(bad)
check("blank name -> None", p["name"] is None, p)
check("non-numeric, negative and bool macros -> None",
      p["kcal"] is None and p["protein_g"] is None and p["fat_g"] is None, p)


# =====================================================================
# fetch_product with a fake requests.get (no network)
# =====================================================================
class FakeResponse:
    def __init__(self, status, body=None, json_ok=True):
        self.status_code = status
        self._body = body
        self._json_ok = json_ok

    def json(self):
        if not self._json_ok:
            raise ValueError("not json")
        return self._body


calls = []


def fake_get(response=None, error=None):
    def _get(url, params=None, headers=None, timeout=None):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        if error:
            raise error
        return response
    return _get


real_get = requests.get
try:
    off_api.requests.get = fake_get(FakeResponse(200, found))
    p = fetch_product("3017620422003")
    check("200 -> parsed product", p is not None and p["name"] == "Nutella")
    check("barcode is in the URL", "3017620422003" in calls[-1]["url"])
    check("User-Agent identifies the app",
          calls[-1]["headers"]["User-Agent"].startswith("CalorieMacroTracker/"))
    check("a timeout is set", calls[-1]["timeout"] is not None)

    off_api.requests.get = fake_get(FakeResponse(404, {"status": 0}))
    check("404 -> None (not found)", fetch_product("1") is None)

    for status in (429, 500, 503):
        off_api.requests.get = fake_get(FakeResponse(status))
        try:
            fetch_product("1")
            check(f"{status} -> OffUnavailable", False, "no error")
        except OffUnavailable:
            check(f"{status} -> OffUnavailable", True)

    off_api.requests.get = fake_get(error=requests.Timeout("slow"))
    try:
        fetch_product("1")
        check("timeout -> OffUnavailable", False, "no error")
    except OffUnavailable:
        check("timeout -> OffUnavailable", True)

    off_api.requests.get = fake_get(FakeResponse(200, json_ok=False))
    try:
        fetch_product("1")
        check("non-JSON -> OffUnavailable", False, "no error")
    except OffUnavailable:
        check("non-JSON -> OffUnavailable", True)
finally:
    off_api.requests.get = real_get


# =====================================================================
# lookup_barcode (database)
# =====================================================================
conn = psycopg.connect(dbname="meal_tracker", user="tonyyshin", autocommit=True)
cur = conn.cursor()
tag = uuid.uuid4().hex[:6]
# a barcode no real product uses: 99 + random digits
digits = str(int(tag, 16) % 10**9).zfill(9)
upc = f"99{digits}1"                 # 12 digits, as printed on a US package
user_ids = []
try:
    for who in ("a", "b"):
        cur.execute("insert into users (email, password) values (%s, %s) returning id",
                    (f"barcode_{who}_{tag}@example.com", "not-a-real-hash"))
        user_ids.append(cur.fetchone()[0])
    user_a, user_b = user_ids

    # stored the way OFF often stores it: EAN-13 with a leading zero
    cur.execute(
        "insert into foods_manual (user_id, barcode, name, kcal, protein_g, carbs_g, fat_g) "
        "values (%s, %s, %s, 100, 1, 2, 3) returning id",
        (user_a, "0" + upc, f"padded {tag}"))
    padded_id = cur.fetchone()[0]

    f = lookup_barcode(conn, upc, user_a)
    check("12-digit scan finds 13-digit stored barcode",
          f is not None and f["id"] == padded_id, f)
    check("14-digit form finds it too",
          (lookup_barcode(conn, "00" + upc, user_a) or {}).get("id") == padded_id)
    check("other user can't see it", lookup_barcode(conn, upc, user_b) is None)
    check("unknown barcode -> None", lookup_barcode(conn, f"98{digits}7", user_a) is None)
    check("empty barcode -> None", lookup_barcode(conn, "", user_a) is None)
finally:
    cur.execute("delete from foods_manual where user_id = any(%s)", (user_ids,))
    cur.execute("delete from users where id = any(%s)", (user_ids,))
    conn.close()

print(f"\n{passed} passed, {failed} failed")
