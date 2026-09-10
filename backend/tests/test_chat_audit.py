"""E2E: chat audit — deleted message recovery + txt export (super admin only)."""
import requests

B = "https://vendor-network-app-1.preview.emergentagent.com/api"
ADMIN = ("support@slangcart.com", "3)Ywxtic")
A = ("testbuyer@test.com", "Test@1234")
BOB = ("testbuyer2@test.com", "Test@1234")
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="


def login(c):
    r = requests.post(B + "/auth/login", json={"email": c[0], "password": c[1]}, timeout=30)
    r.raise_for_status()
    return r.json()["token"]


def h(t):
    return {"Authorization": "Bearer " + t}


at, ta, tb = login(ADMIN), login(A), login(BOB)
print("logins ok")

me_a = requests.get(B + "/auth/me", headers=h(ta), timeout=30).json()
me_b = requests.get(B + "/auth/me", headers=h(tb), timeout=30).json()
print("A:", me_a["name"], me_a["id"], "| B:", me_b["name"], me_b["id"])
req = requests.post(B + "/chat/request", json={"to_user_id": me_b["id"], "message": "audit test"}, headers=h(ta), timeout=30)
print("request:", req.status_code, req.text[:120])
if req.status_code == 200 and req.json().get("status") == "pending":
    acc = requests.post(B + f"/chat/request/{req.json()['id']}/accept", headers=h(tb), timeout=30)
    print("accept:", acc.status_code, acc.text[:120])
    thread = acc.json()["thread_id"]
else:
    thread = requests.get(B + "/chat/search", params={"code": me_b["referral_code"]}, headers=h(ta), timeout=30).json()["thread_id"]
print("thread:", thread)
m1 = requests.post(B + f"/chat/{thread}/messages", json={"text": "AUDIT probe: is the saree available?"}, headers=h(ta), timeout=30)
print("alice msg", m1.status_code)
m1id = m1.json()["id"]
m2 = requests.post(B + f"/chat/{thread}/messages", json={"text": "AUDIT probe reply: yes it is", "reply_to_id": m1id}, headers=h(tb), timeout=30).json()
m3 = requests.post(B + f"/chat/{thread}/messages", json={"text": "", "image_data_url": PNG}, headers=h(ta), timeout=30).json()
m4 = requests.post(B + f"/chat/{thread}/messages", json={"text": "AUDIT probe: THIS WILL BE DELETED - secret plan"}, headers=h(ta), timeout=30).json()
print("4 messages posted")

d = requests.delete(B + f"/chat/messages/{m4['id']}", headers=h(ta), timeout=30)
print("delete own msg:", d.status_code)

# user view must NOT show the deleted text
uview = requests.get(B + f"/chat/{thread}/messages", params={"limit": 10}, headers=h(ta), timeout=30).json()["messages"]
gone = next(m for m in uview if m["id"] == m4["id"])
print("user sees deleted text:", repr(gone.get("text")), "deleted flag:", gone.get("deleted"))
assert gone.get("text") == "" and gone.get("deleted") is True

# ---- audit: non-super-admin blocked
r = requests.get(B + "/admin/chat-audit/threads", headers=h(ta), timeout=30)
print("normal user -> threads:", r.status_code)
assert r.status_code in (401, 403)

# ---- audit thread list
r = requests.get(B + "/admin/chat-audit/threads", params={"q": me_b["email"]}, headers=h(at), timeout=60)
print("list:", r.status_code, r.json().get("total"))
r.raise_for_status()
th = r.json()["threads"]
print("first thread:", {k: v for k, v in th[0].items() if k != "participants"})
print("parties:", [(p["name"], p["email"], p["role"]) for p in th[0]["participants"]])

# ---- audit messages: deleted content recovered
r = requests.get(B + f"/admin/chat-audit/threads/{thread}/messages", headers=h(at), timeout=60)
r.raise_for_status()
msgs = r.json()["messages"]
rec = next(m for m in msgs if m["id"] == m4["id"])
print("ADMIN sees deleted msg:", rec["text"][:60], "| recovered:", rec["recovered"], "| deleted_at:", rec["deleted_at_ist"])
assert "secret plan" in rec["text"] and rec["recovered"] is True
img = next(m for m in msgs if m["id"] == m3["id"])
print("photo msg has_image:", img["has_image"])
assert img["has_image"]

# ---- image bytes
ir = requests.get(B + f"/admin/chat-audit/messages/{m3['id']}/image", headers=h(at), timeout=30)
print("image fetch:", ir.status_code, ir.headers.get("content-type"), len(ir.content))
assert ir.ok and len(ir.content) > 0

# ---- thread export
r = requests.get(B + f"/admin/chat-audit/threads/{thread}/export", headers=h(at), timeout=60)
r.raise_for_status()
j = r.json()
print("export filename:", j["filename"], "| msgs:", j["message_count"])
print("--------- transcript tail ---------")
print("\n".join(j["content"].splitlines()[:14]))
print("...")
print("\n".join(j["content"].splitlines()[-22:]))
assert "secret plan" in j["content"] and "DELETED" in j["content"]
assert "PHOTO attached" in j["content"]

# ---- user-wide export
alice_id = me_a["id"]
r = requests.get(B + f"/admin/chat-audit/users/{alice_id}/export", headers=h(at), timeout=90)
r.raise_for_status()
j2 = r.json()
print("user export:", j2["filename"], "threads:", j2["thread_count"], "msgs:", j2["message_count"])
assert j2["message_count"] >= j["message_count"]
print("ALL CHAT AUDIT CHECKS PASSED")
