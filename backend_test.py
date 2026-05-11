"""
Backend tests for P1 endpoints in products_extended.py
- Helpful vote toggle on reviews
- Reviews list with helpful_count + voted_helpful (no leaked voters)
- Vendor pending Q&A list (with admin fallback)
- Wishlist round-trip regression
"""
import os
import sys
import json
import requests

BASE = "https://network-pay-1.preview.emergentagent.com/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"
USER_EMAIL = "testuser@app.com"
USER_PASS = "Test@123"

results = []  # (name, ok, detail)


def log(name, ok, detail=""):
    results.append((name, ok, detail))
    flag = "PASS" if ok else "FAIL"
    print(f"[{flag}] {name}  {detail}")


def login(email, pwd):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pwd}, timeout=30)
    r.raise_for_status()
    j = r.json()
    return j.get("token") or j.get("access_token") or j["token"]


def hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def main():
    print("== LOGIN ==")
    admin_tok = login(ADMIN_EMAIL, ADMIN_PASS)
    user_tok = login(USER_EMAIL, USER_PASS)
    log("login admin", bool(admin_tok))
    log("login test user", bool(user_tok))

    # 0. Create product as admin
    print("\n== SETUP: create product ==")
    payload = {
        "name": "P1 Test - Helpful Vote",
        "price": 100,
        "image_url": "data:image/jpeg;base64,A==",
        "stock": 5,
        "is_published": True,
        "category": "Test",
    }
    r = requests.post(f"{BASE}/admin/products", json=payload, headers=hdr(admin_tok), timeout=30)
    if r.status_code != 200:
        print("Product create failed:", r.status_code, r.text[:500])
        sys.exit(1)
    prod = r.json()
    pid = prod.get("id") or prod.get("product", {}).get("id")
    if not pid:
        print("No product id in response:", prod)
        sys.exit(1)
    log("admin POST /admin/products", True, f"pid={pid}")

    try:
        # 1. Test user posts a review (their OWN review)
        print("\n== SETUP: post reviews ==")
        r = requests.post(f"{BASE}/products/{pid}/reviews",
                          json={"rating": 5, "title": "Great", "body": "Loved it"},
                          headers=hdr(user_tok), timeout=30)
        log("user POST review", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
        user_review_id = r.json().get("id") if r.status_code == 200 else None

        # Admin posts second review on same product
        r = requests.post(f"{BASE}/products/{pid}/reviews",
                          json={"rating": 4, "title": "Decent", "body": "Admin's take"},
                          headers=hdr(admin_tok), timeout=30)
        log("admin POST review", r.status_code == 200, f"status={r.status_code}")
        admin_review_id = r.json().get("id") if r.status_code == 200 else None

        # =============== 1. POST /products/{pid}/reviews/{rid}/helpful ===============
        print("\n== TEST 1: helpful vote toggle ==")

        # i. Admin votes on Test user's review -> 200 voted_helpful=true count=1
        r = requests.post(f"{BASE}/products/{pid}/reviews/{user_review_id}/helpful",
                          headers=hdr(admin_tok), timeout=30)
        ok = (r.status_code == 200 and r.json().get("voted_helpful") is True
              and r.json().get("helpful_count") == 1)
        log("1.i admin toggle helpful (ON)", ok, f"status={r.status_code} resp={r.text[:200]}")
        sample_vote_on = r.text

        # ii. Admin votes again on same -> toggle off
        r = requests.post(f"{BASE}/products/{pid}/reviews/{user_review_id}/helpful",
                          headers=hdr(admin_tok), timeout=30)
        ok = (r.status_code == 200 and r.json().get("voted_helpful") is False
              and r.json().get("helpful_count") == 0)
        log("1.ii admin toggle helpful (OFF)", ok, f"status={r.status_code} resp={r.text[:200]}")
        sample_vote_off = r.text

        # Re-vote ON for downstream tests
        r = requests.post(f"{BASE}/products/{pid}/reviews/{user_review_id}/helpful",
                          headers=hdr(admin_tok), timeout=30)
        log("1.x re-vote ON for downstream", r.status_code == 200 and r.json().get("helpful_count") == 1,
            f"status={r.status_code}")

        # iii. Self-vote prevention
        r = requests.post(f"{BASE}/products/{pid}/reviews/{user_review_id}/helpful",
                          headers=hdr(user_tok), timeout=30)
        ok = (r.status_code == 400 and "your own review" in r.text.lower())
        log("1.iii self-vote prevention (400)", ok, f"status={r.status_code} body={r.text[:200]}")

        # iv. 404 non-existent review
        r = requests.post(f"{BASE}/products/{pid}/reviews/nonexistent-rid-123/helpful",
                          headers=hdr(admin_tok), timeout=30)
        log("1.iv 404 non-existent review", r.status_code == 404, f"status={r.status_code}")

        # v. Unauth 401
        r = requests.post(f"{BASE}/products/{pid}/reviews/{user_review_id}/helpful", timeout=30)
        log("1.v unauth 401", r.status_code in (401, 403), f"status={r.status_code}")

        # =============== 2. GET /products/{pid}/reviews ===============
        print("\n== TEST 2: GET reviews with helpful_count/voted_helpful ==")

        # Test user GETs reviews
        r = requests.get(f"{BASE}/products/{pid}/reviews", headers=hdr(user_tok), timeout=30)
        ok = r.status_code == 200
        log("2.a user GET /reviews", ok, f"status={r.status_code}")
        leak_found = False
        user_rev_in_list = None
        if ok:
            data = r.json()
            for rev in data.get("reviews", []):
                if "helpful_voters" in rev:
                    leak_found = True
                if rev.get("id") == user_review_id:
                    user_rev_in_list = rev
        ok2 = (user_rev_in_list is not None and user_rev_in_list.get("helpful_count") == 1
               and user_rev_in_list.get("voted_helpful") is False)
        log("2.b user sees helpful_count=1 voted=false", ok2,
            f"rev={user_rev_in_list}")
        log("2.c helpful_voters NOT leaked (user view)", not leak_found, f"leak={leak_found}")

        # Admin GETs reviews
        r = requests.get(f"{BASE}/products/{pid}/reviews", headers=hdr(admin_tok), timeout=30)
        ok = r.status_code == 200
        admin_rev_view = None
        leak_admin = False
        if ok:
            for rev in r.json().get("reviews", []):
                if "helpful_voters" in rev:
                    leak_admin = True
                if rev.get("id") == user_review_id:
                    admin_rev_view = rev
        ok2 = (admin_rev_view is not None and admin_rev_view.get("voted_helpful") is True
               and admin_rev_view.get("helpful_count") == 1)
        log("2.d admin sees voted_helpful=true", ok2, f"rev={admin_rev_view}")
        log("2.e helpful_voters NOT leaked (admin view)", not leak_admin)

        # =============== 3. GET /vendor/me/questions ===============
        print("\n== TEST 3: vendor pending Q&A ==")

        # Test user posts a question
        r = requests.post(f"{BASE}/products/{pid}/questions",
                          json={"text": "Q1 - battery life?"},
                          headers=hdr(user_tok), timeout=30)
        ok = r.status_code == 200
        qid = r.json().get("id") if ok else None
        log("3.a user POST /questions", ok, f"status={r.status_code} qid={qid}")

        # Admin GETs vendor questions (admin allowed per code, sees ALL questions since qry={})
        r = requests.get(f"{BASE}/vendor/me/questions", headers=hdr(admin_tok), timeout=30)
        ok = r.status_code == 200
        log("3.b admin GET /vendor/me/questions", ok, f"status={r.status_code}")
        sample_vendor_q = r.text[:500]
        target_item = None
        if ok:
            data = r.json()
            for it in data.get("items", []):
                if it.get("id") == qid:
                    target_item = it
                    break
            ok2 = (data.get("pending_count", 0) >= 1
                   and target_item is not None
                   and "product_name" in target_item
                   and "product_image" in target_item
                   and target_item.get("answered") is False)
            log("3.c pending_count>=1 and item has product_name/answered:false", ok2,
                f"pending={data.get('pending_count')} item={target_item}")

        # Admin answers the question
        r = requests.post(f"{BASE}/products/{pid}/questions/{qid}/answer",
                          json={"text": "A1 - 5000mAh"},
                          headers=hdr(admin_tok), timeout=30)
        log("3.d admin POST answer", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")

        # GET again - should show answered:true, sorted AFTER pending
        r = requests.get(f"{BASE}/vendor/me/questions", headers=hdr(admin_tok), timeout=30)
        ok = r.status_code == 200
        if ok:
            data = r.json()
            # find our item
            answered_item = None
            answered_idx = -1
            for i, it in enumerate(data.get("items", [])):
                if it.get("id") == qid:
                    answered_item = it
                    answered_idx = i
                    break
            unanswered_after = data.get("pending_count", 0)
            # Verify it's now answered and positioned after unanswered ones
            ok2 = (answered_item is not None and answered_item.get("answered") is True)
            log("3.e question now answered:true", ok2, f"item={answered_item}")
            # Position: it should come AFTER unanswered items
            ok3 = (answered_idx >= unanswered_after)
            log("3.f answered sorted after pending", ok3,
                f"idx={answered_idx} pending_count={unanswered_after}")

        # 403: normal user (testuser is approved customer, role=user) hits /vendor/me/questions
        r = requests.get(f"{BASE}/vendor/me/questions", headers=hdr(user_tok), timeout=30)
        log("3.g normal user gets 403", r.status_code == 403, f"status={r.status_code} body={r.text[:200]}")

        # =============== 4. Wishlist regression ===============
        print("\n== TEST 4: wishlist round-trip ==")

        # First save
        r = requests.post(f"{BASE}/products/{pid}/save", headers=hdr(user_tok), timeout=30)
        ok = (r.status_code == 200 and r.json().get("saved") is True)
        log("4.a POST /save -> saved:true", ok, f"status={r.status_code} body={r.text[:200]}")

        # GET wishlist contains pid
        r = requests.get(f"{BASE}/me/wishlist", headers=hdr(user_tok), timeout=30)
        contains = False
        if r.status_code == 200:
            for it in r.json().get("items", []):
                if it.get("id") == pid:
                    contains = True
                    break
        log("4.b GET /me/wishlist contains pid", contains, f"status={r.status_code}")

        # Toggle off
        r = requests.post(f"{BASE}/products/{pid}/save", headers=hdr(user_tok), timeout=30)
        ok = (r.status_code == 200 and r.json().get("saved") is False)
        log("4.c POST /save again -> saved:false", ok, f"status={r.status_code} body={r.text[:200]}")

        # GET wishlist does NOT contain pid
        r = requests.get(f"{BASE}/me/wishlist", headers=hdr(user_tok), timeout=30)
        contains = False
        if r.status_code == 200:
            for it in r.json().get("items", []):
                if it.get("id") == pid:
                    contains = True
                    break
        log("4.d GET /me/wishlist no longer contains pid", not contains, f"status={r.status_code}")

        # ---- print samples ----
        print("\n== SAMPLES ==")
        print("Sample helpful-vote ON:", sample_vote_on)
        print("Sample helpful-vote OFF:", sample_vote_off)
        print("Sample /vendor/me/questions:", sample_vendor_q)

    finally:
        # Cleanup product
        print("\n== CLEANUP ==")
        r = requests.delete(f"{BASE}/admin/products/{pid}", headers=hdr(admin_tok), timeout=30)
        log("cleanup DELETE product", r.status_code == 200, f"status={r.status_code}")

    # Summary
    print("\n========== SUMMARY ==========")
    passes = sum(1 for _, ok, _ in results if ok)
    fails = [(n, d) for n, ok, d in results if not ok]
    print(f"PASS {passes}/{len(results)}")
    for n, d in fails:
        print(f"  FAIL: {n} -> {d}")
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
