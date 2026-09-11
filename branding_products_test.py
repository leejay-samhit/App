"""
Branding (theme/text/font/tabs) + Products CRUD admin endpoints test.
Scenarios A–N from /app/test_result.md backend task.
"""
import os
import sys
import json
import uuid
import time
import requests

BASE = "https://slangcart-tracking.preview.emergentagent.com/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"

PASS = []
FAIL = []


def rec(name, ok, detail=""):
    if ok:
        PASS.append(name)
        print(f"  PASS  {name}")
    else:
        FAIL.append((name, detail))
        print(f"  FAIL  {name} :: {detail}")


def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=20)
    if r.status_code != 200:
        raise SystemExit(f"login {email} failed: {r.status_code} {r.text}")
    return r.json()["token"], r.json()["user"]


def H(token):
    return {"Authorization": f"Bearer {token}"}


def main():
    print(f"\nTarget: {BASE}\n")

    # ---- Setup: super_admin ----
    super_token, super_user = login(ADMIN_EMAIL, ADMIN_PASS)
    rec("Setup: super_admin login", True)

    # Create helper admins (manager, support, finance) — re-use if already exist by random suffix
    suffix = uuid.uuid4().hex[:6]
    helpers = {}
    for role in ("manager", "support", "finance"):
        email = f"helper.{role}.{suffix}@brandtest.com"
        password = "Helper@123"
        r = requests.post(
            f"{BASE}/admin/admins",
            headers=H(super_token),
            json={"name": f"Helper {role}", "email": email, "password": password, "admin_role": role},
            timeout=20,
        )
        if r.status_code != 200:
            rec(f"Setup: create helper {role}", False, f"{r.status_code} {r.text[:300]}")
            return
        helpers[role] = {"email": email, "password": password, "id": r.json()["id"]}
        # login
        t, _ = login(email, password)
        helpers[role]["token"] = t
    rec("Setup: helper admins (manager/support/finance) created & logged in", True)

    # Create a regular user too
    user_email = f"branduser.{suffix}@brandtest.com"
    rr = requests.post(
        f"{BASE}/auth/register",
        json={"name": "Brand User", "email": user_email, "password": "User@1234"},
        timeout=20,
    )
    if rr.status_code != 200:
        rec("Setup: regular user register", False, f"{rr.status_code} {rr.text[:200]}")
        return
    user_token = rr.json()["token"]
    user_id = rr.json()["user"]["id"]
    rec("Setup: regular user registered", True)

    # ============ A. GET /branding (public) ============
    print("\n[A] GET /branding (public, no auth)")
    r = requests.get(f"{BASE}/branding", timeout=20)
    rec("A.1 GET /branding (no auth) → 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    if r.status_code == 200:
        b1 = r.json()
        for k in ("app_name", "tagline", "login_subtitle", "payment_hero", "pending_hero", "colors", "font", "tabs"):
            rec(f"A.1 has key: {k}", k in b1)
        rec("A.1 colors is dict with primary",
            isinstance(b1.get("colors"), dict) and "primary" in b1["colors"],
            json.dumps(b1.get("colors"))[:200])
        rec("A.1 tabs is non-empty list",
            isinstance(b1.get("tabs"), list) and len(b1["tabs"]) >= 1)
        # idempotent
        r2 = requests.get(f"{BASE}/branding", timeout=20).json()
        rec("A.2 idempotent (2nd GET equals first)", r2 == b1)

    # ============ B. PUT /admin/branding super_admin ============
    print("\n[B] PUT /admin/branding {app_name, colors.primary, font:poppins} as super_admin")
    body = {"app_name": "BrandX", "colors": {"primary": "#FF0066"}, "font": "poppins"}
    r = requests.put(f"{BASE}/admin/branding", headers=H(super_token), json=body, timeout=20)
    rec("B.1 PUT super_admin → 200", r.status_code == 200, f"{r.status_code} {r.text[:300]}")
    if r.status_code == 200:
        ret = r.json()
        rec("B.1 ret.app_name=BrandX", ret.get("app_name") == "BrandX", str(ret.get("app_name")))
        rec("B.1 ret.colors.primary=#FF0066", (ret.get("colors") or {}).get("primary") == "#FF0066")
        rec("B.1 ret.font=poppins", ret.get("font") == "poppins")
    g = requests.get(f"{BASE}/branding", timeout=20).json()
    rec("B.2 GET reflects app_name=BrandX", g.get("app_name") == "BrandX")
    rec("B.2 GET reflects primary=#FF0066", (g.get("colors") or {}).get("primary") == "#FF0066")
    rec("B.2 GET reflects font=poppins", g.get("font") == "poppins")
    # original other defaults still present (e.g. accent stays default)
    rec("B.2 GET other defaults preserved (accent present)", "accent" in (g.get("colors") or {}))

    # ============ C. PUT with invalid hex color (and one valid) ============
    print("\n[C] PUT colors with invalid hex + valid hex — invalid silently dropped")
    body = {"colors": {"primary": "not-a-color", "accent": "#00AABB"}}
    r = requests.put(f"{BASE}/admin/branding", headers=H(super_token), json=body, timeout=20)
    rec("C.1 PUT mixed hex → 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    g = requests.get(f"{BASE}/branding", timeout=20).json()
    rec("C.1 invalid hex dropped (primary stayed #FF0066)", (g.get("colors") or {}).get("primary") == "#FF0066")
    rec("C.1 valid hex applied (accent=#00AABB)", (g.get("colors") or {}).get("accent") == "#00AABB")

    # ============ D. PUT font invalid → 400 ============
    print("\n[D] PUT font=not-a-font → 400")
    r = requests.put(f"{BASE}/admin/branding", headers=H(super_token), json={"font": "not-a-font"}, timeout=20)
    rec("D.1 invalid font → 400", r.status_code == 400, f"{r.status_code} {r.text[:200]}")

    # ============ E. PUT all tabs invisible → 400 ============
    print("\n[E] PUT all tabs visible:false → 400")
    bad_tabs = [
        {"key": "dashboard", "label": "Dashboard", "icon": "home", "visible": False},
        {"key": "network", "label": "Network", "icon": "git-branch", "visible": False},
        {"key": "wallet", "label": "Wallet", "icon": "credit-card", "visible": False},
        {"key": "shop", "label": "Shop", "icon": "shopping-bag", "visible": False},
        {"key": "profile", "label": "Profile", "icon": "user", "visible": False},
    ]
    r = requests.put(f"{BASE}/admin/branding", headers=H(super_token), json={"tabs": bad_tabs}, timeout=20)
    rec("E.1 all-invisible tabs → 400", r.status_code == 400, f"{r.status_code} {r.text[:200]}")

    # ============ F. PUT reorder tabs (wallet first) → 200, GET reflects new order ============
    print("\n[F] Reorder tabs → wallet first")
    new_tabs = [
        {"key": "wallet", "label": "Wallet", "icon": "credit-card", "visible": True},
        {"key": "dashboard", "label": "Dashboard", "icon": "home", "visible": True},
        {"key": "network", "label": "Network", "icon": "git-branch", "visible": True},
        {"key": "shop", "label": "Shop", "icon": "shopping-bag", "visible": True},
        {"key": "profile", "label": "Profile", "icon": "user", "visible": True},
    ]
    r = requests.put(f"{BASE}/admin/branding", headers=H(super_token), json={"tabs": new_tabs}, timeout=20)
    rec("F.1 reorder tabs → 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    g = requests.get(f"{BASE}/branding", timeout=20).json()
    keys_order = [t["key"] for t in g.get("tabs", [])]
    rec(f"F.2 GET tabs first key=wallet (got order: {keys_order})", keys_order[:1] == ["wallet"])
    rec("F.2 GET tabs has all 5 standard keys",
        set(keys_order) == {"dashboard", "network", "wallet", "shop", "profile"})

    # ============ G. RBAC on PUT ============
    print("\n[G] RBAC: manager/support/finance/user PUT → 403; user no auth → 401")
    for role in ("manager", "support", "finance"):
        r = requests.put(f"{BASE}/admin/branding", headers=H(helpers[role]["token"]),
                         json={"app_name": "Hack"}, timeout=20)
        rec(f"G.1 {role} PUT → 403", r.status_code == 403, f"{r.status_code} {r.text[:200]}")
    r = requests.put(f"{BASE}/admin/branding", headers=H(user_token), json={"app_name": "Hack"}, timeout=20)
    rec("G.2 regular user PUT → 403", r.status_code == 403, f"{r.status_code} {r.text[:200]}")
    r = requests.put(f"{BASE}/admin/branding", json={"app_name": "Hack"}, timeout=20)
    rec("G.3 no-auth PUT → 401", r.status_code == 401, f"{r.status_code} {r.text[:200]}")

    # RBAC on RESET
    for role in ("manager", "support", "finance"):
        r = requests.post(f"{BASE}/admin/branding/reset", headers=H(helpers[role]["token"]), timeout=20)
        rec(f"G.4 {role} RESET → 403", r.status_code == 403, f"{r.status_code} {r.text[:200]}")

    # ============ H. RESET endpoint ============
    print("\n[H] POST /admin/branding/reset → 200 returns defaults")
    r = requests.post(f"{BASE}/admin/branding/reset", headers=H(super_token), timeout=20)
    rec("H.1 reset → 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    if r.status_code == 200:
        d = r.json()
        rec("H.1 app_name back to NetworkPay", d.get("app_name") == "NetworkPay", str(d.get("app_name")))
        rec("H.1 font back to system", d.get("font") == "system")
        rec("H.1 colors.primary back to #143D2E", (d.get("colors") or {}).get("primary") == "#143D2E")
        # tabs default order: dashboard, network, wallet, shop, profile
        order = [t["key"] for t in d.get("tabs", [])]
        rec(f"H.1 tabs order back to default (got {order})",
            order == ["dashboard", "network", "wallet", "shop", "profile"])

    # ===========================================================
    # PRODUCTS
    # ===========================================================

    # ============ I. POST /admin/products with is_published=false; not in public list ============
    print("\n[I] super_admin POST /admin/products with is_published=false")
    p_body = {
        "name": f"DraftWidget-{suffix}",
        "price": 199.99,
        "image_url": "https://example.com/img.png",
        "description": "A draft product for testing",
        "stock": 25,
        "category": "test-category",
        "is_published": False,
    }
    r = requests.post(f"{BASE}/admin/products", headers=H(super_token), json=p_body, timeout=20)
    rec("I.1 super_admin POST product (unpublished) → 200", r.status_code == 200, f"{r.status_code} {r.text[:300]}")
    draft_id = r.json().get("id") if r.status_code == 200 else None

    # publish one too
    p_body_pub = {
        "name": f"PubWidget-{suffix}",
        "price": 49.50,
        "image_url": "https://example.com/img2.png",
        "description": "Published product",
        "stock": 50,
        "category": "test-category",
        "is_published": True,
    }
    r = requests.post(f"{BASE}/admin/products", headers=H(super_token), json=p_body_pub, timeout=20)
    rec("I.1b super_admin POST product (published) → 200", r.status_code == 200, f"{r.status_code} {r.text[:300]}")
    pub_id = r.json().get("id") if r.status_code == 200 else None

    # finance must be 403 on POST
    r = requests.post(f"{BASE}/admin/products", headers=H(helpers["finance"]["token"]),
                      json={"name": "FinanceShouldFail", "price": 1.0, "image_url": "u"}, timeout=20)
    rec("I.2 finance POST product → 403", r.status_code == 403, f"{r.status_code} {r.text[:200]}")

    # manager and support can create
    r = requests.post(f"{BASE}/admin/products", headers=H(helpers["manager"]["token"]),
                      json={"name": f"MgrWidget-{suffix}", "price": 10.0, "image_url": "u",
                            "is_published": True}, timeout=20)
    rec("I.3 manager POST product → 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    mgr_pid = r.json().get("id") if r.status_code == 200 else None

    r = requests.post(f"{BASE}/admin/products", headers=H(helpers["support"]["token"]),
                      json={"name": f"SupWidget-{suffix}", "price": 11.0, "image_url": "u",
                            "is_published": False}, timeout=20)
    rec("I.4 support POST product → 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    sup_pid = r.json().get("id") if r.status_code == 200 else None

    # Public /products: must hide unpublished but include published + legacy
    r = requests.get(f"{BASE}/products", timeout=20)
    rec("I.5 public GET /products → 200", r.status_code == 200)
    pub_list = r.json() if r.status_code == 200 else []
    pub_ids = {p.get("id") for p in pub_list}
    rec(f"I.5 public list HIDES unpublished draft_id={draft_id}", draft_id not in pub_ids)
    rec(f"I.5 public list INCLUDES published pub_id={pub_id}", pub_id in pub_ids)
    rec(f"I.5 public list HIDES support unpublished sup_pid={sup_pid}", sup_pid not in pub_ids)
    rec(f"I.5 public list INCLUDES manager published mgr_pid={mgr_pid}", mgr_pid in pub_ids)

    # /admin/products: all admins should see all (including unpublished)
    r = requests.get(f"{BASE}/admin/products", headers=H(super_token), timeout=20)
    rec("I.6 super_admin GET /admin/products → 200", r.status_code == 200)
    admin_ids = {p.get("id") for p in (r.json() if r.status_code == 200 else [])}
    for pid, name in [(draft_id, "draft"), (pub_id, "published"), (mgr_pid, "mgr"), (sup_pid, "sup")]:
        rec(f"I.6 admin list contains {name}={pid}", pid in admin_ids)

    # finance can read /admin/products too (any admin)
    r = requests.get(f"{BASE}/admin/products", headers=H(helpers["finance"]["token"]), timeout=20)
    rec("I.7 finance GET /admin/products → 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    # ============ J. PATCH product ============
    print("\n[J] PATCH product")
    if draft_id:
        r = requests.patch(f"{BASE}/admin/products/{draft_id}", headers=H(super_token),
                           json={"price": 299.99, "is_published": True, "category": "updated-cat"}, timeout=20)
        rec("J.1 PATCH draft → 200", r.status_code == 200, f"{r.status_code} {r.text[:300]}")
        if r.status_code == 200:
            updated = r.json()
            rec("J.1 price updated", updated.get("price") == 299.99, str(updated.get("price")))
            rec("J.1 is_published updated to True", updated.get("is_published") is True)
            rec("J.1 category updated", updated.get("category") == "updated-cat")
        # confirm now visible publicly
        pub_after = requests.get(f"{BASE}/products", timeout=20).json()
        rec("J.1b previously-draft now visible in public list",
            draft_id in {p.get("id") for p in pub_after})

    # PATCH non-existent
    r = requests.patch(f"{BASE}/admin/products/non-existent-{uuid.uuid4().hex[:8]}",
                       headers=H(super_token), json={"price": 1.0}, timeout=20)
    rec("J.2 PATCH non-existent → 404", r.status_code == 404, f"{r.status_code} {r.text[:200]}")

    # finance PATCH → 403
    if pub_id:
        r = requests.patch(f"{BASE}/admin/products/{pub_id}",
                           headers=H(helpers["finance"]["token"]), json={"price": 0.01}, timeout=20)
        rec("J.3 finance PATCH → 403", r.status_code == 403, f"{r.status_code} {r.text[:200]}")

    # manager/support PATCH → 200
    if mgr_pid:
        r = requests.patch(f"{BASE}/admin/products/{mgr_pid}",
                           headers=H(helpers["manager"]["token"]), json={"price": 12.5}, timeout=20)
        rec("J.4 manager PATCH → 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    if sup_pid:
        r = requests.patch(f"{BASE}/admin/products/{sup_pid}",
                           headers=H(helpers["support"]["token"]), json={"stock": 99}, timeout=20)
        rec("J.5 support PATCH → 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    # ============ L. (do this BEFORE delete) cart-add then DELETE; verify cart purged ============
    print("\n[L] User adds product to cart, then admin DELETE removes it from cart")
    if pub_id:
        # user must register-fee first? cart/add doesn't gate on payment in this app — verify directly
        # Set user's wallet/registration if needed; cart/add typically just stores items.
        r_add = requests.post(f"{BASE}/cart/add", headers=H(user_token),
                              json={"product_id": pub_id, "qty": 1}, timeout=20)
        rec(f"L.1 user POST /cart/add → 200 (status={r_add.status_code})",
            r_add.status_code == 200, f"{r_add.status_code} {r_add.text[:300]}")

        cart_before = requests.get(f"{BASE}/cart", headers=H(user_token), timeout=20).json()
        # Cart payload may be a dict {items:[...]} or a list
        items_before = cart_before.get("items", cart_before) if isinstance(cart_before, dict) else cart_before
        ids_in_cart = {it.get("product_id") for it in items_before} if isinstance(items_before, list) else set()
        rec(f"L.1b cart contains pub_id before delete (cart={ids_in_cart})", pub_id in ids_in_cart)

        # ============ K. DELETE product ============
        r = requests.delete(f"{BASE}/admin/products/{pub_id}", headers=H(super_token), timeout=20)
        rec("K.1 DELETE pub_id → 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
        # Second delete → 404
        r = requests.delete(f"{BASE}/admin/products/{pub_id}", headers=H(super_token), timeout=20)
        rec("K.2 second DELETE same id → 404", r.status_code == 404, f"{r.status_code} {r.text[:200]}")

        # L.2 cart no longer contains it
        cart_after = requests.get(f"{BASE}/cart", headers=H(user_token), timeout=20).json()
        items_after = cart_after.get("items", cart_after) if isinstance(cart_after, dict) else cart_after
        ids_after = {it.get("product_id") for it in items_after} if isinstance(items_after, list) else set()
        rec(f"L.2 deleted product NOT in user cart (after={ids_after})", pub_id not in ids_after)

    # finance DELETE → 403 on a remaining product
    if mgr_pid:
        r = requests.delete(f"{BASE}/admin/products/{mgr_pid}",
                            headers=H(helpers["finance"]["token"]), timeout=20)
        rec("K.3 finance DELETE → 403", r.status_code == 403, f"{r.status_code} {r.text[:200]}")

    # ============ N. Regression: legacy /api/products still works ============
    print("\n[N] Regression: public /api/products endpoint")
    r = requests.get(f"{BASE}/products", timeout=20)
    rec("N.1 public /products → 200", r.status_code == 200)
    rec("N.1 returns list", isinstance(r.json(), list))
    if isinstance(r.json(), list):
        # Confirm only published (or legacy without flag) shown
        bad = [p for p in r.json() if p.get("is_published") is False]
        rec(f"N.1 no is_published=False leaked (found {len(bad)})", len(bad) == 0)

    # ============ M. Cleanup ============
    print("\n[M] Cleanup")
    cleaned = 0
    for pid in (draft_id, mgr_pid, sup_pid):
        if not pid:
            continue
        r = requests.delete(f"{BASE}/admin/products/{pid}", headers=H(super_token), timeout=20)
        if r.status_code in (200, 404):
            cleaned += 1
    rec(f"M.1 cleaned up remaining products ({cleaned} deleted)", cleaned >= 1)

    # Reset branding to clean state
    r = requests.post(f"{BASE}/admin/branding/reset", headers=H(super_token), timeout=20)
    rec("M.2 final branding reset → 200", r.status_code == 200)

    # Delete helper admins + user
    for role, info in helpers.items():
        r = requests.delete(f"{BASE}/admin/users/{info['id']}", headers=H(super_token), timeout=20)
        rec(f"M.3 cleanup helper {role}", r.status_code in (200, 404))
    r = requests.delete(f"{BASE}/admin/users/{user_id}", headers=H(super_token), timeout=20)
    rec("M.3 cleanup regular user", r.status_code in (200, 404))

    # Final sanity: branding back to defaults
    g = requests.get(f"{BASE}/branding", timeout=20).json()
    rec("M.4 final GET /branding has app_name=NetworkPay", g.get("app_name") == "NetworkPay")
    rec("M.4 final font=system", g.get("font") == "system")
    rec("M.4 final colors.primary=#143D2E",
        (g.get("colors") or {}).get("primary") == "#143D2E")

    # Summary
    print("\n" + "=" * 70)
    print(f"PASSED: {len(PASS)}")
    print(f"FAILED: {len(FAIL)}")
    if FAIL:
        print("\nFailures:")
        for n, d in FAIL:
            print(f"  - {n}: {d}")
    print("=" * 70)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
