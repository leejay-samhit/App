# Iter-120 UI helper: mint a brand-new mobile OTP account (seeded code, no WhatsApp send) and print token json
import os, hashlib, secrets, json, sys
from datetime import datetime, timezone, timedelta
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('/app/frontend/.env'); load_dotenv('/app/backend/.env')
API = (os.environ.get('EXPO_BACKEND_URL') or os.environ['EXPO_PUBLIC_BACKEND_URL']).rstrip('/') + "/api"
db = MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
mobile = sys.argv[1]
salt = secrets.token_hex(16); otp = "314159"; now = datetime.now(timezone.utc)
db.otp_codes.delete_many({"mobile": mobile})
db.otp_codes.insert_one({"mobile": mobile, "otp_hash": hashlib.sha256(f"{salt}:{mobile}:{otp}".encode()).hexdigest(),
                         "salt": salt, "purpose": "login", "attempts": 0, "consumed": False,
                         "created_at": (now - timedelta(seconds=90)).isoformat(),
                         "expires_at": (now + timedelta(seconds=200)).isoformat()})
r = requests.post(f"{API}/auth/otp/verify", json={"mobile": mobile, "otp": otp}, timeout=30)
j = r.json()
out = {"status": r.status_code, "token": j.get("token"), "refresh": j.get("refresh_token"),
       "id": j.get("user", {}).get("id"), "created": j.get("created"), "needs_profile": j.get("needs_profile")}
json.dump(out, open(f"/tmp/ui_{mobile}.json", "w"))
print({k: out[k] for k in ("status", "id", "created", "needs_profile")})
