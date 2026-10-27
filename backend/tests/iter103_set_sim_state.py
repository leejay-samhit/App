# Iter103 helper — set testbuyer's SIM state via the real challenge→verify path. Usage: python iter103_set_sim_state.py SIM_ABSENT|SIM_PRESENT
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
B = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") + "/api"
state = sys.argv[1]
t = requests.post(f"{B}/auth/login", json={"email": "testbuyer@test.com", "password": "Test@1234"}).json()["token"]
h = {"Authorization": f"Bearer {t}"}
for _ in range(2):  # second pass clears revalidate if the fingerprint moved
    ch = requests.post(f"{B}/sim-binding/challenge", headers=h, json={}).json()
    mcc, mnc = ("404", "45") if state == "SIM_PRESENT" else ("", "")
    r = requests.post(f"{B}/sim-binding/verify", headers=h, json={
        "challenge_id": ch["challenge_id"], "nonce": ch["nonce"], "sim_state": state, "slot_count": 1 if mcc else 0,
        "mcc": mcc, "mnc": mnc, "platform": "android", "os_version": "14", "app_version": "1.0"})
st = r.json()
print(state, "level=", st["level"], "meets=", st["meets_requirement"], "enforce=", st["enforce_chat"])
th = requests.get(f"{B}/chat/threads", headers=h).json()
tl = th if isinstance(th, list) else th.get("threads", th.get("items", []))
print("thread:", tl[0]["id"] if tl else None)
