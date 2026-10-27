"""Iter102 — FIX 4/4b over HTTP: service reviews after contact (member free
reveal, free-account paid reveal, booking), contacted_count, visit charges via
PATCH /api/service/me, application mirror, non-provider refused.

Run:  python3 tests/test_iter102_service_reviews_visit_charge.py
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db import db  # noqa: E402
from core.security import hash_password  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(f"{'PASS' if ok else 'FAIL'} · {name}" + (f" — {extra}" if extra else ""))


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
PW = "Test@1234"


async def login(c, email, pw=PW):
    r = await c.post(f"{BASE}/auth/login", json={"email": email, "password": pw})
    return {"Authorization": "Bearer " + r.json().get("token", "")}


async def main():
    ts = datetime.now(timezone.utc).isoformat()
    pid = f"TEST_sp_{uuid.uuid4().hex[:6]}"
    pemail = f"{pid.lower()}@test.com"
    free_id = f"TEST_free_{uuid.uuid4().hex[:6]}"
    free_email = f"{free_id.lower()}@test.com"
    book_id = f"TEST_book_{uuid.uuid4().hex[:6]}"
    book_email = f"{book_id.lower()}@test.com"
    base_user = {"role": "user", "password_hash": hash_password(PW), "created_at": ts, "is_approved": True,
                 "status": "active", "email_verified": True}
    await db.users.insert_many([
        {**base_user, "id": pid, "name": "TEST Plumber", "email": pemail, "phone": "9999900011",
         "is_service_provider": True, "service_status": "approved", "service_name": "Plumbing",
         "service_category": "Plumbing", "service_pincode": "517644", "service_charge": 100.0,
         "registration_paid": True, "referral_code": f"S{uuid.uuid4().hex[:6].upper()}"},
        {**base_user, "id": free_id, "name": "TEST Free", "email": free_email, "phone": "9999900012",
         "registration_paid": False, "referral_code": f"F{uuid.uuid4().hex[:6].upper()}"},
        {**base_user, "id": book_id, "name": "TEST Booker", "email": book_email, "phone": "9999900013",
         "registration_paid": False, "referral_code": f"B{uuid.uuid4().hex[:6].upper()}"},
    ])
    await db.service_applications.insert_one({"id": f"APP-{pid}", "user_id": pid, "status": "approved", "charge": 100.0})
    buyer = await db.users.find_one({"email": "testbuyer@test.com"}, {"_id": 0, "id": 1, "registration_paid": 1})
    try:
        async with httpx.AsyncClient(timeout=90) as c:
            # member (free reveal) — flip testbuyer to member temporarily
            await db.users.update_one({"id": buyer["id"]}, {"$set": {"registration_paid": True}})
            mh = await login(c, "testbuyer@test.com")
            fh = await login(c, free_email)
            bh = await login(c, book_email)
            ph = await login(c, pemail)
            check("seeded logins work", all(len(h["Authorization"]) > 20 for h in (mh, fh, bh, ph)))

            for label, h in (("member", mh), ("free", fh), ("booker", bh)):
                r = await c.post(f"{BASE}/services/{pid}/reviews", headers=h, json={"rating": 4, "comment": "x"})
                check(f"{label}: review refused before contact (403)", r.status_code == 403, f"{r.status_code} {r.text[:80]}")

            await db.phone_reveal_invoices.insert_many([
                {"id": str(uuid.uuid4()), "user_id": buyer["id"], "provider_id": pid, "fee": 0.0, "gst": 0.0,
                 "total": 0.0, "status": "free_member", "created_at": ts},
                {"id": str(uuid.uuid4()), "user_id": free_id, "provider_id": pid, "fee": 1.0, "gst": 0.18,
                 "total": 1.18, "status": "paid", "created_at": ts},
            ])
            await db.service_bookings.insert_one({"id": f"TESTBK-{uuid.uuid4().hex[:6]}", "customer_id": book_id,
                                                  "provider_id": pid, "status": "completed", "created_at": ts})
            prof = (await c.get(f"{BASE}/services/{pid}/profile", headers=fh)).json()
            check("profile exposes can_review/contacted_count/visit_charge",
                  all(k in prof for k in ("can_review", "contacted_count", "visit_charge")), str({k: prof.get(k) for k in ("can_review", "contacted_count", "visit_charge")}))
            check("contacted_count = 3 distinct (2 reveals + 1 booker)", prof.get("contacted_count") == 3, str(prof.get("contacted_count")))
            check("visit_charge = 100", abs(float(prof.get("visit_charge") or 0) - 100) < 0.01, str(prof.get("visit_charge")))
            for label, h in (("member", mh), ("free-paid", fh), ("booker", bh)):
                p = (await c.get(f"{BASE}/services/{pid}/profile", headers=h)).json()
                check(f"{label}: can_review true", p.get("can_review") is True, str(p.get("can_review")))
                r = await c.post(f"{BASE}/services/{pid}/reviews", headers=h, json={"rating": 5, "comment": f"good {label}"})
                check(f"{label}: review posts (200)", r.status_code == 200, f"{r.status_code} {r.text[:100]}")
            p = (await c.get(f"{BASE}/services/{pid}/profile", headers=fh)).json()
            check("rating_count = 3", p.get("rating_count") == 3, str(p.get("rating_count")))
            # duplicate reveal row for same customer must not double count
            await db.phone_reveal_invoices.insert_one({"id": str(uuid.uuid4()), "user_id": free_id, "provider_id": pid,
                                                       "fee": 1.0, "gst": 0.18, "total": 1.18, "status": "paid", "created_at": ts})
            p = (await c.get(f"{BASE}/services/{pid}/profile", headers=fh)).json()
            check("contacted_count stays 3 with a repeat reveal (distinct)", p.get("contacted_count") == 3, str(p.get("contacted_count")))

            # visit charges via HTTP
            r = await c.patch(f"{BASE}/service/me", headers=ph, json={"visit_charge": 250})
            check("provider PATCH visit_charge 250 → 200", r.status_code == 200, f"{r.status_code} {r.text[:100]}")
            u = await db.users.find_one({"id": pid}, {"_id": 0, "service_charge": 1})
            check("users.service_charge = 250", abs(float(u.get("service_charge") or 0) - 250) < 0.01, str(u))
            a = await db.service_applications.find_one({"user_id": pid}, {"_id": 0, "charge": 1})
            check("service_application.charge mirrored = 250", abs(float(a.get("charge") or 0) - 250) < 0.01, str(a))
            p = (await c.get(f"{BASE}/services/{pid}/profile", headers=fh)).json()
            check("public profile visit_charge = 250", abs(float(p.get("visit_charge") or 0) - 250) < 0.01, str(p.get("visit_charge")))
            r = await c.patch(f"{BASE}/service/me", headers=ph, json={"visit_charge": 0})
            p = (await c.get(f"{BASE}/services/{pid}/profile", headers=fh)).json()
            check("visit_charge 0 accepted (on request)", r.status_code == 200 and float(p.get("visit_charge") or 0) == 0, f"{r.status_code} {p.get('visit_charge')}")
            r = await c.patch(f"{BASE}/service/me", headers=ph, json={"visit_charge": -5})
            check("negative visit_charge rejected (422)", r.status_code == 422, str(r.status_code))
            vh = await login(c, "testvendor@test.com")
            r = await c.patch(f"{BASE}/service/me", headers=vh, json={"visit_charge": 250})
            check("non-provider refused (403)", r.status_code == 403, f"{r.status_code} {r.text[:80]}")
    finally:
        await db.users.update_one({"id": buyer["id"]}, {"$set": {"registration_paid": bool(buyer.get("registration_paid"))}})
        await db.users.delete_many({"id": {"$in": [pid, free_id, book_id]}})
        await db.service_applications.delete_many({"user_id": pid})
        await db.phone_reveal_invoices.delete_many({"provider_id": pid})
        await db.service_bookings.delete_many({"provider_id": pid})
        await db.service_reviews.delete_many({"provider_id": pid})
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
