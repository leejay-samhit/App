"""100K-user load seeder using REAL API endpoints (option 5a).

Flow per user:
  1. POST /api/auth/register           (random name/email/phone + optional ref)
  2. POST /api/auth/login              (get token)
  3. POST /api/payment/register-fee    (legacy/mock mode = OK)
  4. POST /api/admin/approvals/{uid}/approve   (admin path)

Mix (defaults):
  15% no-ref  | 15% EARN-code | 70% with-ref (random existing user)

Concurrency: SEED_CONCURRENCY env (default 20).
Throttle:    SEED_DELAY_MS env (default 0).

Tracks every batch in /tmp/seed_progress.txt and final ledger snapshot in
/tmp/seed_done.txt.

ENV inputs:
  SEED_TARGET   = 100000   (number of users to seed)
  SEED_BATCH    = 500      (progress checkpoint frequency)
  SEED_CONC     = 20
  SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD (defaults to admin@app.com / Admin@123)
"""
import asyncio
import os
import random
import secrets
import string
import sys
import time
from typing import List, Optional

import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BACKEND = os.environ.get("SEED_BACKEND", "http://localhost:8001")
TARGET = int(os.environ.get("SEED_TARGET", "100000"))
BATCH = int(os.environ.get("SEED_BATCH", "500"))
CONCURRENCY = int(os.environ.get("SEED_CONC", "20"))
DELAY_MS = int(os.environ.get("SEED_DELAY_MS", "0"))
ADMIN_EMAIL = os.environ.get("SEED_ADMIN_EMAIL", "admin@app.com")
ADMIN_PASS = os.environ.get("SEED_ADMIN_PASSWORD", "Admin@123")
PROGRESS_FILE = "/tmp/seed_progress.txt"
DONE_FILE = "/tmp/seed_done.txt"

MIX_NO_REF = 0.15
MIX_EARN = 0.15
MIX_WITH_REF = 0.70

FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Reyansh", "Krishna",
    "Ishaan", "Shaurya", "Atharva", "Advik", "Pranav", "Rudra", "Aryan",
    "Saanvi", "Aanya", "Aadhya", "Ananya", "Pari", "Anika", "Navya", "Diya",
    "Riya", "Sneha", "Pooja", "Nisha", "Kavya", "Tara", "Mira", "Zara",
    "Rohan", "Karan", "Amit", "Vikram", "Sanjay", "Rajesh", "Pradeep",
    "Anand", "Sahil", "Yash", "Hardik", "Tanmay", "Aditi", "Ishita",
    "Khushi", "Megha", "Priya", "Shreya", "Tanvi", "Vidhi",
]
LAST_NAMES = [
    "Sharma", "Verma", "Gupta", "Singh", "Kumar", "Patel", "Reddy",
    "Nair", "Iyer", "Menon", "Kapoor", "Khanna", "Malhotra", "Bhatia",
    "Chopra", "Joshi", "Mehta", "Shah", "Desai", "Pillai", "Naidu",
    "Pandey", "Mishra", "Tiwari", "Agarwal", "Bansal", "Goel", "Saxena",
]


def rand_name() -> str:
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def rand_phone() -> str:
    return "9" + "".join(random.choices(string.digits, k=9))


def rand_email(uid: str) -> str:
    return f"loadtest_{uid}@seeduser.app"


def write_progress(line: str) -> None:
    try:
        with open(PROGRESS_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


async def admin_login(client: httpx.AsyncClient) -> str:
    r = await client.post(
        f"{BACKEND}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["token"]


async def fetch_earn_code(db) -> Optional[str]:
    """Returns the admin's referral_code (used as the 'EARN' code)."""
    a = await db.users.find_one({"email": ADMIN_EMAIL.lower()}, {"referral_code": 1, "_id": 0})
    return (a or {}).get("referral_code")


async def fetch_user_codes(db, limit: int = 5000) -> List[str]:
    """Pool of existing user referral_codes to use as sponsor for with-ref signups."""
    codes = []
    async for u in db.users.find(
        {"role": "user", "registration_paid": True, "approval_status": "approved"},
        {"referral_code": 1, "_id": 0},
    ).limit(limit):
        if u.get("referral_code"):
            codes.append(u["referral_code"])
    return codes


async def seed_one(
    client: httpx.AsyncClient,
    admin_token: str,
    ref_code: Optional[str],
    pool: List[str],
    sem: asyncio.Semaphore,
    counters: dict,
) -> None:
    async with sem:
        uid = secrets.token_hex(4)
        email = rand_email(uid)
        name = rand_name()
        phone = rand_phone()
        try:
            # 1. register
            r = await client.post(
                f"{BACKEND}/api/auth/register",
                json={
                    "name": name,
                    "email": email,
                    "password": "Seed@1234",
                    "phone": phone,
                    "referral_code": ref_code,
                },
                timeout=20,
            )
            if r.status_code != 200:
                counters["fail_register"] += 1
                return
            user_id = r.json().get("user", {}).get("id") or r.json().get("id")
            user_token = r.json().get("token")
            if not user_token:
                # fallback login
                lr = await client.post(
                    f"{BACKEND}/api/auth/login",
                    json={"email": email, "password": "Seed@1234"}, timeout=15,
                )
                user_token = lr.json().get("token")
            if not user_id or not user_token:
                counters["fail_register"] += 1
                return

            # 2. pay registration fee
            r2 = await client.post(
                f"{BACKEND}/api/payment/register-fee",
                headers={"Authorization": f"Bearer {user_token}"},
                timeout=20,
            )
            if r2.status_code != 200:
                counters["fail_pay"] += 1
                return

            # 3. admin approval
            r3 = await client.post(
                f"{BACKEND}/api/admin/approvals/{user_id}/approve",
                headers={"Authorization": f"Bearer {admin_token}"},
                timeout=30,
            )
            if r3.status_code != 200:
                counters["fail_approve"] += 1
                return

            # Capture the new user's referral_code so deeper users can sponsor under them
            new_code = r.json().get("user", {}).get("referral_code")
            if new_code and len(pool) < 20000:
                pool.append(new_code)
            counters["ok"] += 1
        except Exception as e:
            counters["exception"] += 1
            counters["last_err"] = str(e)[:120]
        finally:
            if DELAY_MS > 0:
                await asyncio.sleep(DELAY_MS / 1000)


async def main():
    print(f"[seed] target={TARGET} concurrency={CONCURRENCY} backend={BACKEND}")
    open(PROGRESS_FILE, "w").close()

    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]

    # Bootstrap pool
    earn_code = await fetch_earn_code(db)
    pool = await fetch_user_codes(db, limit=5000)
    print(f"[seed] EARN code = {earn_code}, sponsor pool = {len(pool)} codes")
    if not pool and not earn_code:
        print("[seed] No sponsors available — aborting.")
        return

    async with httpx.AsyncClient(http2=False, limits=httpx.Limits(max_connections=CONCURRENCY * 2)) as client:
        admin_token = await admin_login(client)
        sem = asyncio.Semaphore(CONCURRENCY)
        counters = {"ok": 0, "fail_register": 0, "fail_pay": 0, "fail_approve": 0, "exception": 0, "last_err": ""}

        t0 = time.time()
        batch_tasks: list = []
        for i in range(TARGET):
            roll = random.random()
            if roll < MIX_NO_REF:
                code = None
            elif roll < MIX_NO_REF + MIX_EARN:
                code = earn_code
            else:
                code = random.choice(pool) if pool else earn_code

            batch_tasks.append(seed_one(client, admin_token, code, pool, sem, counters))

            # Flush every BATCH starts (not awaits) to bound memory.
            if len(batch_tasks) >= BATCH:
                await asyncio.gather(*batch_tasks, return_exceptions=True)
                batch_tasks = []
                el = time.time() - t0
                rate = counters["ok"] / max(0.1, el)
                line = (
                    f"[{int(el)}s] ok={counters['ok']} "
                    f"fail_reg={counters['fail_register']} "
                    f"fail_pay={counters['fail_pay']} "
                    f"fail_app={counters['fail_approve']} "
                    f"exc={counters['exception']} "
                    f"rate={rate:.1f}/s pool={len(pool)} target={i+1}"
                )
                print(line, flush=True)
                write_progress(line)

        # Drain remainder
        if batch_tasks:
            await asyncio.gather(*batch_tasks, return_exceptions=True)

    el = time.time() - t0
    summary = (
        f"DONE in {int(el)}s | ok={counters['ok']} | fails: reg={counters['fail_register']} "
        f"pay={counters['fail_pay']} app={counters['fail_approve']} exc={counters['exception']} "
        f"| last_err={counters['last_err']}"
    )
    print(summary, flush=True)
    write_progress(summary)
    with open(DONE_FILE, "w") as f:
        f.write(summary + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
