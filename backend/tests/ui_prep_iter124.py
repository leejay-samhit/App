# UI prep for iter124 chat search/deletion UI tests. Usage: python ui_prep_iter124.py setup|cleanup
import os, sys, json, uuid, random, requests, pymongo
from dotenv import load_dotenv
load_dotenv("/app/backend/.env"); load_dotenv("/app/frontend/.env")
API = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/") + "/api"
mdb = pymongo.MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
F = "/tmp/ui124.json"


def phone():
    while True:
        p = random.choice("6789") + "".join(random.choice("0123456789") for _ in range(9))
        if not mdb.users.find_one({"phone": p}):
            return p


if sys.argv[1] == "setup":
    run = uuid.uuid4().hex[:5]
    out = {"run": run, "pfx": f"TEST_ui124{run}"}
    for k, nm in (("me", "Me"), ("friend", "Friend"), ("other", "Fellow"), ("del", "Leaver")):
        email = f"test_ui124_{k}_{run}@example.com"
        r = requests.post(f"{API}/auth/register", json={"name": f"{out['pfx']}{nm}", "email": email,
                                                        "password": "Test@1234", "phone": phone()}, timeout=30)
        r.raise_for_status()
        d = r.json()
        out[k] = {"id": d["user"]["id"], "tok": d["token"], "email": email, "name": f"{out['pfx']}{nm}"}
        u = mdb.users.find_one({"id": d["user"]["id"]})
        print(k, {x: u.get(x) for x in ("status", "phone_verified", "mobile_verified", "is_blocked")})
    h = lambda t: {"Authorization": f"Bearer {t}"}
    q = requests.post(f"{API}/chat/request", json={"to_user_id": out["friend"]["id"]}, headers=h(out["me"]["tok"]))
    q.raise_for_status()
    a = requests.post(f"{API}/chat/request/{q.json()['id']}/accept", headers=h(out["friend"]["tok"]))
    a.raise_for_status()
    out["thread"] = a.json()["thread_id"]
    json.dump(out, open(F, "w"))
    print(json.dumps({k: (v["email"] if isinstance(v, dict) else v) for k, v in out.items()}))
else:
    out = json.load(open(F))
    for k in ("me", "friend", "other", "del"):
        uid = out[k]["id"]
        mdb.chat_requests.delete_many({"$or": [{"from_user_id": uid}, {"to_user_id": uid}]})
        mdb.chat_threads.delete_many({"participants": uid})
        mdb.chat_blocks.delete_many({"blocker_id": uid})
        tids = [t["id"] for t in mdb.tickets.find({"user_id": uid}, {"id": 1})]
        mdb.ticket_messages.delete_many({"ticket_id": {"$in": tids}})
        mdb.tickets.delete_many({"id": {"$in": tids}})
        mdb.notifications.delete_many({"user_id": uid})
        mdb.users.delete_one({"id": uid})
    print("cleaned")
