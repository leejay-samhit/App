"""
Backend test for:
  A) GET /api/shop-categories (public)
  B) Admin shop-categories CRUD + reflection in public
  C) Shop layout product_grid new fields (products_per_row, show_view_all, view_all_link)
  D) Backward compatibility on GET /api/shop-layout?scope=home
"""
import os
import sys
import json
import requests

# Read backend URL from frontend .env
BACKEND_URL = None
with open("/app/frontend/.env") as f:
    for line in f:
        line = line.strip()
        if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
            BACKEND_URL = line.split("=", 1)[1].strip().strip('"')
            break

assert BACKEND_URL, "Missing EXPO_PUBLIC_BACKEND_URL in /app/frontend/.env"
API = BACKEND_URL.rstrip("/") + "/api"
print(f"[INFO] API base: {API}")

results = []  # (name, ok, detail)

def record(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name} -- {detail}")
    results.append((name, ok, detail))

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

# Login
def login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    return r

r = login(ADMIN_EMAIL, ADMIN_PASSWORD)
if r.status_code != 200:
    print(f"[FATAL] Admin login failed: {r.status_code} {r.text[:300]}")
    sys.exit(1)
admin_token = r.json().get("token") or r.json().get("access_token")
assert admin_token, f"Login response missing token: {r.json()}"
admin_h = {"Authorization": f"Bearer {admin_token}"}
print(f"[INFO] Admin login OK, token len={len(admin_token)}")

# ============================================================
# A) Public shop-categories
# ============================================================
print("\n=== A) GET /api/shop-categories (public) ===")
r = requests.get(f"{API}/shop-categories", timeout=30)
ok = r.status_code == 200
body = {}
try:
    body = r.json()
except Exception:
    pass
record("A1 public /shop-categories returns 200", ok, f"status={r.status_code}")
if ok:
    items = body.get("items")
    record("A2 response has items list", isinstance(items, list) and len(items) > 0, f"items count={len(items) if isinstance(items, list) else 'N/A'}")

    expected_keys = {"icon_pack", "icon_name", "image_url", "color", "sort_order", "active"}
    if isinstance(items, list) and items:
        sample = items[0]
        present = expected_keys.issubset(set(sample.keys()))
        record("A3 each category has icon_pack/icon_name/image_url/color/sort_order/active", present,
               f"sample keys={sorted(sample.keys())}")

        # All active
        all_active = all(bool(c.get("active")) for c in items)
        record("A4 all returned categories have active=true", all_active,
               f"non-active count={sum(1 for c in items if not c.get('active'))}")
    else:
        record("A3 keys check skipped (no items)", False)
        record("A4 active=true check skipped", False)

# ============================================================
# B) Admin CRUD + reflection
# ============================================================
print("\n=== B) Admin shop-categories CRUD ===")
r = requests.get(f"{API}/admin/shop-categories", headers=admin_h, timeout=30)
ok = r.status_code == 200
record("B1 GET /api/admin/shop-categories returns 200", ok, f"status={r.status_code}")
admin_items = []
if ok:
    body = r.json()
    admin_items = body.get("items", [])
    record("B2 admin list returns items (incl active+inactive)", len(admin_items) > 0,
           f"admin items count={len(admin_items)}")

# Find an active category we can mutate (don't touch original; we'll restore at end)
target = None
if admin_items:
    # prefer first active
    for c in admin_items:
        if c.get("active"):
            target = c
            break
    if not target:
        target = admin_items[0]

original_icon_name = None
original_color = None
if target:
    cat_id = target["id"]
    original_icon_name = target.get("icon_name")
    original_color = target.get("color")
    print(f"[INFO] Target category: id={cat_id} name={target.get('name')!r} "
          f"original icon_name={original_icon_name!r} color={original_color!r}")

    new_icon = "tshirt-crew"
    new_color = "#DCFCE7"
    r = requests.put(
        f"{API}/admin/shop-categories/{cat_id}",
        headers=admin_h,
        json={"icon_name": new_icon, "color": new_color},
        timeout=30,
    )
    ok = r.status_code == 200
    body = {}
    try:
        body = r.json()
    except Exception:
        pass
    record("B3 PUT update icon_name + color", ok,
           f"status={r.status_code} icon_name={body.get('icon_name')!r} color={body.get('color')!r}")

    # Re-fetch public and confirm reflection
    r = requests.get(f"{API}/shop-categories", timeout=30)
    body = r.json() if r.status_code == 200 else {}
    found = next((c for c in body.get("items", []) if c.get("id") == cat_id), None)
    if found is None:
        # If the target was inactive, it won't appear publicly. Check admin instead.
        record("B4 Public /shop-categories reflects update", False,
               f"target id not present in public list (active={target.get('active')})")
    else:
        ok_icon = found.get("icon_name") == new_icon
        ok_color = found.get("color") == new_color
        record("B4 Public /shop-categories reflects icon_name update", ok_icon,
               f"public icon_name={found.get('icon_name')!r}")
        record("B5 Public /shop-categories reflects color update", ok_color,
               f"public color={found.get('color')!r}")

    # Restore original
    restore_payload = {}
    if original_icon_name is not None:
        restore_payload["icon_name"] = original_icon_name
    if original_color is not None:
        restore_payload["color"] = original_color
    if restore_payload:
        rr = requests.put(
            f"{API}/admin/shop-categories/{cat_id}",
            headers=admin_h,
            json=restore_payload,
            timeout=30,
        )
        print(f"[INFO] Restored target category status={rr.status_code}")
else:
    record("B3 PUT update icon_name + color", False, "No target category available")

# ============================================================
# C) Shop layout product_grid new fields
# ============================================================
print("\n=== C) Shop layout product_grid new fields ===")

create_payload = {
    "block_type": "product_grid",
    "scope": "home",
    "products_per_row": 3,
    "show_view_all": True,
    "view_all_link": "Electronics",
    "product_count": 6,
    "data_source": "trending",
    "title": "TEST product grid block (delete me)",
    "sort_order": 999,
    "active": True,
}

r = requests.post(f"{API}/admin/shop-layout", headers=admin_h, json=create_payload, timeout=30)
ok = r.status_code == 200
body = r.json() if ok else {}
block_id = body.get("id")
record("C1 POST /api/admin/shop-layout product_grid create", ok and bool(block_id),
       f"status={r.status_code} id={block_id} "
       f"ppr={body.get('products_per_row')} sva={body.get('show_view_all')} val={body.get('view_all_link')!r}")

if block_id:
    record("C1a create response products_per_row=3", body.get("products_per_row") == 3,
           f"got={body.get('products_per_row')}")
    record("C1b create response show_view_all=True", body.get("show_view_all") is True,
           f"got={body.get('show_view_all')}")
    record("C1c create response view_all_link=Electronics", body.get("view_all_link") == "Electronics",
           f"got={body.get('view_all_link')!r}")

    # GET admin list and find it
    r = requests.get(f"{API}/admin/shop-layout?scope=home", headers=admin_h, timeout=30)
    blocks = r.json().get("items", []) if r.status_code == 200 else []
    found = next((b for b in blocks if b.get("id") == block_id), None)
    if found:
        record("C2 Admin GET sees block with products_per_row=3", found.get("products_per_row") == 3,
               f"got={found.get('products_per_row')}")
        record("C2a show_view_all=True saved", found.get("show_view_all") is True,
               f"got={found.get('show_view_all')}")
        record("C2b view_all_link='Electronics' saved", found.get("view_all_link") == "Electronics",
               f"got={found.get('view_all_link')!r}")
    else:
        record("C2 Admin GET sees new block", False, "block id not present in admin list")

    # PATCH: products_per_row=4, show_view_all=False
    r = requests.patch(
        f"{API}/admin/shop-layout/{block_id}",
        headers=admin_h,
        json={"products_per_row": 4, "show_view_all": False},
        timeout=30,
    )
    ok = r.status_code == 200
    pbody = r.json() if ok else {}
    record("C3 PATCH products_per_row=4 + show_view_all=False", ok,
           f"status={r.status_code} ppr={pbody.get('products_per_row')} sva={pbody.get('show_view_all')}")
    if ok:
        record("C3a PATCH response products_per_row=4", pbody.get("products_per_row") == 4,
               f"got={pbody.get('products_per_row')}")
        record("C3b PATCH response show_view_all=False", pbody.get("show_view_all") is False,
               f"got={pbody.get('show_view_all')}")
        # view_all_link should remain "Electronics"
        record("C3c PATCH preserved view_all_link='Electronics'", pbody.get("view_all_link") == "Electronics",
               f"got={pbody.get('view_all_link')!r}")

    # Public GET /api/shop-layout?scope=home
    r = requests.get(f"{API}/shop-layout?scope=home", timeout=30)
    pub_ok = r.status_code == 200
    pub_items = r.json().get("items", []) if pub_ok else []
    found_pub = next((b for b in pub_items if b.get("id") == block_id), None)
    record("C4 Public GET /api/shop-layout?scope=home returns 200", pub_ok, f"status={r.status_code}")
    if found_pub:
        record("C4a Public block has products_per_row=4", found_pub.get("products_per_row") == 4,
               f"got={found_pub.get('products_per_row')}")
        record("C4b Public block has show_view_all=False", found_pub.get("show_view_all") is False,
               f"got={found_pub.get('show_view_all')}")
        record("C4c Public block has view_all_link='Electronics'", found_pub.get("view_all_link") == "Electronics",
               f"got={found_pub.get('view_all_link')!r}")
    else:
        record("C4a public visibility of test block", False, "block not in public list (may be filtered)")

    # DELETE cleanup
    r = requests.delete(f"{API}/admin/shop-layout/{block_id}", headers=admin_h, timeout=30)
    record("C5 DELETE test block (cleanup)", r.status_code == 200, f"status={r.status_code}")

# ============================================================
# D) Backward compatibility
# ============================================================
print("\n=== D) Backward compatibility on GET /api/shop-layout?scope=home ===")
r = requests.get(f"{API}/shop-layout?scope=home", timeout=30)
ok = r.status_code == 200
record("D1 Public /shop-layout?scope=home returns 200", ok, f"status={r.status_code}")
if ok:
    items = r.json().get("items", [])
    record("D2 returns items list", isinstance(items, list), f"count={len(items)}")
    # Check that every block has the new fields backfilled (no crash)
    all_have_fields = all(
        ("products_per_row" in b) and ("show_view_all" in b) and ("view_all_link" in b)
        for b in items
    )
    record("D3 every block has new fields backfilled (products_per_row/show_view_all/view_all_link)",
           all_have_fields,
           f"blocks_missing={sum(1 for b in items if 'products_per_row' not in b)}")

# Summary
print("\n=== SUMMARY ===")
passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)
total = passed + failed
print(f"Passed: {passed}/{total}; Failed: {failed}")
if failed:
    print("\nFailed cases:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}: {detail}")
sys.exit(0 if failed == 0 else 1)
