# Iter103 regression — while testbuyer is SIM_ABSENT (chat-blocked), shopping/checkout/cancel/wallet/returns must work.
import os
import subprocess
import sys

import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
B = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") + "/api"
HERE = os.path.dirname(__file__)


def main():
    subprocess.run([sys.executable, os.path.join(HERE, "iter103_set_sim_state.py"), "SIM_ABSENT"], check=True)
    t = requests.post(f"{B}/auth/login", json={"email": "testbuyer@test.com", "password": "Test@1234"}).json()["token"]
    h = {"Authorization": f"Bearer {t}"}
    res = {}
    try:
        res["chat_blocked"] = requests.post(f"{B}/chat/contact-support", headers=h, json={}).status_code
        pl = []
        for off in (0, 100, 200):
            prods = requests.get(f"{B}/products", headers=h, params={"limit": 100, "offset": off}).json()
            pl += prods.get("items") or []
        pick = next((p for p in pl if (p.get("stock") or 0) > 3 and p.get("cod_available") is not False
                     and not p.get("variants") and not str(p.get("id")).startswith("rchg")
                     and p.get("product_type", "physical") in ("physical", None, "")), None)
        if not pick:
            print("NO COD-eligible product found among", len(pl))
            return
        res["product"] = pick and pick["id"]
        requests.post(f"{B}/cart/clear", headers=h)
        r = requests.post(f"{B}/cart/add", headers=h, json={"product_id": pick["id"], "qty": 1})
        res["cart_add"] = r.status_code
        addr = {"name": "TEST Buyer", "phone": "9876543210", "line1": "TEST 1 MG Road", "city": "Bengaluru",
                "state": "Karnataka", "pincode": "560001"}
        r = requests.post(f"{B}/orders/checkout", headers=h, json={"payment_method": "cod", "shipping_address": addr})
        res["checkout_cod"] = (r.status_code, r.text[:160] if r.status_code != 200 else "")
        body = r.json() if r.status_code == 200 else {}
        oids = [o.get("id") for o in (body.get("orders") or [])] or [body.get("id") or body.get("order_id")]
        oids = [o for o in oids if o]
        mine = requests.get(f"{B}/orders/me", headers=h).json()
        ml = mine if isinstance(mine, list) else mine.get("orders") or mine.get("items") or []
        res["order_visible"] = bool(oids) and any(o.get("id") in oids for o in ml)
        for oid in oids:
            res[f"cancel_{oid[:6]}"] = requests.post(f"{B}/orders/{oid}/cancel", headers=h, json={"reason": "TEST iter103"}).status_code
        res["wallet"] = requests.get(f"{B}/wallet", headers=h).status_code
        res["returns_me"] = requests.get(f"{B}/returns/me", headers=h).status_code
    finally:
        requests.post(f"{B}/cart/clear", headers=h)
        subprocess.run([sys.executable, os.path.join(HERE, "iter103_set_sim_state.py"), "SIM_PRESENT"], check=True)
    print("REGRESSION:", res)


if __name__ == "__main__":
    main()
