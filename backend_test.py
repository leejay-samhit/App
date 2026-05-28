"""Phase D pending items (June 2026) — backend regression test.

Endpoints under test:
  1. GET  /admin/service-analytics
  2. PUT  /admin/branding   (gradient / button_style / home_banner_b64)
  3. GET  /branding
  4. GET  /services/categories
  5. GET  /payment/config       (registration fee floor of ₹118)
  6. Subcategory CRUD regression
"""
from __future__ import annotations

import sys
import requests

BASE = "https://vendor-network-app-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"
USER_EMAIL = "testuser@app.com"
USER_PASS = "Test@123"

PASS = "PASS"
FAIL = "FAIL"

results: list[tuple[str, str, str]] = []


def log(name: str, ok: bool, msg: str = ""):
    results.append((PASS if ok else FAIL, name, msg))
    print(f"[{PASS if ok else FAIL}] {name}  {msg}")


def login(email: str, password: str) -> str | None:
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=20)
    if r.status_code != 200:
        print(f"!! login {email} -> {r.status_code} {r.text[:200]}")
        return None
    j = r.json()
    return j.get("access_token") or j.get("token")


def main() -> int:
    admin_tok = login(ADMIN_EMAIL, ADMIN_PASS)
    if not admin_tok:
        print("ABORT: admin login failed")
        return 1
    user_tok = login(USER_EMAIL, USER_PASS)
    if not user_tok:
        print("ABORT: testuser login failed")
        return 1
    A = {"Authorization": f"Bearer {admin_tok}"}
    U = {"Authorization": f"Bearer {user_tok}"}

    # ─── 1. GET /admin/service-analytics ─────────────────────────────────────
    r = requests.get(f"{BASE}/admin/service-analytics", headers=A, timeout=20)
    log("1a admin GET /admin/service-analytics 200", r.status_code == 200,
        f"status={r.status_code} body={r.text[:240]}")
    if r.status_code == 200:
        body = r.json()
        avail = body.get("availability") or {}
        for key in ("available", "busy", "offline", "unset"):
            log(f"1a.availability.{key} present", key in avail,
                f"got keys={list(avail.keys())}")
        log("1a.categories is list", isinstance(body.get("categories"), list))
        rs = body.get("reveal_stats") or {}
        for key in ("count_30d", "amount_30d", "fee_30d", "gst_30d", "count_lifetime"):
            log(f"1a.reveal_stats.{key} present", key in rs)
        apps = body.get("applications") or {}
        for key in ("pending", "approved", "rejected"):
            log(f"1a.applications.{key} present", key in apps)
        log("1a.generated_at present", "generated_at" in body)

    r2 = requests.get(f"{BASE}/admin/service-analytics", headers=U, timeout=20)
    log("1b testuser GET /admin/service-analytics 403", r2.status_code == 403,
        f"status={r2.status_code} body={r2.text[:160]}")

    # ─── 2. PUT /admin/branding ──────────────────────────────────────────────
    body1 = {"gradient": {"start": "#0A0E27", "middle": "#1E2A78", "end": "#5B21B6", "glow": "#06B6D4"}}
    r = requests.put(f"{BASE}/admin/branding", headers=A, json=body1, timeout=20)
    log("2.body1 PUT branding gradient 200", r.status_code == 200,
        f"status={r.status_code} body={r.text[:240]}")
    if r.status_code == 200:
        g = (r.json() or {}).get("gradient") or {}
        log("2.body1 response.gradient present", isinstance(g, dict) and bool(g),
            f"gradient={g}")
        log("2.body1 gradient.start preserved", g.get("start") == "#0A0E27")
        log("2.body1 gradient.middle preserved", g.get("middle") == "#1E2A78")
        log("2.body1 gradient.end preserved", g.get("end") == "#5B21B6")
        log("2.body1 gradient.glow preserved", g.get("glow") == "#06B6D4")

    body2 = {"button_style": "pill"}
    r = requests.put(f"{BASE}/admin/branding", headers=A, json=body2, timeout=20)
    log("2.body2 button_style=pill 200", r.status_code == 200,
        f"status={r.status_code} body={r.text[:160]}")
    if r.status_code == 200:
        log("2.body2 response.button_style==pill",
            (r.json() or {}).get("button_style") == "pill",
            f"button_style={(r.json() or {}).get('button_style')}")

    body3 = {"button_style": "xyz"}
    r = requests.put(f"{BASE}/admin/branding", headers=A, json=body3, timeout=20)
    log("2.body3 button_style=xyz 400", r.status_code == 400,
        f"status={r.status_code} body={r.text[:160]}")

    body4 = {"gradient": {"start": "not-a-color", "end": "#FF0000"}}
    r = requests.put(f"{BASE}/admin/branding", headers=A, json=body4, timeout=20)
    log("2.body4 invalid hex silently ignored 200", r.status_code == 200,
        f"status={r.status_code} body={r.text[:240]}")
    if r.status_code == 200:
        g = (r.json() or {}).get("gradient") or {}
        log("2.body4 valid 'end' applied", g.get("end") == "#FF0000",
            f"gradient={g}")
        log("2.body4 invalid 'start' NOT overwritten with garbage",
            g.get("start") != "not-a-color",
            f"start={g.get('start')}")

    body5 = {"home_banner_b64": "https://example.com/banner.png"}
    r = requests.put(f"{BASE}/admin/branding", headers=A, json=body5, timeout=20)
    log("2.body5 home_banner_b64 URL 200", r.status_code == 200,
        f"status={r.status_code} body={r.text[:160]}")

    body6 = {"home_banner_b64": "ftp://bad"}
    r = requests.put(f"{BASE}/admin/branding", headers=A, json=body6, timeout=20)
    log("2.body6 home_banner_b64 ftp 400", r.status_code == 400,
        f"status={r.status_code} body={r.text[:160]}")

    # ─── 3. GET /branding ────────────────────────────────────────────────────
    r = requests.get(f"{BASE}/branding", timeout=20)
    log("3 public GET /branding 200", r.status_code == 200,
        f"status={r.status_code}")
    if r.status_code == 200:
        b = r.json() or {}
        log("3.gradient field present", "gradient" in b and isinstance(b.get("gradient"), dict),
            f"gradient={b.get('gradient')}")
        log("3.button_style==pill", b.get("button_style") == "pill",
            f"button_style={b.get('button_style')}")
        log("3.home_banner_b64==https URL",
            b.get("home_banner_b64") == "https://example.com/banner.png",
            f"home_banner_b64={b.get('home_banner_b64')}")

    # ─── 4. GET /services/categories ─────────────────────────────────────────
    r = requests.get(f"{BASE}/services/categories", timeout=20)
    log("4 GET /services/categories 200", r.status_code == 200,
        f"status={r.status_code}")
    if r.status_code == 200:
        cats = (r.json() or {}).get("categories") or []
        log("4 categories>=5", len(cats) >= 5, f"len={len(cats)}")
        names = [c.get("name") for c in cats]
        new_entries = ["Appliance Repair", "Delivery", "Vehicle Repair",
                       "Home Maintenance", "Labour"]
        present = [n for n in new_entries if n in names]
        log(f"4 June-2026 entries present (informational, {len(present)}/5)",
            True, f"present={present}")

    # ─── 5. GET /payment/config (>=118 floor) ────────────────────────────────
    r = requests.get(f"{BASE}/payment/config", headers=U, timeout=20)
    log("5 user GET /payment/config 200", r.status_code == 200,
        f"status={r.status_code} body={r.text[:200]}")
    if r.status_code == 200:
        cfg = r.json() or {}
        amt = cfg.get("amount")
        amt_paise = cfg.get("amount_paise")
        log("5 cfg.amount >= 118", isinstance(amt, (int, float)) and amt >= 118,
            f"amount={amt}")
        log("5 cfg.amount_paise >= 11800",
            isinstance(amt_paise, int) and amt_paise >= 11800,
            f"amount_paise={amt_paise}")

    # ─── 6. Subcategory CRUD regression ──────────────────────────────────────
    r = requests.get(f"{BASE}/admin/service-categories", headers=A, timeout=20)
    log("6a admin GET /admin/service-categories 200", r.status_code == 200,
        f"status={r.status_code}")
    parent_id = None
    if r.status_code == 200:
        cats = (r.json() or {}).get("categories") or []
        if cats:
            parent_id = cats[0].get("id")
        log("6a first category id found", bool(parent_id),
            f"parent_id={parent_id}")

    sub_id = None
    if parent_id:
        r = requests.post(f"{BASE}/admin/service-subcategories", headers=A,
                          json={"parent_id": parent_id, "name": "QA_PHASE_D_TEST"},
                          timeout=20)
        log("6b POST /admin/service-subcategories 200",
            r.status_code == 200,
            f"status={r.status_code} body={r.text[:240]}")
        if r.status_code == 200:
            sub_id = ((r.json() or {}).get("subcategory") or {}).get("id")
            log("6b returned subcategory.id", bool(sub_id), f"sub_id={sub_id}")

        r = requests.get(f"{BASE}/admin/service-subcategories",
                         headers=A, params={"parent_id": parent_id}, timeout=20)
        log("6c GET subcategories list 200", r.status_code == 200,
            f"status={r.status_code}")
        if r.status_code == 200:
            items = (r.json() or {}).get("items") or []
            ids = [it.get("id") for it in items]
            log("6c created subcategory present in list",
                sub_id in ids if sub_id else False,
                f"sub_id in list = {sub_id in ids if sub_id else 'N/A'}")

        if sub_id:
            r = requests.delete(f"{BASE}/admin/service-subcategories/{sub_id}",
                                headers=A, timeout=20)
            log("6d DELETE created subcategory 200", r.status_code == 200,
                f"status={r.status_code} body={r.text[:160]}")

    print("\n=== SUMMARY ===")
    n_pass = sum(1 for s, _, _ in results if s == PASS)
    n_fail = sum(1 for s, _, _ in results if s == FAIL)
    print(f"PASS: {n_pass}    FAIL: {n_fail}    TOTAL: {len(results)}")
    if n_fail:
        print("\n--- FAILED CASES ---")
        for s, name, msg in results:
            if s == FAIL:
                print(f"  [{s}] {name}  {msg}")
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
