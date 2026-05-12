"""Focused re-test of 4 public-access / route-ordering bug fixes."""
import os
import sys
import requests

BASE = "https://network-pay-1.preview.emergentagent.com/api"
ADMIN = {"email": "admin@app.com", "password": "Admin@123"}
USER = {"email": "testuser@app.com", "password": "Test@123"}

PASS_RESULTS = []
FAIL_RESULTS = []


def report(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    line = f"[{tag}] {name}"
    if detail:
        line += f"  | {detail}"
    print(line)
    (PASS_RESULTS if ok else FAIL_RESULTS).append(line)
    return ok


def login(creds):
    r = requests.post(f"{BASE}/auth/login", json=creds, timeout=15)
    r.raise_for_status()
    return r.json()["token"]


def main():
    print("=" * 70)
    print("Logging in admin + test user…")
    admin_token = login(ADMIN)
    user_token = login(USER)
    admin_h = {"Authorization": f"Bearer {admin_token}"}
    user_h = {"Authorization": f"Bearer {user_token}"}
    print("Both tokens obtained.\n")

    # ════════════════════════════════════════════════════════════
    # RE-TEST 1 — /products/by-source route ordering
    # ════════════════════════════════════════════════════════════
    print("── RE-TEST 1: /products/by-source ──")

    # (i) trending
    r = requests.get(f"{BASE}/products/by-source", params={"source": "trending", "limit": 5}, timeout=15)
    ok = r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) <= 5
    report("1.i  by-source?source=trending&limit=5 → 200 array(<=5)",
           ok, f"status={r.status_code}, len={len(r.json()) if r.ok else 'n/a'}")

    # (ii) new — sorted by created_at desc
    r = requests.get(f"{BASE}/products/by-source", params={"source": "new", "limit": 5}, timeout=15)
    new_ok = r.status_code == 200 and isinstance(r.json(), list)
    sorted_ok = True
    if new_ok and len(r.json()) > 1:
        dts = [p.get("created_at") for p in r.json() if p.get("created_at")]
        sorted_ok = dts == sorted(dts, reverse=True)
    report("1.ii by-source?source=new&limit=5 → 200, sorted desc",
           new_ok and sorted_ok,
           f"status={r.status_code}, len={len(r.json()) if r.ok else 'n/a'}, sorted={sorted_ok}")

    # (iii) best
    r = requests.get(f"{BASE}/products/by-source", params={"source": "best", "limit": 5}, timeout=15)
    ok = r.status_code == 200 and isinstance(r.json(), list)
    report("1.iii by-source?source=best&limit=5 → 200", ok,
           f"status={r.status_code}, len={len(r.json()) if r.ok else 'n/a'}")

    # (iv) category=Electronics
    r = requests.get(f"{BASE}/products/by-source",
                     params={"source": "category", "category": "Electronics", "limit": 10}, timeout=15)
    if r.status_code == 200:
        rows = r.json()
        cat_ok = all((p.get("category") == "Electronics") for p in rows)
        report("1.iv by-source?source=category&category=Electronics → 200, all rows match",
               cat_ok, f"len={len(rows)}, all_match={cat_ok}")
    else:
        report("1.iv by-source?source=category&category=Electronics", False,
               f"status={r.status_code}, body={r.text[:200]}")

    # (v) no args
    r = requests.get(f"{BASE}/products/by-source", timeout=15)
    ok = r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) <= 10
    report("1.v  by-source (no args) → 200, default trending limit 10", ok,
           f"status={r.status_code}, len={len(r.json()) if r.ok else 'n/a'}")

    # (vi) regression: GET /products/{real_id}
    products_list = requests.get(f"{BASE}/products", timeout=15).json()
    if isinstance(products_list, dict):
        products_list = products_list.get("items", [])
    if products_list:
        real_id = products_list[0]["id"]
        r = requests.get(f"{BASE}/products/{real_id}", timeout=15)
        ok = r.status_code == 200 and r.json().get("id") == real_id
        report(f"1.vi GET /products/{{real id}} → 200 (not mistaken for by-source)",
               ok, f"status={r.status_code}, returned_id={r.json().get('id') if r.ok else 'n/a'}")
    else:
        report("1.vi GET /products/{real id}", False, "no products to test with")

    # (vii) GET /products
    r = requests.get(f"{BASE}/products", timeout=15)
    body = r.json() if r.ok else None
    rows = body if isinstance(body, list) else (body.get("items", []) if body else [])
    ok = r.status_code == 200 and isinstance(rows, list)
    report("1.vii GET /products (list) → 200", ok,
           f"status={r.status_code}, count={len(rows)}")

    # ════════════════════════════════════════════════════════════
    # RE-TEST 2 — Public /shop-layout
    # ════════════════════════════════════════════════════════════
    print("\n── RE-TEST 2: /shop-layout (public) ──")

    # (i) scope=home, no auth
    r = requests.get(f"{BASE}/shop-layout", params={"scope": "home"}, timeout=15)
    ok = r.status_code == 200 and "items" in (r.json() or {}) and isinstance(r.json()["items"], list)
    report("2.i  GET /shop-layout?scope=home (no auth) → 200 with items[]", ok,
           f"status={r.status_code}, items_len={len(r.json().get('items', [])) if r.ok else 'n/a'}")

    # (ii) scope=category, no auth
    r = requests.get(f"{BASE}/shop-layout",
                     params={"scope": "category", "category": "Electronics"}, timeout=15)
    ok = r.status_code == 200 and "items" in (r.json() or {})
    report("2.ii GET /shop-layout?scope=category&category=Electronics (no auth) → 200", ok,
           f"status={r.status_code}, items_len={len(r.json().get('items', [])) if r.ok else 'n/a'}")

    # (iii) Admin GET /admin/shop-layout → 200
    r = requests.get(f"{BASE}/admin/shop-layout", headers=admin_h, timeout=15)
    ok = r.status_code == 200
    report("2.iii Admin GET /admin/shop-layout → 200 (still auth-protected)",
           ok, f"status={r.status_code}")

    # (iv) Non-admin user → 403
    r = requests.get(f"{BASE}/admin/shop-layout", headers=user_h, timeout=15)
    ok = r.status_code == 403
    report("2.iv Non-admin GET /admin/shop-layout → 403", ok,
           f"status={r.status_code}, body={r.text[:120]}")

    # ════════════════════════════════════════════════════════════
    # RE-TEST 3 — Public /services
    # ════════════════════════════════════════════════════════════
    print("\n── RE-TEST 3: /services (public) ──")

    # (i) GET /services no auth
    r = requests.get(f"{BASE}/services", timeout=15)
    body = r.json() if r.ok else None
    ok = r.status_code == 200 and body is not None and "items" in body and "total" in body
    report("3.i  GET /services (no auth) → 200 with items+total", ok,
           f"status={r.status_code}, total={body.get('total') if body else 'n/a'}")

    # (ii) GET /services?category=Plumber no auth
    r = requests.get(f"{BASE}/services", params={"category": "Plumber"}, timeout=15)
    body = r.json() if r.ok else None
    ok = r.status_code == 200 and body is not None and "items" in body
    report("3.ii GET /services?category=Plumber (no auth) → 200", ok,
           f"status={r.status_code}, total={body.get('total') if body else 'n/a'}")

    # (iii) GET /services?lat=12.97&lng=77.59&radius_km=10 → geo:true
    r = requests.get(f"{BASE}/services",
                     params={"lat": 12.97, "lng": 77.59, "radius_km": 10}, timeout=15)
    body = r.json() if r.ok else None
    ok = r.status_code == 200 and body is not None and body.get("geo") is True
    report("3.iii GET /services?lat=12.97&lng=77.59&radius_km=10 (no auth) → 200 geo:true",
           ok, f"status={r.status_code}, geo={body.get('geo') if body else 'n/a'}")

    # ════════════════════════════════════════════════════════════
    # RE-TEST 4 — Public /services/categories
    # ════════════════════════════════════════════════════════════
    print("\n── RE-TEST 4: /services/categories (public) ──")

    r = requests.get(f"{BASE}/services/categories", timeout=15)
    body = r.json() if r.ok else None
    if r.status_code == 200 and body and "categories" in body and isinstance(body["categories"], list):
        cats = body["categories"]
        has_pc = all("provider_count" in c for c in cats) if cats else True
        report("4.i  GET /services/categories (no auth) → 200, categories[] w/ provider_count",
               has_pc, f"status={r.status_code}, n_cats={len(cats)}, all_have_provider_count={has_pc}")
    else:
        report("4.i  GET /services/categories (no auth)", False,
               f"status={r.status_code}, body={r.text[:200]}")

    # ════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print(f"SUMMARY: {len(PASS_RESULTS)} passed, {len(FAIL_RESULTS)} failed")
    print("=" * 70)
    if FAIL_RESULTS:
        print("\nFAILURES:")
        for f in FAIL_RESULTS:
            print(" ", f)
    return 0 if not FAIL_RESULTS else 1


if __name__ == "__main__":
    sys.exit(main())
