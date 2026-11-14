# Test helper: waits for a fresh OTP row for MOBILE and swaps the hash for a known code (UI E2E only)
import os, sys, time, hashlib
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
from pymongo import MongoClient
db = MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
mobile, code = sys.argv[1], sys.argv[2]
db.otp_codes.delete_many({"mobile": mobile})
for _ in range(240):
    row = db.otp_codes.find_one({"mobile": mobile})
    if row:
        h = hashlib.sha256(f"{row['salt']}:{mobile}:{code}".encode()).hexdigest()
        db.otp_codes.update_one({"_id": row["_id"]}, {"$set": {"otp_hash": h}})
        print("planted", flush=True)
        break
    time.sleep(0.5)
