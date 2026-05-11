"""
Backend round-trip test for the new Amazon/Flipkart-style Rich Product fields.

Tests:
  1. POST /api/admin/products  — create with FULL extended payload
  2. GET  /api/admin/products  — verify fields persist in admin list
  3. PATCH /api/admin/products/{id} — partial update preserves untouched fields
  4. GET  /api/products (public) — published product appears with rich fields
  5. DELETE /api/admin/products/{id} — clean up
"""
import os
import sys
import json
import requests

BASE = os.environ.get("BACKEND_URL", "https://network-pay-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"


def jprint(label, data):
    print(f"\n----- {label} -----")
    try:
        print(json.dumps(data, indent=2, default=str)[:2000])
    except Exception:
        print(str(data)[:2000])


passed = 0
failed = 0
issues = []


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        issues.append(msg)
        print(f"  FAIL: {msg}")


# ------ 1. Login as admin ------
print("=" * 60)
print("STEP 0: Admin login")
print("=" * 60)
r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
print(f"  POST /auth/login -> {r.status_code}")
if r.status_code != 200:
    print(r.text)
    sys.exit(1)
token = r.json().get("token") or r.json().get("access_token")
HDR = {"Authorization": f"Bearer {token}"}
check(bool(token), "Admin login returned token")

# ------ The full payload ------
FULL_PAYLOAD = {
    "name": "Test Phone Pro X",
    "price": 49999.0,
    "image_url": "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
    "description": "Flagship test phone",
    "stock": 25,
    "category": "Electronics",
    "is_published": True,
    "brand": "TestBrand",
    "sub_features": ["Super AMOLED 6.7\"", "5000 mAh battery", "48MP camera"],
    "images": ["data:image/jpeg;base64,A==", "data:image/jpeg;base64,B=="],
    "price_summary":      {"text": "Rs 49,999 inclusive of all taxes", "bold": True,  "font_size": 18,   "align": "left"},
    "protection_summary": {"text": "1-year warranty + extended 2yr",   "bold": False, "font_size": None, "align": "left"},
    "warranty_summary":   {"text": "Free replacement within 7 days",   "bold": False, "font_size": 14,   "align": "center"},
    "delivery_summary":   {"text": "Free delivery in 2-4 days",        "bold": True,  "font_size": None, "align": "right"},
    "attrs_brand": "TestBrand",
    "attrs_os": "Android 14",
    "attrs_ram": "8 GB",
    "attrs_cpu_model": "Snapdragon 8 Gen 3",
    "attrs_cpu_speed": "3.3 GHz",
    "attrs_storage": "256 GB",
    "extra_attrs": {"Screen": "6.7\" AMOLED", "Weight": "190g"},
    "spec_tabs": [
        {"name": "General", "rows": [{"label": "Model", "value": "PX-100"}, {"label": "Color", "value": "Onyx"}]},
        {"name": "Battery", "rows": [{"label": "Capacity", "value": "5000 mAh"}]},
    ],
    "whats_in_box": [
        {"name": "Phone", "image_data_url": "data:image/jpeg;base64,X=="},
        {"name": "Charger", "image_data_url": ""},
    ],
}

# ------ 2. POST /api/admin/products ------
print("\n" + "=" * 60)
print("STEP 1: POST /api/admin/products  (full payload)")
print("=" * 60)
r = requests.post(f"{API}/admin/products", json=FULL_PAYLOAD, headers=HDR, timeout=30)
print(f"  -> HTTP {r.status_code}")
check(r.status_code in (200, 201), f"create returns 200/201 (got {r.status_code})")
if r.status_code not in (200, 201):
    print(r.text)
    sys.exit(1)
created = r.json()
jprint("create response", created)
product_id = created.get("id")
check(bool(product_id), "Created product has id")


def cmp(a, b):
    return a == b


field_specs = [
    ("name", "Test Phone Pro X"),
    ("price", 49999.0),
    ("image_url", FULL_PAYLOAD["image_url"]),
    ("description", "Flagship test phone"),
    ("stock", 25),
    ("category", "Electronics"),
    ("is_published", True),
    ("brand", "TestBrand"),
    ("sub_features", FULL_PAYLOAD["sub_features"]),
    ("images", FULL_PAYLOAD["images"]),
    ("price_summary", FULL_PAYLOAD["price_summary"]),
    ("protection_summary", FULL_PAYLOAD["protection_summary"]),
    ("warranty_summary", FULL_PAYLOAD["warranty_summary"]),
    ("delivery_summary", FULL_PAYLOAD["delivery_summary"]),
    ("attrs_brand", "TestBrand"),
    ("attrs_os", "Android 14"),
    ("attrs_ram", "8 GB"),
    ("attrs_cpu_model", "Snapdragon 8 Gen 3"),
    ("attrs_cpu_speed", "3.3 GHz"),
    ("attrs_storage", "256 GB"),
    ("extra_attrs", FULL_PAYLOAD["extra_attrs"]),
    ("spec_tabs", FULL_PAYLOAD["spec_tabs"]),
    ("whats_in_box", FULL_PAYLOAD["whats_in_box"]),
]
for field, expected in field_specs:
    actual = created.get(field)
    if not cmp(actual, expected):
        print(f"  DIFF on '{field}':\n    expected: {expected!r}\n    actual:   {actual!r}")
    check(cmp(actual, expected), f"create echoes '{field}' intact")

# ------ 3. GET /api/admin/products ------
print("\n" + "=" * 60)
print("STEP 2: GET /api/admin/products (admin list)")
print("=" * 60)
r = requests.get(f"{API}/admin/products", headers=HDR, timeout=30)
print(f"  -> HTTP {r.status_code}")
check(r.status_code == 200, "admin list returns 200")
items = r.json()
found = next((p for p in items if p.get("id") == product_id), None)
check(found is not None, "Created product appears in admin list")
if found:
    for field, expected in field_specs:
        actual = found.get(field)
        if not cmp(actual, expected):
            print(f"  DIFF on '{field}' in admin list:\n    expected: {expected!r}\n    actual:   {actual!r}")
        check(cmp(actual, expected), f"admin-list preserves '{field}'")

# ------ 4. PATCH partial update ------
print("\n" + "=" * 60)
print("STEP 3: PATCH /api/admin/products/{id} (partial update)")
print("=" * 60)
PATCH_PAYLOAD = {
    "brand": "TestBrand-V2",
    "sub_features": ["Updated feature 1", "Updated feature 2"],
    "images": [
        "data:image/jpeg;base64,UPD1==",
        "data:image/jpeg;base64,UPD2==",
        "data:image/jpeg;base64,UPD3==",
    ],
    "price_summary": {"text": "Now Rs 39,999 -- limited time", "bold": False, "font_size": 22, "align": "center"},
    "extra_attrs": {"Material": "Aluminum"},
    "spec_tabs": [
        {"name": "Updated", "rows": [{"label": "RefreshRate", "value": "120 Hz"}]},
    ],
    "whats_in_box": [
        {"name": "Phone only", "image_data_url": "data:image/jpeg;base64,UPDONLY=="},
    ],
}
r = requests.patch(f"{API}/admin/products/{product_id}", json=PATCH_PAYLOAD, headers=HDR, timeout=30)
print(f"  -> HTTP {r.status_code}")
check(r.status_code == 200, f"PATCH returns 200 (got {r.status_code})")
if r.status_code != 200:
    print(r.text)
patched = r.json() if r.status_code == 200 else {}
jprint("patch response", patched)

for field, expected in PATCH_PAYLOAD.items():
    actual = patched.get(field)
    if not cmp(actual, expected):
        print(f"  DIFF on patched '{field}':\n    expected: {expected!r}\n    actual:   {actual!r}")
    check(cmp(actual, expected), f"PATCH updates '{field}' correctly")

preserved = [
    ("name", "Test Phone Pro X"),
    ("price", 49999.0),
    ("category", "Electronics"),
    ("description", "Flagship test phone"),
    ("stock", 25),
    ("is_published", True),
    ("protection_summary", FULL_PAYLOAD["protection_summary"]),
    ("warranty_summary", FULL_PAYLOAD["warranty_summary"]),
    ("delivery_summary", FULL_PAYLOAD["delivery_summary"]),
    ("attrs_brand", "TestBrand"),
    ("attrs_os", "Android 14"),
    ("attrs_ram", "8 GB"),
    ("attrs_cpu_model", "Snapdragon 8 Gen 3"),
    ("attrs_cpu_speed", "3.3 GHz"),
    ("attrs_storage", "256 GB"),
]
for field, expected in preserved:
    actual = patched.get(field)
    if not cmp(actual, expected):
        print(f"  DIFF on PRESERVED '{field}':\n    expected: {expected!r}\n    actual:   {actual!r}")
    check(cmp(actual, expected), f"PATCH preserves untouched '{field}'")

# ------ 5. GET /api/products (public) ------
print("\n" + "=" * 60)
print("STEP 4: GET /api/products  (public)")
print("=" * 60)
r = requests.get(f"{API}/products", timeout=30)
print(f"  -> HTTP {r.status_code}")
check(r.status_code == 200, "public list returns 200")
pub_items = r.json()
pub_found = next((p for p in pub_items if p.get("id") == product_id), None)
check(pub_found is not None, "Published product appears in public list")
if pub_found:
    rich_fields_pub = ["brand", "sub_features", "images", "price_summary",
                       "protection_summary", "warranty_summary", "delivery_summary",
                       "attrs_brand", "attrs_os", "attrs_ram", "attrs_cpu_model",
                       "attrs_cpu_speed", "attrs_storage", "extra_attrs",
                       "spec_tabs", "whats_in_box"]
    for f in rich_fields_pub:
        present = f in pub_found
        check(present, f"public list exposes rich field '{f}'")
    check(pub_found.get("brand") == "TestBrand-V2", "public list reflects patched brand")
    check(pub_found.get("sub_features") == PATCH_PAYLOAD["sub_features"], "public list reflects patched sub_features")
    check(pub_found.get("price_summary") == PATCH_PAYLOAD["price_summary"], "public list reflects patched price_summary")
    check(pub_found.get("extra_attrs") == {"Material": "Aluminum"}, "public list reflects patched extra_attrs")
    check(pub_found.get("spec_tabs") == PATCH_PAYLOAD["spec_tabs"], "public list reflects patched spec_tabs")
    check(pub_found.get("whats_in_box") == PATCH_PAYLOAD["whats_in_box"], "public list reflects patched whats_in_box")
    check("is_in_stock" in pub_found, "public list adds computed 'is_in_stock'")
    check("interested_count" in pub_found, "public list adds computed 'interested_count'")
    check("interested_users" not in pub_found, "public list does NOT leak 'interested_users'")

# ------ 6. DELETE cleanup ------
print("\n" + "=" * 60)
print("STEP 5: DELETE /api/admin/products/{id}  (cleanup)")
print("=" * 60)
r = requests.delete(f"{API}/admin/products/{product_id}", headers=HDR, timeout=30)
print(f"  -> HTTP {r.status_code}")
check(r.status_code == 200, f"DELETE returns 200 (got {r.status_code})")
try:
    jprint("delete response", r.json())
except Exception:
    pass

r = requests.get(f"{API}/admin/products", headers=HDR, timeout=30)
items_after = r.json()
gone = all(p.get("id") != product_id for p in items_after)
check(gone, "Product is removed after DELETE")

# ------ Summary ------
print("\n" + "=" * 60)
print(f"RESULT: {passed} passed, {failed} failed")
print("=" * 60)
if failed:
    print("\nFailures:")
    for i, msg in enumerate(issues, 1):
        print(f"  {i}. {msg}")
    sys.exit(1)
print("All checks passed.")
sys.exit(0)
