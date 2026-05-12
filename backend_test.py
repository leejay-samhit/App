"""
Regression test for GET /api/products/{id} public single-product endpoint
plus wishlist/save round-trip.
"""
import requests

BASE_URL = "https://network-pay-1.preview.emergentagent.com/api"

TEST_USER = {"email": "testuser@app.com", "password": "Test@123"}
ADMIN = {"email": "admin@app.com", "password": "Admin@123"}

results = []


def log(name, ok, detail=""):
    results.append((name, ok, detail))
    sym = "PASS" if ok else "FAIL"
    print(f"[{sym}] {name} :: {detail}")


def login(creds):
    r = requests.post(f"{BASE_URL}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"Login failed for {creds['email']}: {r.status_code} {r.text}"
    return r.json()["token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def main():
    # Setup logins
    try:
        admin_token = login(ADMIN)
        log("admin login", True, "200")
    except Exception as e:
        log("admin login", False, str(e))
        return

    user_token = None
    r = requests.post(f"{BASE_URL}/auth/login", json=TEST_USER, timeout=15)
    if r.status_code == 200:
        user_token = r.json()["token"]
        log("test user login", True, "200")
    else:
        reg = requests.post(
            f"{BASE_URL}/auth/register",
            json={"name": "Test Customer", "email": TEST_USER["email"],
                  "password": TEST_USER["password"]},
            timeout=15,
        )
        if reg.status_code == 200:
            user_token = reg.json()["token"]
            log("test user register", True, "200 (created)")
        else:
            log("test user login/register", False, f"{r.status_code} {r.text}")
            return

    # CASE 4: GET /products list regression
    r = requests.get(f"{BASE_URL}/products", timeout=15)
    if r.status_code != 200:
        log("CASE 4: GET /products (list)", False, f"{r.status_code} {r.text[:200]}")
        return
    products = r.json()
    # Accept array or {items:[...]}
    if isinstance(products, dict) and "items" in products:
        products = products["items"]
    if not isinstance(products, list) or not products:
        log("CASE 4: GET /products (list)", False, f"empty/invalid: {products}")
        return
    sample = products[0]
    required_list_keys = {"id", "name", "price", "image_url", "is_in_stock", "interested_count"}
    missing = required_list_keys - set(sample.keys())
    if missing:
        log("CASE 4: GET /products (list) shape", False, f"missing: {missing}")
    else:
        log("CASE 4: GET /products (list) shape", True,
            f"{len(products)} items, sample id={sample['id'][:8]}")
    if "interested_users" in sample:
        log("CASE 4: GET /products list privacy", False, "interested_users leaked")
    else:
        log("CASE 4: GET /products list privacy", True, "no interested_users")

    product_id = sample["id"]

    # CASE 1: GET /products/{valid id}
    r = requests.get(f"{BASE_URL}/products/{product_id}", timeout=15)
    if r.status_code != 200:
        log("CASE 1: GET /products/{valid id}", False, f"{r.status_code} {r.text[:300]}")
    else:
        p = r.json()
        expected_str = ["brand", "attrs_brand", "attrs_os", "attrs_ram",
                        "attrs_cpu_model", "attrs_cpu_speed", "attrs_storage"]
        expected_list = ["sub_features", "images", "spec_tabs", "whats_in_box"]
        expected_dict = ["extra_attrs"]
        expected_styled = ["price_summary", "protection_summary",
                           "warranty_summary", "delivery_summary"]
        expected_basic = ["id", "name", "price", "image_url"]
        expected_computed = ["is_in_stock", "interested_count"]

        problems = []
        for k in expected_basic:
            if k not in p:
                problems.append(f"missing basic:{k}")
        for k in expected_str:
            if k not in p:
                problems.append(f"missing str:{k}")
            elif not isinstance(p[k], str):
                problems.append(f"{k} not str:{type(p[k]).__name__}")
        for k in expected_list:
            if k not in p:
                problems.append(f"missing list:{k}")
            elif not isinstance(p[k], list):
                problems.append(f"{k} not list:{type(p[k]).__name__}")
        for k in expected_dict:
            if k not in p:
                problems.append(f"missing dict:{k}")
            elif not isinstance(p[k], dict):
                problems.append(f"{k} not dict:{type(p[k]).__name__}")
        for k in expected_styled:
            if k not in p:
                problems.append(f"missing styled:{k}")
            else:
                v = p[k]
                if not isinstance(v, dict):
                    problems.append(f"{k} not dict")
                else:
                    for sub in ("text", "bold", "font_size", "align"):
                        if sub not in v:
                            problems.append(f"{k}.{sub} missing")
        for k in expected_computed:
            if k not in p:
                problems.append(f"missing computed:{k}")
        if not isinstance(p.get("is_in_stock"), bool):
            problems.append(f"is_in_stock not bool:{type(p.get('is_in_stock')).__name__}")
        if not isinstance(p.get("interested_count"), int):
            problems.append(f"interested_count not int:{type(p.get('interested_count')).__name__}")
        if "interested_users" in p:
            problems.append("interested_users leaked")

        if not problems:
            log("CASE 1: GET /products/{valid id}", True,
                f"200, all 20+ fields present (brand={p.get('brand')!r}, "
                f"is_in_stock={p['is_in_stock']}, interested_count={p['interested_count']})")
        else:
            log("CASE 1: GET /products/{valid id}", False, "; ".join(problems[:10]))

    # CASE 2: unpublished product -> 404
    payload = {
        "name": "Regression Unpublished Test",
        "price": 99.0,
        "image_url": "data:image/png;base64,iVBOR=",
        "description": "draft only",
        "stock": 5,
        "is_published": False,
    }
    r = requests.post(f"{BASE_URL}/admin/products", json=payload,
                      headers=auth(admin_token), timeout=15)
    unpub_id = None
    if r.status_code != 200:
        log("CASE 2 setup: create unpublished product", False,
            f"{r.status_code} {r.text[:200]}")
    else:
        unpub_id = r.json().get("id")
        log("CASE 2 setup: create unpublished product", True, f"id={unpub_id}")

    if unpub_id:
        r = requests.get(f"{BASE_URL}/products/{unpub_id}", timeout=15)
        if r.status_code == 404:
            log("CASE 2: GET unpublished -> 404", True, "404 as expected")
        else:
            log("CASE 2: GET unpublished -> 404", False,
                f"expected 404, got {r.status_code}: {r.text[:200]}")
        rd = requests.delete(f"{BASE_URL}/admin/products/{unpub_id}",
                             headers=auth(admin_token), timeout=15)
        log("CASE 2 cleanup: delete unpublished",
            rd.status_code == 200, f"{rd.status_code}")

    # CASE 3: non-existent id -> 404
    bogus = "this-id-does-not-exist-12345"
    r = requests.get(f"{BASE_URL}/products/{bogus}", timeout=15)
    if r.status_code == 404:
        log("CASE 3: GET non-existent id -> 404", True, "404 as expected")
    else:
        log("CASE 3: GET non-existent id -> 404", False,
            f"expected 404, got {r.status_code}: {r.text[:200]}")

    # CASE 5: Wishlist round-trip
    # Pre-clean
    r0 = requests.get(f"{BASE_URL}/me/wishlist", headers=auth(user_token), timeout=15)
    if r0.status_code == 200:
        existing_pids = {x["id"] for x in r0.json().get("items", [])}
        if product_id in existing_pids:
            requests.post(f"{BASE_URL}/products/{product_id}/save",
                          headers=auth(user_token), timeout=15)

    r = requests.post(f"{BASE_URL}/products/{product_id}/save",
                      headers=auth(user_token), timeout=15)
    if r.status_code == 200 and r.json().get("saved") is True:
        log("CASE 5a: POST /save (1st) -> saved:true", True, str(r.json()))
    else:
        log("CASE 5a: POST /save (1st) -> saved:true", False,
            f"{r.status_code} {r.text[:200]}")

    r = requests.get(f"{BASE_URL}/me/wishlist", headers=auth(user_token), timeout=15)
    if r.status_code == 200:
        items = r.json().get("items", [])
        pids = [x["id"] for x in items]
        if product_id in pids:
            log("CASE 5b: GET /me/wishlist contains pid", True,
                f"{len(items)} items, found pid")
        else:
            log("CASE 5b: GET /me/wishlist contains pid", False,
                f"pid not in items")
    else:
        log("CASE 5b: GET /me/wishlist contains pid", False,
            f"{r.status_code} {r.text[:200]}")

    r = requests.post(f"{BASE_URL}/products/{product_id}/save",
                      headers=auth(user_token), timeout=15)
    if r.status_code == 200 and r.json().get("saved") is False:
        log("CASE 5c: POST /save (toggle) -> saved:false", True, str(r.json()))
    else:
        log("CASE 5c: POST /save (toggle) -> saved:false", False,
            f"{r.status_code} {r.text[:200]}")

    # Summary
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"RESULT: {passed}/{total} PASSED")
    print("=" * 60)
    if passed < total:
        print("\nFAILED:")
        for name, ok, det in results:
            if not ok:
                print(f"  FAIL: {name} :: {det}")


if __name__ == "__main__":
    main()
