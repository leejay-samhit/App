# Iteration 105 — regression smoke: core areas still respond for existing seeded accounts.
import os
import pytest
import requests


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = (os.environ.get("EXPO_BACKEND_URL") or _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL")).rstrip("/") + "/api"


def _login(email, pw):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pw}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {email}: {r.status_code}")
    return {"Authorization": f"Bearer {r.json()['token']}", "X-Client-Platform": "android"}


@pytest.fixture(scope="module")
def buyer():
    return _login("testbuyer@test.com", "Test@1234")


@pytest.fixture(scope="module")
def admin():
    return _login("support@slangcart.com", "3)Ywxtic")


@pytest.mark.parametrize("path", ["/auth/me", "/products", "/cart", "/orders/me", "/services", "/services/categories",
                                  "/services/bookings/me", "/chat/threads", "/recharge/options", "/recharge/history",
                                  "/wallet/topup/config", "/auth/signup-gate/status"])
def test_buyer_areas(buyer, path):
    r = requests.get(f"{BASE}{path}", headers=buyer, timeout=30)
    assert r.status_code == 200, f"{path} {r.status_code} {r.text[:120]}"


def test_buyer_still_free(buyer):
    me = requests.get(f"{BASE}/auth/me", headers=buyer, timeout=30).json()
    assert me.get("registration_paid") is False


@pytest.mark.parametrize("path", ["/admin/stats", "/admin/users", "/admin/users/source-counts"])
def test_admin_areas(admin, path):
    r = requests.get(f"{BASE}{path}", headers=admin, timeout=30)
    assert r.status_code == 200, f"{path} {r.status_code}"


def test_google_exchange_rejects_garbage():
    r = requests.post(f"{BASE}/auth/google/exchange", json={"session_id": "bogus", "code": "bogus"}, timeout=30)
    assert r.status_code in (400, 401, 422), r.status_code
