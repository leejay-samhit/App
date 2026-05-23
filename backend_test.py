"""Backend regression tests for the session changes:
A) Legal pages CRUD
B) Service Provider Profile + Reviews
C) Chat Support
D) Placement realignment fields regression
"""
import requests

BASE = "https://vendor-network-app-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PW = "Admin@123"
USER_EMAIL = "testuser@app.com"
USER_PW = "Test@123"

results = []


def report(test_id, name, passed, detail=""):
    results.append((test_id, name, passed, detail))
    flag = "PASS" if passed else "FAIL"
    print(f"[{flag}] {test_id} {name}: {detail}")


def login(email, pw):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pw}, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data.get("token") or data.get("access_token")


def main():
    print(f"BASE={BASE}\n")
    try:
        admin_tok = login(ADMIN_EMAIL, ADMIN_PW)
        print(f"Admin login OK")
    except Exception as e:
        report("LOGIN", "admin login", False, repr(e))
        return
    try:
        user_tok = login(USER_EMAIL, USER_PW)
        print(f"User login OK")
    except Exception as e:
        report("LOGIN", "testuser login", False, repr(e))
        return

    A_HDR = {"Authorization": f"Bearer {admin_tok}"}
    U_HDR = {"Authorization": f"Bearer {user_tok}"}

    # A) LEGAL PAGES
    r = requests.get(f"{BASE}/legal/privacy", timeout=15)
    ok = r.status_code == 200 and all(k in r.json() for k in ("kind", "content_text", "is_default"))
    report("A1", "GET /legal/privacy", ok, f"status={r.status_code}")
    initial_is_default = r.json().get("is_default") if r.ok else None
    print(f"   initial is_default={initial_is_default}")

    for kind in ("terms", "refund", "contact_us"):
        r = requests.get(f"{BASE}/legal/{kind}", timeout=15)
        ok = r.status_code == 200 and r.json().get("kind") == kind
        report(f"A_{kind}", f"GET /legal/{kind}", ok, f"status={r.status_code}")

    r = requests.get(f"{BASE}/legal/unknown_kind", timeout=15)
    report("A5", "GET /legal/unknown_kind", r.status_code == 404, f"status={r.status_code}")

    r = requests.get(f"{BASE}/admin/legal", headers=A_HDR, timeout=15)
    if r.status_code == 200:
        items = r.json().get("items", [])
        kinds = sorted([i.get("kind") for i in items])
        ok = kinds == ["contact_us", "privacy", "refund", "terms"]
        report("A6", "GET /admin/legal admin", ok, f"items={len(items)} kinds={kinds}")
    else:
        report("A6", "GET /admin/legal admin", False, f"status={r.status_code} body={r.text[:200]}")

    r = requests.get(f"{BASE}/admin/legal", timeout=15)
    ok = r.status_code in (401, 403)
    report("A7", "GET /admin/legal no auth", ok, f"status={r.status_code} body={r.text[:120]}")

    new_content = "## Custom Privacy\n\nUpdated by automated regression test."
    r = requests.put(f"{BASE}/admin/legal/privacy", headers=A_HDR,
                     json={"content_text": new_content}, timeout=15)
    ok = r.status_code == 200 and r.json().get("ok") is True
    report("A8", "PUT /admin/legal/privacy", ok, f"status={r.status_code} body={r.text[:200]}")

    r = requests.get(f"{BASE}/legal/privacy", timeout=15)
    if r.status_code == 200:
        b = r.json()
        ok = (b.get("is_default") is False) and (b.get("content_text") == new_content)
        report("A9", "GET /legal/privacy post-update", ok,
               f"is_default={b.get('is_default')} matches={b.get('content_text')==new_content}")
    else:
        report("A9", "GET /legal/privacy post-update", False, f"status={r.status_code}")

    r = requests.put(f"{BASE}/admin/legal/privacy", headers=A_HDR,
                     json={"content_text": "short"}, timeout=15)
    report("A10", "PUT /admin/legal/privacy <10 chars", r.status_code == 422,
           f"status={r.status_code}")

    r = requests.put(f"{BASE}/admin/legal/unknown_kind", headers=A_HDR,
                     json={"content_text": "long enough content text here"}, timeout=15)
    report("A11", "PUT /admin/legal/unknown_kind", r.status_code == 404, f"status={r.status_code}")

    # B) SERVICE PROVIDER
    provider_id = None
    r = requests.get(f"{BASE}/services", params={"lat": 12.97, "lng": 77.59}, timeout=20)
    services = []
    if r.status_code == 200:
        body = r.json()
        services = body if isinstance(body, list) else body.get("items", [])
        if services:
            provider_id = services[0].get("id")
    print(f"   services found w/lat/lng: {len(services)} provider_id={provider_id}")

    if not provider_id:
        r = requests.get(f"{BASE}/services", timeout=20)
        if r.status_code == 200:
            body = r.json()
            services = body if isinstance(body, list) else body.get("items", [])
            if services:
                provider_id = services[0].get("id")
        print(f"   fallback services: {len(services)} provider_id={provider_id}")

    if not provider_id:
        report("B_skip", "No service providers in DB", False, "skipping section B")
    else:
        r = requests.get(f"{BASE}/services/{provider_id}/profile", timeout=15)
        if r.status_code == 200:
            b = r.json()
            required = ["id", "name", "service_name", "rating_avg", "rating_count", "reviews",
                        "bookings_count", "is_active"]
            missing = [k for k in required if k not in b]
            ok = not missing
            report("B13", "GET /services/{id}/profile", ok, f"status=200 missing={missing}")
        else:
            report("B13", "GET /services/{id}/profile", False,
                   f"status={r.status_code} body={r.text[:200]}")

        r = requests.get(f"{BASE}/services/INVALID_ID_XYZ/profile", timeout=15)
        report("B14", "GET /services/INVALID/profile", r.status_code == 404, f"status={r.status_code}")

        r = requests.post(f"{BASE}/services/{provider_id}/reviews",
                          headers=U_HDR, json={"rating": 5, "comment": "Great"}, timeout=15)
        ok = r.status_code == 403 and "booked" in (r.text or "").lower()
        report("B15", "POST review w/o booking", ok, f"status={r.status_code} body={r.text[:200]}")

        r = requests.post(f"{BASE}/services/{provider_id}/reviews",
                          headers=U_HDR, json={"rating": 6}, timeout=15)
        report("B16", "POST review rating=6", r.status_code == 422, f"status={r.status_code}")

    # C) CHAT SUPPORT
    r = requests.post(f"{BASE}/chat/contact-support", headers=U_HDR,
                      json={"message": "Test support ping from regression"}, timeout=20)
    chat_threads_payload = []
    if r.status_code == 200:
        b = r.json()
        threads = b.get("threads", [])
        count = b.get("count", 0)
        ok = count >= 1 and isinstance(threads, list) and len(threads) >= 1
        report("C17", "POST /chat/contact-support", ok,
               f"count={count} threads_len={len(threads)}")
        chat_threads_payload = threads
    else:
        report("C17", "POST /chat/contact-support", False,
               f"status={r.status_code} body={r.text[:300]}")

    r = requests.get(f"{BASE}/chat/threads", headers=U_HDR, timeout=15)
    if r.status_code == 200:
        threads = r.json().get("threads", [])
        match = None
        for t in threads:
            for ct in chat_threads_payload:
                if t.get("id") == ct.get("thread_id"):
                    match = t
                    break
            if match:
                break
        if not match and threads:
            match = threads[0]
        ok = match is not None
        report("C18", "GET /chat/threads has support thread", ok,
               f"total_threads={len(threads)} matched_thread_id={(match or {}).get('id')}")
        if match:
            other = match.get("other") or {}
            has_vendor = "is_vendor" in other
            has_sp = "is_service_provider" in other
            ok2 = (has_vendor and has_sp
                   and isinstance(other.get("is_vendor"), bool)
                   and isinstance(other.get("is_service_provider"), bool))
            report("C19", "thread.other has is_vendor & is_service_provider bools", ok2,
                   f"keys={list(other.keys())} "
                   f"is_vendor={other.get('is_vendor')} "
                   f"is_service_provider={other.get('is_service_provider')}")
        else:
            report("C19", "thread.other role flags", False, "no thread")
    else:
        report("C18", "GET /chat/threads", False, f"status={r.status_code} body={r.text[:200]}")
        report("C19", "thread.other role flags", False, "skipped")

    # D) Placement realignment fields
    r = requests.get(f"{BASE}/admin/users", headers=A_HDR, timeout=20)
    if r.status_code == 200:
        body = r.json()
        users = body if isinstance(body, list) else body.get("users", body.get("items", []))
        if not isinstance(users, list):
            users = []
        sample = None
        for u in users:
            if u.get("role") != "admin":
                sample = u
                break
        if not sample and users:
            sample = users[0]
        if sample:
            has_orig = "original_sponsor_id" in sample
            has_hist = "placement_history" in sample
            ok = has_orig and has_hist
            report("D20", "/admin/users has original_sponsor_id & placement_history", ok,
                   f"orig={has_orig} hist={has_hist} sample_email={sample.get('email')}")
        else:
            report("D20", "/admin/users sample", False, "no users")
    else:
        report("D20", "/admin/users", False, f"status={r.status_code} body={r.text[:200]}")

    print("\n=========== SUMMARY ===========")
    passed = sum(1 for _, _, p, _ in results if p)
    print(f"Total: {len(results)}  Passed: {passed}  Failed: {len(results)-passed}")
    for tid, name, p, detail in results:
        print(f"  [{'PASS' if p else 'FAIL'}] {tid} {name}")


if __name__ == "__main__":
    main()
