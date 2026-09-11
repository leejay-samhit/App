"""
Smoke test for the small additions to backend:
1. Category image/description fields (admin CRUD)
2. /services list subcategory filter
3. /admin/service-analytics pincode filter
4. Regression smoke (/branding, /payment/config, /admin/ai/text)
"""
import requests
import sys

BASE = "https://slangcart-tracking.preview.emergentagent.com/api"
ADMIN = ("admin@app.com", "Admin@123")
USER = ("testuser@app.com", "Test@123")

PASS, FAIL = [], []


def _login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    j = r.json()
    return j.get("access_token") or j.get("token")


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def record(label, ok, detail=""):
    if ok:
        PASS.append(label)
        print(f"  PASS  {label}  {detail}")
    else:
        FAIL.append((label, detail))
        print(f"  FAIL  {label}  {detail}")


def section(name):
    print(f"\n=== {name} ===")


def main():
    section("LOGIN")
    admin_tok = _login(*ADMIN)
    user_tok = _login(*USER)
    record("Admin login", bool(admin_tok))
    record("User login", bool(user_tok))

    # ---------- 1. Category image/description ----------
    section("1. Category image/description (admin)")
    payload = {
        "name": "QA_TEST_CAT_IMG",
        "icon": "tool",
        "color": "#10B981",
        "image_b64": "https://images.unsplash.com/photo-1607472586893-edb57bdc0e39?w=256",
        "banner_b64": "https://example.com/banner.png",
        "description": "Auto-test category",
    }
    r = requests.post(f"{BASE}/admin/service-categories", json=payload, headers=_h(admin_tok), timeout=30)
    print(f"  POST /admin/service-categories -> {r.status_code}")
    cat_id = None
    if r.status_code == 200:
        body = r.json()
        cat = body.get("category", {})
        cat_id = cat.get("id")
        record("POST returns 200", True, f"id={cat_id}")
        record("response.image_b64 echoed",
               cat.get("image_b64") == payload["image_b64"],
               f"got={cat.get('image_b64')!r}")
        record("response.banner_b64 echoed",
               cat.get("banner_b64") == payload["banner_b64"],
               f"got={cat.get('banner_b64')!r}")
        record("response.description echoed",
               cat.get("description") == payload["description"],
               f"got={cat.get('description')!r}")
    else:
        record("POST returns 200", False, f"status={r.status_code} body={r.text[:300]}")

    # GET /admin/service-categories
    r = requests.get(f"{BASE}/admin/service-categories", headers=_h(admin_tok), timeout=30)
    print(f"  GET /admin/service-categories -> {r.status_code}")
    if r.status_code == 200 and cat_id:
        cats = r.json().get("categories", [])
        row = next((c for c in cats if c.get("id") == cat_id), None)
        record("admin GET contains our category", row is not None)
        if row:
            record("admin row.image_b64 present",
                   row.get("image_b64") == payload["image_b64"],
                   f"got={row.get('image_b64')!r}")
            record("admin row.banner_b64 present",
                   row.get("banner_b64") == payload["banner_b64"],
                   f"got={row.get('banner_b64')!r}")
            record("admin row.description present",
                   row.get("description") == payload["description"],
                   f"got={row.get('description')!r}")
    else:
        record("admin GET returns 200", False, f"status={r.status_code}")

    # Public GET /services/categories
    r = requests.get(f"{BASE}/services/categories", timeout=30)
    print(f"  GET /services/categories (public) -> {r.status_code}")
    if r.status_code == 200 and cat_id:
        cats = r.json().get("categories", [])
        row = next((c for c in cats if c.get("id") == cat_id), None)
        record("public GET contains our category", row is not None)
        if row:
            record("public row.image_b64 present",
                   row.get("image_b64") == payload["image_b64"],
                   f"got={row.get('image_b64')!r}")
            record("public row.banner_b64 present",
                   row.get("banner_b64") == payload["banner_b64"],
                   f"got={row.get('banner_b64')!r}")
            record("public row.description present",
                   row.get("description") == payload["description"],
                   f"got={row.get('description')!r}")
    else:
        record("public GET returns 200", False, f"status={r.status_code}")

    # DELETE cleanup
    if cat_id:
        r = requests.delete(f"{BASE}/admin/service-categories/{cat_id}", headers=_h(admin_tok), timeout=30)
        record("DELETE cleanup returns 200", r.status_code == 200, f"status={r.status_code}")

    # ---------- 2. Services list subcategory filter ----------
    section("2. /services subcategory_id and availability filter (public)")
    r = requests.get(f"{BASE}/services?subcategory_id=NONEXISTENT", timeout=30)
    print(f"  GET /services?subcategory_id=NONEXISTENT -> {r.status_code}")
    if r.status_code == 200:
        body = r.json()
        items = body.get("items", body if isinstance(body, list) else [])
        record("subcategory_id=NONEXISTENT returns 200", True)
        record("subcategory_id=NONEXISTENT items==[]", len(items) == 0, f"len={len(items)}")
    else:
        record("subcategory_id=NONEXISTENT returns 200", False, f"status={r.status_code} body={r.text[:200]}")

    r = requests.get(f"{BASE}/services?availability=available", timeout=30)
    print(f"  GET /services?availability=available -> {r.status_code}")
    if r.status_code == 200:
        body = r.json()
        items = body.get("items", [])
        record("availability=available returns 200", True, f"items={len(items)}")
        # Inspect up to 3
        sample = items[:3]
        all_avail = all(it.get("availability_status") == "available" for it in sample)
        if sample:
            record("availability=available items have status==available", all_avail,
                   f"statuses={[i.get('availability_status') for i in sample]}")
        else:
            record("availability=available items have status==available", True, "no items to inspect (vacuously true)")
    else:
        record("availability=available returns 200", False, f"status={r.status_code} body={r.text[:200]}")

    r = requests.get(f"{BASE}/services?availability=invalid", timeout=30)
    print(f"  GET /services?availability=invalid -> {r.status_code}")
    # Should not crash (not 500); 200 or 400 acceptable
    record("availability=invalid did not 5xx", r.status_code < 500, f"status={r.status_code}")

    # ---------- 3. Service-analytics pincode filter ----------
    section("3. /admin/service-analytics pincode filter")
    r = requests.get(f"{BASE}/admin/service-analytics", headers=_h(admin_tok), timeout=30)
    print(f"  GET /admin/service-analytics -> {r.status_code}")
    baseline = None
    if r.status_code == 200:
        baseline = r.json()
        record("baseline analytics returns 200", True,
               f"keys={list(baseline.keys())[:6]}")
    else:
        record("baseline analytics returns 200", False, f"status={r.status_code} body={r.text[:200]}")

    r = requests.get(f"{BASE}/admin/service-analytics?pincode=500001", headers=_h(admin_tok), timeout=30)
    print(f"  GET /admin/service-analytics?pincode=500001 -> {r.status_code}")
    if r.status_code == 200:
        body = r.json()
        record("?pincode=500001 returns 200", True)
        if baseline:
            # Same shape
            same_keys = set(body.keys()) == set(baseline.keys())
            record("?pincode=500001 same shape as baseline", same_keys,
                   f"missing={set(baseline.keys())-set(body.keys())}")
    else:
        record("?pincode=500001 returns 200", False, f"status={r.status_code} body={r.text[:200]}")

    r = requests.get(f"{BASE}/admin/service-analytics?pincode=NONEXISTENT_ZIP", headers=_h(admin_tok), timeout=30)
    print(f"  GET /admin/service-analytics?pincode=NONEXISTENT_ZIP -> {r.status_code}")
    if r.status_code == 200:
        body = r.json()
        record("?pincode=NONEXISTENT_ZIP returns 200", True)
        # All zero counts in availability
        avail = body.get("availability") or {}
        all_zero = sum(int(v or 0) for v in avail.values() if isinstance(v, (int, float))) == 0
        record("?pincode=NONEXISTENT_ZIP availability all zero",
               all_zero, f"availability={avail}")
        # Top categories all zero
        cats = body.get("categories") or body.get("top_categories") or []
        provider_sum = sum(int(c.get("provider_count") or 0) for c in cats)
        record("?pincode=NONEXISTENT_ZIP category provider_counts all zero",
               provider_sum == 0, f"sum={provider_sum}")
    else:
        record("?pincode=NONEXISTENT_ZIP returns 200", False, f"status={r.status_code} body={r.text[:200]}")

    # ---------- 4. Regression smoke ----------
    section("4. Regression smoke")
    r = requests.get(f"{BASE}/branding", timeout=30)
    print(f"  GET /branding -> {r.status_code}")
    if r.status_code == 200:
        body = r.json()
        record("/branding 200", True)
        record("/branding has gradient", "gradient" in body, f"gradient={body.get('gradient')!r}"[:120])
        record("/branding has button_style", "button_style" in body, f"={body.get('button_style')!r}")
        record("/branding has home_banner_b64", "home_banner_b64" in body, f"={str(body.get('home_banner_b64'))[:40]}")
    else:
        record("/branding 200", False, f"status={r.status_code}")

    r = requests.get(f"{BASE}/payment/config", headers=_h(user_tok), timeout=30)
    print(f"  GET /payment/config (testuser) -> {r.status_code}")
    if r.status_code == 200:
        body = r.json()
        amt = body.get("amount")
        record("/payment/config 200", True, f"amount={amt}")
        record("/payment/config amount >= 118", amt is not None and amt >= 118,
               f"amount={amt}")
    else:
        record("/payment/config 200", False, f"status={r.status_code} body={r.text[:200]}")

    # AI text
    r = requests.post(f"{BASE}/admin/ai/text", headers=_h(admin_tok), json={
        "kind": "category_description",
        "prompt": "AC repair home services",
        "tone": "friendly",
        "max_words": 40,
    }, timeout=60)
    print(f"  POST /admin/ai/text -> {r.status_code}")
    if r.status_code == 200:
        text = r.json().get("text") or ""
        record("/admin/ai/text 200", True, f"text_len={len(text)}")
        record("/admin/ai/text non-empty", len(text) > 0, f"snippet={text[:80]!r}")
    else:
        record("/admin/ai/text 200", False, f"status={r.status_code} body={r.text[:300]}")

    print(f"\n=== TOTAL: {len(PASS)} pass / {len(FAIL)} fail ===")
    if FAIL:
        print("\nFAILURES:")
        for label, det in FAIL:
            print(f"  - {label}: {det}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
