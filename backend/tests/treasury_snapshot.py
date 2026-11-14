# Admin System Wallet / Treasury snapshot for before/after reconciliation
import os, json, sys, requests
from dotenv import load_dotenv
load_dotenv('/app/frontend/.env')
API = (os.environ.get('EXPO_BACKEND_URL') or os.environ.get('EXPO_PUBLIC_BACKEND_URL')).rstrip('/') + "/api"
tok = requests.post(f"{API}/auth/login", json={"email": "support@slangcart.com", "password": "3)Ywxtic"}, timeout=30).json()
tok = tok.get("token") or tok.get("access_token")
H = {"Authorization": f"Bearer {tok}"}
out = {}
for p in ["/admin/system-wallet", "/admin/system-wallet/breakdown", "/admin/system-wallet/source-breakdown", "/admin/finance/net-worth"]:
    r = requests.get(API + p, headers=H, timeout=60)
    try:
        out[p] = {"status": r.status_code, "body": r.json()}
    except Exception:
        out[p] = {"status": r.status_code, "body": r.text[:200]}
json.dump(out, open(sys.argv[1], "w"), indent=1, sort_keys=True, default=str)
print({k: v["status"] for k, v in out.items()})
