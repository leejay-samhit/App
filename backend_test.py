"""
Backend regression check (2026-05-28) — refactor verification for:
  • routes/admin_ai.py
  • routes/service_subcategories.py
"""
import sys
import time
import requests

BASE = "https://vendor-network-app-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"


def _print(label, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {label}" + (f"  — {detail}" if detail else ""))


def login_admin():
    r = requests.post(f"{BASE}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=20)
    r.raise_for_status()
    return r.json()["token"]


def main():
    results = []
    admin_token = login_admin()
    H = {"Authorization": f"Bearer {admin_token}"}

    # 1) POST /admin/ai/text
    try:
        r = requests.post(
            f"{BASE}/admin/ai/text",
            json={"kind": "category_description", "prompt": "plumber", "tone": "professional"},
            headers=H, timeout=45,
        )
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        ok = r.status_code == 200 and body.get("ok") is True and isinstance(body.get("text"), str) and len(body["text"]) > 10
        results.append(("POST /admin/ai/text", ok))
        _print("1) POST /admin/ai/text", ok, f"status={r.status_code} text_len={len(body.get('text','') or '')}")
    except Exception as e:
        results.append(("POST /admin/ai/text", False))
        _print("1) POST /admin/ai/text", False, f"exception={e}")

    # 2) POST /admin/ai/image (allow 60s)
    try:
        r = requests.post(
            f"{BASE}/admin/ai/image",
            json={"prompt": "plumber wrench icon", "style": "flat-icon"},
            headers=H, timeout=90,
        )
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        ok = (
            r.status_code == 200
            and body.get("ok") is True
            and isinstance(body.get("image_b64"), str)
            and len(body["image_b64"]) > 100
            and isinstance(body.get("mime_type"), str)
            and body["mime_type"].startswith("image/")
        )
        results.append(("POST /admin/ai/image", ok))
        _print("2) POST /admin/ai/image", ok,
               f"status={r.status_code} mime={body.get('mime_type')} b64_len={len(body.get('image_b64') or '')}")
    except Exception as e:
        results.append(("POST /admin/ai/image", False))
        _print("2) POST /admin/ai/image", False, f"exception={e}")

    # 3) GET /service-subcategories (no auth)
    try:
        r = requests.get(f"{BASE}/service-subcategories", timeout=15)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        ok = r.status_code == 200 and isinstance(body.get("items"), list) and "total" in body
        results.append(("GET /service-subcategories (public)", ok))
        _print("3) GET /service-subcategories (public)", ok,
               f"status={r.status_code} total={body.get('total')} items_len={len(body.get('items') or [])}")
    except Exception as e:
        results.append(("GET /service-subcategories (public)", False))
        _print("3) GET /service-subcategories (public)", False, f"exception={e}")

    # 4) GET /admin/service-subcategories
    try:
        r = requests.get(f"{BASE}/admin/service-subcategories", headers=H, timeout=15)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        ok = r.status_code == 200 and isinstance(body.get("items"), list) and "total" in body
        results.append(("GET /admin/service-subcategories", ok))
        _print("4) GET /admin/service-subcategories", ok,
               f"status={r.status_code} total={body.get('total')} items_len={len(body.get('items') or [])}")
    except Exception as e:
        results.append(("GET /admin/service-subcategories", False))
        _print("4) GET /admin/service-subcategories", False, f"exception={e}")

    # Look up a parent category id
    parent_id = None
    try:
        r = requests.get(f"{BASE}/admin/service-categories", headers=H, timeout=15)
        if r.status_code == 200:
            data = r.json()
            cats = data if isinstance(data, list) else (data.get("items") or data.get("categories") or [])
            if cats:
                parent_id = cats[0].get("id")
            _print("    parent lookup", parent_id is not None, f"parent_id={parent_id}")
        else:
            _print("    parent lookup", False, f"status={r.status_code} body={r.text[:120]}")
    except Exception as e:
        _print("    parent lookup", False, f"exception={e}")

    created_id = None

    # 5) POST /admin/service-subcategories
    if parent_id:
        try:
            r = requests.post(
                f"{BASE}/admin/service-subcategories",
                json={"parent_id": parent_id, "name": f"TestSub-Refactor-{int(time.time())}", "icon": "droplet"},
                headers=H, timeout=20,
            )
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            sub = body.get("subcategory") or {}
            ok = r.status_code == 200 and body.get("ok") is True and isinstance(sub.get("id"), str) and sub.get("parent_id") == parent_id
            created_id = sub.get("id")
            results.append(("POST /admin/service-subcategories", ok))
            _print("5) POST /admin/service-subcategories", ok,
                   f"status={r.status_code} created_id={created_id} name={sub.get('name')}")
        except Exception as e:
            results.append(("POST /admin/service-subcategories", False))
            _print("5) POST /admin/service-subcategories", False, f"exception={e}")
    else:
        results.append(("POST /admin/service-subcategories", False))
        _print("5) POST /admin/service-subcategories", False, "no parent_id available")

    # 6) PATCH
    if created_id:
        try:
            r = requests.patch(
                f"{BASE}/admin/service-subcategories/{created_id}",
                json={"name": "TestSub-Refactor-Renamed"},
                headers=H, timeout=15,
            )
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            sub = body.get("subcategory") or {}
            ok = r.status_code == 200 and body.get("ok") is True and sub.get("name") == "TestSub-Refactor-Renamed"
            results.append(("PATCH /admin/service-subcategories/{id}", ok))
            _print("6) PATCH /admin/service-subcategories/{id}", ok,
                   f"status={r.status_code} new_name={sub.get('name')}")
        except Exception as e:
            results.append(("PATCH /admin/service-subcategories/{id}", False))
            _print("6) PATCH /admin/service-subcategories/{id}", False, f"exception={e}")
    else:
        results.append(("PATCH /admin/service-subcategories/{id}", False))
        _print("6) PATCH /admin/service-subcategories/{id}", False, "no created_id")

    # 7) DELETE
    if created_id:
        try:
            r = requests.delete(f"{BASE}/admin/service-subcategories/{created_id}", headers=H, timeout=15)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            ok = r.status_code == 200 and body.get("ok") is True
            results.append(("DELETE /admin/service-subcategories/{id}", ok))
            _print("7) DELETE /admin/service-subcategories/{id}", ok, f"status={r.status_code}")
        except Exception as e:
            results.append(("DELETE /admin/service-subcategories/{id}", False))
            _print("7) DELETE /admin/service-subcategories/{id}", False, f"exception={e}")
    else:
        results.append(("DELETE /admin/service-subcategories/{id}", False))
        _print("7) DELETE /admin/service-subcategories/{id}", False, "no created_id")

    # 8) POST /admin/service-categories/reorder
    try:
        r = requests.get(f"{BASE}/admin/service-categories", headers=H, timeout=15)
        cats = []
        if r.status_code == 200:
            data = r.json()
            cats = data if isinstance(data, list) else (data.get("items") or data.get("categories") or [])
        if cats:
            cid = cats[0]["id"]
            original_so = cats[0].get("sort_order", 0)
            r = requests.post(
                f"{BASE}/admin/service-categories/reorder",
                json={"items": [{"id": cid, "sort_order": 999}]},
                headers=H, timeout=15,
            )
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            ok = r.status_code == 200 and body.get("ok") is True
            results.append(("POST /admin/service-categories/reorder", ok))
            _print("8) POST /admin/service-categories/reorder", ok,
                   f"status={r.status_code} updated={body.get('updated')}")
            # Restore the original sort_order
            try:
                requests.post(
                    f"{BASE}/admin/service-categories/reorder",
                    json={"items": [{"id": cid, "sort_order": original_so}]},
                    headers=H, timeout=15,
                )
            except Exception:
                pass
        else:
            results.append(("POST /admin/service-categories/reorder", False))
            _print("8) POST /admin/service-categories/reorder", False, "no category to reorder")
    except Exception as e:
        results.append(("POST /admin/service-categories/reorder", False))
        _print("8) POST /admin/service-categories/reorder", False, f"exception={e}")

    print()
    passed = sum(1 for _, ok in results if ok)
    print(f"==== SUMMARY: {passed}/{len(results)} PASS ====")
    for label, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
