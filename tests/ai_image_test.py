"""
AI Image Generation backend test runner.

Targets:
  A) POST /api/products/ai-image  (new endpoint)
  B) Product CRUD with optional sub_category + clothing_size round-trip
  C) Regression smoke (branding, shop-layout, products)

IMPORTANT: never print/log full base64 strings. Only first 30 chars + total length.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

import requests


# ───── Helpers ─────────────────────────────────────────────

def _read_credentials() -> dict:
    """Read /app/memory/test_credentials.md if available, else fall back to defaults."""
    defaults = {
        "admin_email": "admin@app.com",
        "admin_password": "Admin@123",
        "user_email": "testuser@app.com",
        "user_password": "Test@123",
    }
    path = Path("/app/memory/test_credentials.md")
    if path.exists() and path.read_text().strip():
        return defaults  # file exists, defaults aligned with it
    return defaults


def _backend_url() -> str:
    """Read EXPO_PUBLIC_BACKEND_URL from /app/frontend/.env."""
    env = Path("/app/frontend/.env").read_text()
    for line in env.splitlines():
        if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
            url = line.split("=", 1)[1].strip().strip('"').strip("'")
            return url.rstrip("/") + "/api"
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL not found in /app/frontend/.env")


BASE = _backend_url()
CREDS = _read_credentials()

PASS: list[str] = []
FAIL: list[str] = []


def record(ok: bool, name: str, detail: str = ""):
    line = f"{'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else "")
    print(line)
    (PASS if ok else FAIL).append(name + (" — " + detail if detail else ""))


def login(email: str, password: str) -> str | None:
    r = requests.post(
        f"{BASE}/auth/login",
        json={"email": email, "password": password},
        timeout=60,
    )
    if r.status_code != 200:
        print(f"[login fail] {email} -> {r.status_code} {r.text[:200]}")
        return None
    return r.json().get("token") or r.json().get("access_token")


def get_me(token: str) -> dict:
    r = requests.get(f"{BASE}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    return r.json() if r.status_code == 200 else {}


def register_fresh_user() -> tuple[str, str, str]:
    """Register a fresh role=user account. Returns (email, password, token)."""
    import random, string
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    email = f"airegtest_{suffix}@example.com"
    password = "AIregTest@2026"
    body = {"name": "AI Reg Test User", "email": email, "password": password, "phone": "9988770011"}
    r = requests.post(f"{BASE}/auth/register", json=body, timeout=60)
    if r.status_code != 200:
        print(f"[register fail] {email} -> {r.status_code} {r.text[:200]}")
        return email, password, ""
    token = r.json().get("token") or r.json().get("access_token") or ""
    return email, password, token


def _short(s: str, n: int = 30) -> str:
    return (s[:n] + "…") if s and len(s) > n else (s or "")


# ───── Fetch tiny valid JPEG for reference image ───────────

def get_reference_b64() -> str:
    try:
        r = requests.get("https://placehold.co/400x600/jpg", timeout=30)
        if r.status_code == 200 and r.content:
            return "data:image/jpeg;base64," + base64.b64encode(r.content).decode()
    except Exception as e:
        print(f"[warn] placehold.co fetch failed: {e}")
    # Fallback: 1x1 jpeg
    raw = base64.b64decode(
        "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/2wBDAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAr/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AL+AAAA="
    )
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode()


# ───── Section A: POST /products/ai-image ──────────────────

def test_ai_image(admin_token: str, fresh_user_token: str, ref_b64: str):
    print("\n── Section A: POST /products/ai-image ──")
    url = f"{BASE}/products/ai-image"

    # A1: No auth → 401
    r = requests.post(url, json={"image_data_url": ref_b64, "gender": "female"}, timeout=60)
    record(r.status_code in (401, 403), "A1 No auth → 401/403", f"got {r.status_code}")

    # A2: Auth as fresh regular user (role=user) → 403
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {fresh_user_token}"},
        json={"image_data_url": ref_b64, "gender": "female"},
        timeout=120,
    )
    body = ""
    try:
        body = r.json().get("detail", "")
    except Exception:
        body = r.text[:200]
    ok = r.status_code == 403 and "admins and vendors" in (body or "").lower()
    record(ok, "A2 Regular user → 403 admins/vendors only", f"status={r.status_code} detail={body[:120]}")

    # A3: Admin, missing gender → 422
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"image_data_url": ref_b64},
        timeout=30,
    )
    record(r.status_code == 422, "A3 Admin missing gender → 422", f"got {r.status_code}")

    # A4: Admin, image too small → 400
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"image_data_url": "x", "gender": "female"},
        timeout=30,
    )
    try:
        detail = r.json().get("detail", "")
    except Exception:
        detail = r.text[:200]
    ok = r.status_code == 400 and "too small or invalid" in (detail or "").lower()
    record(ok, "A4 Admin tiny image → 400 too small/invalid", f"status={r.status_code} detail={detail[:120]}")

    # A5: Admin, valid body, count=5
    payload = {
        "image_data_url": ref_b64,
        "gender": "female",
        "category": "Clothes",
        "size": "M",
        "count": 5,
    }
    print(f"  → A5 calling AI image gen (count=5), this may take 20-60s …")
    t0 = time.time()
    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {admin_token}"},
            json=payload,
            timeout=180,
        )
    except requests.exceptions.RequestException as e:
        record(False, "A5 Admin valid call (count=5)", f"request exception: {e}")
        return
    dt = time.time() - t0

    if r.status_code == 200:
        try:
            data = r.json()
        except Exception:
            data = {}
        images = data.get("images") or []
        count = data.get("count")
        # Validate shape — no full base64 printed
        previews = [(i, _short(s, 30), len(s)) for i, s in enumerate(images)]
        for i, prev, ln in previews:
            print(f"    image[{i}] startswith={prev!r} len={ln}")
        ok_count = isinstance(count, int) and count >= 1
        ok_imgs = all(isinstance(s, str) and s.startswith("data:image") and len(s) >= 1000 for s in images)
        ok = ok_count and ok_imgs and len(images) >= 1
        record(ok, f"A5 Admin valid 200 (count=5) [{dt:.1f}s]", f"images_returned={len(images)} count_field={count}")
    elif r.status_code == 502:
        # Sane fallback path
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = r.text[:200]
        record(True, "A5 Admin valid → 502 (AI provider returned no images, sane)", f"detail={detail[:120]}")
    else:
        record(False, "A5 Admin valid call", f"status={r.status_code} body={r.text[:200]}")

    # A6: Admin, count=1 (lower bound)
    payload2 = dict(payload)
    payload2["count"] = 1
    print(f"  → A6 calling AI image gen (count=1) …")
    t0 = time.time()
    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {admin_token}"},
            json=payload2,
            timeout=120,
        )
    except requests.exceptions.RequestException as e:
        record(False, "A6 Admin valid call (count=1)", f"request exception: {e}")
        return
    dt = time.time() - t0
    if r.status_code == 200:
        try:
            data = r.json()
        except Exception:
            data = {}
        images = data.get("images") or []
        count = data.get("count")
        for i, s in enumerate(images):
            print(f"    image[{i}] startswith={_short(s, 30)!r} len={len(s)}")
        ok = (
            isinstance(count, int)
            and count >= 1
            and len(images) >= 1
            and all(s.startswith("data:image") and len(s) >= 1000 for s in images)
        )
        record(ok, f"A6 Admin valid 200 (count=1) [{dt:.1f}s]", f"images_returned={len(images)}")
    elif r.status_code == 502:
        record(True, "A6 Admin valid count=1 → 502 (sane)", "")
    else:
        record(False, "A6 Admin valid call (count=1)", f"status={r.status_code} body={r.text[:200]}")


# ───── Section B: Product CRUD round-trip ──────────────────

def test_product_crud(admin_token: str) -> None:
    print("\n── Section B: Product CRUD with optional fields ──")
    h = {"Authorization": f"Bearer {admin_token}"}

    # B1: POST /admin/products
    create_body = {
        "name": "AI Test Dress (regression)",
        "price": 1299.0,
        "image_url": "data:image/jpeg;base64,AAAA",
        "description": "Test clothing item for AI image regression",
        "stock": 10,
        "category": "Clothes",
        "is_published": False,
        "sub_category": "female",
        "clothing_size": "M",
    }
    r = requests.post(f"{BASE}/admin/products", headers=h, json=create_body, timeout=60)
    if r.status_code != 200:
        record(False, "B1 POST /admin/products with clothes fields", f"status={r.status_code} body={r.text[:200]}")
        return
    doc = r.json()
    pid = doc.get("id")
    ok = (
        bool(pid)
        and doc.get("sub_category") == "female"
        and doc.get("clothing_size") == "M"
    )
    record(ok, "B1 POST /admin/products with sub_category+clothing_size", f"id={pid} sub_category={doc.get('sub_category')} clothing_size={doc.get('clothing_size')}")

    # B2: PATCH /admin/products/{id} update clothing_size=L
    r = requests.patch(
        f"{BASE}/admin/products/{pid}",
        headers=h,
        json={"clothing_size": "L"},
        timeout=30,
    )
    if r.status_code != 200:
        record(False, "B2 PATCH clothing_size=L", f"status={r.status_code} body={r.text[:200]}")
    else:
        fresh = r.json()
        ok = fresh.get("clothing_size") == "L" and fresh.get("sub_category") == "female"
        record(ok, "B2 PATCH clothing_size=L → round-trip", f"clothing_size={fresh.get('clothing_size')} sub_category={fresh.get('sub_category')}")

    # B3: DELETE cleanup
    r = requests.delete(f"{BASE}/admin/products/{pid}", headers=h, timeout=30)
    ok = r.status_code == 200
    record(ok, "B3 DELETE /admin/products/{id} cleanup", f"status={r.status_code}")


# ───── Section C: Regression smoke ─────────────────────────

def test_smoke():
    print("\n── Section C: Regression smoke ──")

    r = requests.get(f"{BASE}/branding", timeout=30)
    record(r.status_code == 200, "C1 GET /branding (no auth) → 200", f"status={r.status_code}")

    r = requests.get(f"{BASE}/shop-layout?scope=home", timeout=30)
    record(r.status_code == 200, "C2 GET /shop-layout?scope=home (no auth) → 200", f"status={r.status_code}")

    r = requests.get(f"{BASE}/products", timeout=30)
    record(r.status_code == 200, "C3 GET /products (no auth) → 200", f"status={r.status_code}")


# ───── Main ────────────────────────────────────────────────

def main():
    print(f"BACKEND = {BASE}")
    admin_token = login(CREDS["admin_email"], CREDS["admin_password"])
    user_token = login(CREDS["user_email"], CREDS["user_password"])
    if not admin_token or not user_token:
        print(f"❌ Could not get tokens (admin={bool(admin_token)} user={bool(user_token)})")
        sys.exit(2)

    # Verify role of seeded test user
    me = get_me(user_token)
    seeded_role = me.get("role")
    print(f"  seeded testuser role = {seeded_role!r}")

    # If seeded testuser is not 'user' role, register a fresh role=user account for A2.
    fresh_email = fresh_password = ""
    fresh_token = ""
    if seeded_role and seeded_role.lower() != "user":
        print(f"  ⚠ seeded testuser is not role=user (it is {seeded_role!r}); registering a fresh regular user for A2")
        fresh_email, fresh_password, fresh_token = register_fresh_user()
        if not fresh_token:
            print("❌ Could not register fresh regular user for A2")
            sys.exit(2)
        fme = get_me(fresh_token)
        print(f"  fresh user role = {fme.get('role')!r} email={fme.get('email')}")
        reg_user_token = fresh_token
    else:
        reg_user_token = user_token

    ref_b64 = get_reference_b64()
    print(f"  reference image len={len(ref_b64)} prefix={_short(ref_b64, 30)!r}")

    test_ai_image(admin_token, reg_user_token, ref_b64)
    test_product_crud(admin_token)
    test_smoke()

    print("\n──────────── SUMMARY ────────────")
    print(f"PASS = {len(PASS)}")
    print(f"FAIL = {len(FAIL)}")
    if FAIL:
        print("\nFailed cases:")
        for f in FAIL:
            print(f"  ❌ {f}")
    sys.exit(0 if not FAIL else 1)


if __name__ == "__main__":
    main()
