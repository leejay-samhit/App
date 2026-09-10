"""Phase 5B smoke test — shop-layout responses must never inline base64.

Seeds a block with a real (small) base64 PNG on the block AND on a slide,
then checks:
  • GET /shop-layout + /admin/shop-layout return image URLs, not data URLs
  • those URLs serve the actual bytes
  • saving the block back with the URL keeps the stored artwork (no wipe)
"""
import asyncio
import base64
import os
import sys

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

BASE = "http://localhost:8001/api"
PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx"
    "0gAAAABJRU5ErkJggg=="
)
DATA_URL = f"data:image/png;base64,{PNG}"


def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=60)
    r.raise_for_status()
    d = r.json()
    return {"Authorization": f"Bearer {d.get('access_token') or d.get('token')}"}


async def main():
    h = login("support@slangcart.com", "3)Ywxtic")
    created = requests.post(f"{BASE}/admin/shop-layout", headers=h, timeout=60, json={
        "block_type": "banner_slider",
        "scope": "home",
        "title": "ITER66 payload test",
        "image_data_url": DATA_URL,
        "active": True,
        "sort_order": 999,
        "items": [{"label": "Slide A", "image_data_url": DATA_URL, "link_type": None, "link_value": ""}],
    })
    created.raise_for_status()
    block = created.json()
    bid = block["id"]
    print("created", bid)
    try:
        assert block["image_data_url"] == f"/api/shop-layout/{bid}/image", block["image_data_url"]
        assert block["items"][0]["image_data_url"] == f"/api/shop-layout/{bid}/items/0/image"

        pub = requests.get(f"{BASE}/shop-layout", params={"scope": "home"}, timeout=60).json()
        mine = [b for b in pub["items"] if b["id"] == bid][0]
        assert not mine["image_data_url"].startswith("data:"), "base64 leaked into the public list"
        assert not mine["items"][0]["image_data_url"].startswith("data:")

        adm = requests.get(f"{BASE}/admin/shop-layout", headers=h, timeout=60).json()
        amine = [b for b in adm["items"] if b["id"] == bid][0]
        assert not amine["image_data_url"].startswith("data:"), "base64 leaked into the admin list"

        img = requests.get(f"http://localhost:8001/api/shop-layout/{bid}/image", timeout=60)
        assert img.status_code == 200 and img.headers["content-type"].startswith("image/"), img.status_code
        assert img.content == base64.b64decode(PNG), "block image bytes differ"
        sl = requests.get(f"http://localhost:8001/api/shop-layout/{bid}/items/0/image", timeout=60)
        assert sl.status_code == 200 and sl.content == base64.b64decode(PNG), "slide image bytes differ"
        print("image endpoints OK, cache:", img.headers.get("cache-control"))

        # Round-trip: save the block back exactly as the admin app received it.
        patched = requests.patch(f"{BASE}/admin/shop-layout/{bid}", headers=h, timeout=60, json={
            "title": "ITER66 payload test (renamed)",
            "image_data_url": mine["image_data_url"],
            "items": [{**mine["items"][0], "label": "Slide A renamed"}],
        })
        patched.raise_for_status()
        print("patched ->", patched.json()["title"], patched.json()["items"][0]["label"])
        again = requests.get(f"http://localhost:8001/api/shop-layout/{bid}/image", timeout=60)
        assert again.status_code == 200 and again.content == base64.b64decode(PNG), "save wiped the block image!"
        slide_again = requests.get(f"http://localhost:8001/api/shop-layout/{bid}/items/0/image", timeout=60)
        assert slide_again.status_code == 200 and slide_again.content == base64.b64decode(PNG), "save wiped the slide image!"
        print("PASS")
    finally:
        requests.delete(f"{BASE}/admin/shop-layout/{bid}", headers=h, timeout=60)
        print("cleaned up test block")


if __name__ == "__main__":
    asyncio.run(main())
