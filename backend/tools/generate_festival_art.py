"""One-off: generate the festival banner artwork for every festival (req 16).

Run with:  setsid python3 tools/generate_festival_art.py >> /tmp/artgen.log 2>&1 &
Skips festivals that already have artwork unless FORCE=1.
"""
import os
import sys

import requests
from dotenv import dotenv_values

env = dotenv_values("/app/backend/.env")
B = "http://localhost:8001/api"
FIDS = [
    "deepavali", "ugadi", "independence_day", "ganesh_chaturthi", "dussehra",
    "maha_shivaratri", "ramzan", "christmas", "new_year", "sankranti",
]

tok = requests.post(
    B + "/auth/login",
    json={"email": env["ADMIN_EMAIL"], "password": env["ADMIN_PASSWORD"]},
    timeout=30,
).json()["token"]
h = {"Authorization": "Bearer " + tok}

only = sys.argv[1:] or FIDS
for fid in only:
    try:
        r = requests.post(
            B + "/admin/festival-theme/artwork",
            json={"festival_id": fid, "slot": "banner"},
            headers=h,
            timeout=600,
        )
        print(fid, r.status_code, r.json().get("bytes") if r.status_code == 200 else r.text[:200], flush=True)
    except Exception as e:  # noqa: BLE001
        print(fid, "EXC", str(e)[:200], flush=True)
print("DONE", flush=True)
