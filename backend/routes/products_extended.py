"""
Products Extended — auxiliary endpoints layered on top of the core product
schema. Keeps server.py lean.

Endpoints:
  GET    /api/brands/suggest?q=               typeahead (existing brand strings)
  GET    /api/vendors/suggest?q=              typeahead (vendor users)
  POST   /api/products/{id}/save              toggle wishlist
  GET    /api/me/wishlist                     my saved products
  POST   /api/products/{id}/questions         post a public question (Phase 2)
  GET    /api/products/{id}/questions         list public Q&A
  POST   /api/products/{id}/questions/{qid}/answer   vendor/admin answers
  POST   /api/products/{id}/reviews           submit a review (1-5★, photos)
  GET    /api/products/{id}/reviews           list reviews + aggregate
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.db import db
from core.security import get_current_user, require_admin

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_id(d: Dict[str, Any]) -> Dict[str, Any]:
    d.pop("_id", None)
    return d


# ───────────── Typeahead (Brand / Vendor) ─────────────

@router.get("/brands/suggest")
async def brand_suggest(q: Optional[str] = Query(""), _: Dict[str, Any] = Depends(get_current_user)):
    """Hybrid typeahead — returns existing distinct brand strings (and the
    structured attrs_brand field) so the admin can pick or type a new one."""
    pipeline = [
        {"$match": {"$or": [
            {"brand": {"$regex": q, "$options": "i"}},
            {"attrs_brand": {"$regex": q, "$options": "i"}},
        ]}} if q else {"$match": {}},
        {"$project": {"brands": {"$concatArrays": [[{"$ifNull": ["$brand", ""]}], [{"$ifNull": ["$attrs_brand", ""]}]]}}},
        {"$unwind": "$brands"},
        {"$match": {"brands": {"$ne": ""}}},
        {"$group": {"_id": {"$toLower": "$brands"}, "label": {"$first": "$brands"}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 25},
    ]
    rows = await db.products.aggregate(pipeline).to_list(50)
    return {"suggestions": [{"value": r["label"], "count": r["count"]} for r in rows if r.get("label")]}


@router.get("/vendors/suggest")
async def vendor_suggest(q: Optional[str] = Query(""), _: Dict[str, Any] = Depends(require_admin)):
    qry: Dict[str, Any] = {"role": "vendor"}
    if q:
        qry["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"email": {"$regex": q, "$options": "i"}},
            {"referral_code": {"$regex": q, "$options": "i"}},
        ]
    rows = await db.users.find(qry, {"_id": 0, "id": 1, "name": 1, "email": 1, "referral_code": 1}).limit(25).to_list(25)
    return {"suggestions": rows}


# ───────────── Wishlist ─────────────

@router.post("/products/{pid}/save")
async def toggle_wishlist(pid: str, user: Dict[str, Any] = Depends(get_current_user)):
    p = await db.products.find_one({"id": pid})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    existing = await db.wishlist.find_one({"user_id": user["id"], "product_id": pid})
    if existing:
        await db.wishlist.delete_one({"_id": existing["_id"]})
        return {"saved": False}
    await db.wishlist.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "product_id": pid,
        "created_at": _now(),
    })
    return {"saved": True}


@router.get("/me/wishlist")
async def list_wishlist(user: Dict[str, Any] = Depends(get_current_user)):
    cur = db.wishlist.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1)
    items = await cur.to_list(500)
    pids = [w["product_id"] for w in items]
    prods = await db.products.find({"id": {"$in": pids}}, {"_id": 0}).to_list(500)
    return {"items": prods, "count": len(items)}


# ───────────── Public Product Q&A ─────────────

class QuestionIn(BaseModel):
    text: str = Field(..., min_length=2, max_length=600)


class AnswerIn(BaseModel):
    text: str = Field(..., min_length=2, max_length=1200)


@router.post("/products/{pid}/questions")
async def ask_question(pid: str, body: QuestionIn, user: Dict[str, Any] = Depends(get_current_user)):
    p = await db.products.find_one({"id": pid})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    doc = {
        "id": str(uuid.uuid4()),
        "product_id": pid,
        "vendor_id": p.get("vendor_id"),
        "asker_id": user["id"],
        "asker_name": user.get("name") or "Customer",
        "text": body.text.strip(),
        "answers": [],
        "created_at": _now(),
    }
    await db.product_questions.insert_one(doc.copy())

    # ── June 2026 upgrade — Also mirror the question into a private
    # 1:1 chat thread between the customer and the vendor so the vendor
    # sees it in their inbox and can reply directly (fixing the bug
    # where Q&A messages were invisible in the chat box).  Auto-created
    # thread bypasses the request-handshake step.
    vendor_id = p.get("vendor_id")
    thread_id: Optional[str] = None
    if vendor_id and vendor_id != user["id"]:
        try:
            parts = sorted([user["id"], vendor_id])
            thread = await db.chat_threads.find_one({"participants": parts})
            if not thread:
                thread = {
                    "id": str(uuid.uuid4()),
                    "participants": parts,
                    "created_at": datetime.now(timezone.utc),
                    "last_message_at": datetime.now(timezone.utc),
                    # Mark as auto-created from product Q&A so client can style it
                    "kind": "product_qa",
                    "product_ref": {
                        "id": pid,
                        "name": p.get("name") or "",
                        "image_url": p.get("image_url") or "",
                        "price": p.get("price") or 0,
                    },
                }
                await db.chat_threads.insert_one(thread.copy())
            thread_id = thread["id"]

            # Post initial message (prefixed with product context)
            prefix = f"[About: {(p.get('name') or 'this product')[:80]}]\n"
            msg = {
                "id": str(uuid.uuid4()),
                "thread_id": thread_id,
                "sender_id": user["id"],
                "text": prefix + body.text.strip(),
                "image_data_url": "",
                "deleted": False,
                "deleted_for_everyone": False,
                "edited": False,
                "read_by": [user["id"]],
                "delivered_to": [user["id"]],
                "reply_to": None,
                "reactions": {},
                "starred_by": [],
                "client_dedupe_key": None,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
            await db.chat_messages.insert_one(msg.copy())
            await db.chat_threads.update_one(
                {"id": thread_id},
                {"$set": {"last_message_at": datetime.now(timezone.utc)}},
            )
        except Exception:
            # Best-effort — Q&A row already saved so the chat mirror is
            # non-fatal.  Log-and-continue keeps the customer experience
            # smooth even if the chat collection has an issue.
            thread_id = None

    result = _strip_id(doc)
    if thread_id:
        result["thread_id"] = thread_id
    return result


@router.get("/products/{pid}/questions")
async def list_questions(pid: str, _: Dict[str, Any] = Depends(get_current_user)):
    cur = db.product_questions.find({"product_id": pid}, {"_id": 0}).sort("created_at", -1).limit(100)
    return {"questions": await cur.to_list(100)}


@router.post("/products/{pid}/questions/{qid}/answer")
async def answer_question(pid: str, qid: str, body: AnswerIn, user: Dict[str, Any] = Depends(get_current_user)):
    q = await db.product_questions.find_one({"id": qid, "product_id": pid})
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    # Only the vendor of the product OR an admin can answer
    role = user.get("role")
    is_vendor = (q.get("vendor_id") == user.get("id"))
    if not is_vendor and role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Only the vendor or admin can answer.")
    answer = {
        "id": str(uuid.uuid4()),
        "by_id": user["id"],
        "by_name": user.get("name") or ("Admin" if role else "Vendor"),
        "by_role": "vendor" if is_vendor else "admin",
        "text": body.text.strip(),
        "created_at": _now(),
    }
    await db.product_questions.update_one({"id": qid}, {"$push": {"answers": answer}, "$set": {"answered_at": _now()}})
    return {"ok": True, "answer": answer}


# ───────────── Reviews ─────────────

class ReviewIn(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    title: Optional[str] = Field(default="", max_length=120)
    body: Optional[str] = Field(default="", max_length=2000)
    images: Optional[List[str]] = Field(default_factory=list)  # up to 3 base64


@router.post("/products/{pid}/reviews")
async def post_review(pid: str, body: ReviewIn, user: Dict[str, Any] = Depends(get_current_user)):
    p = await db.products.find_one({"id": pid})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    # Check: did user actually order this product? (verified_purchase flag)
    ordered = await db.orders.find_one({"user_id": user["id"], "items.product_id": pid})
    images = [im for im in (body.images or []) if im][:3]
    doc = {
        "id": str(uuid.uuid4()),
        "product_id": pid,
        "user_id": user["id"],
        "user_name": user.get("name") or "Customer",
        "rating": int(body.rating),
        "title": (body.title or "").strip(),
        "body": (body.body or "").strip(),
        "images": images,
        "verified_purchase": bool(ordered),
        "helpful_count": 0,
        "created_at": _now(),
    }
    await db.product_reviews.insert_one(doc.copy())
    return _strip_id(doc)


@router.get("/products/{pid}/reviews")
async def list_reviews(pid: str, user: Dict[str, Any] = Depends(get_current_user)):
    cur = db.product_reviews.find({"product_id": pid}, {"_id": 0}).sort("created_at", -1).limit(200)
    items = await cur.to_list(200)
    uid = user.get("id")
    # Mark whether the current viewer already up-voted each review
    for r in items:
        voters = r.get("helpful_voters") or []
        r["helpful_count"] = int(r.get("helpful_count") or len(voters))
        r["voted_helpful"] = uid in voters
        # Don't leak voter ids to the client
        r.pop("helpful_voters", None)
    # Aggregate stats
    counts = [0, 0, 0, 0, 0, 0]  # idx 1..5 used
    total = 0; sum_r = 0
    for r in items:
        rt = int(r.get("rating") or 0)
        if 1 <= rt <= 5:
            counts[rt] += 1; total += 1; sum_r += rt
    avg = round(sum_r / total, 1) if total else 0.0
    return {
        "reviews": items,
        "stats": {
            "average": avg,
            "total": total,
            "breakdown": {str(i): counts[i] for i in range(1, 6)},
        },
    }


# ───────────── Helpful Votes ─────────────

@router.post("/products/{pid}/reviews/{rid}/helpful")
async def toggle_helpful(pid: str, rid: str, user: Dict[str, Any] = Depends(get_current_user)):
    """Idempotent helpful-vote toggle.  Each user can up-vote a review once;
    tapping again removes the vote.  Returns the fresh count + voted flag."""
    rev = await db.product_reviews.find_one({"id": rid, "product_id": pid})
    if not rev:
        raise HTTPException(status_code=404, detail="Review not found")
    uid = user["id"]
    if uid == rev.get("user_id"):
        raise HTTPException(status_code=400, detail="You can't vote on your own review.")
    voters: List[str] = list(rev.get("helpful_voters") or [])
    if uid in voters:
        voters.remove(uid)
        voted = False
    else:
        voters.append(uid)
        voted = True
    await db.product_reviews.update_one(
        {"id": rid},
        {"$set": {"helpful_voters": voters, "helpful_count": len(voters)}},
    )
    return {"voted_helpful": voted, "helpful_count": len(voters)}


# ───────────── Vendor: pending Q&A ─────────────

@router.get("/vendor/me/questions")
async def vendor_pending_questions(user: Dict[str, Any] = Depends(get_current_user)):
    """Questions on this vendor's products. Returns unanswered first, then
    answered (most recent), capped at 100."""
    if user.get("role") != "vendor" and user.get("role") not in ("admin", "super_admin"):
        # Allow approved vendors only.  Admins can also use this for support.
        raise HTTPException(status_code=403, detail="Vendor access required.")
    qry: Dict[str, Any] = {"vendor_id": user["id"]} if user.get("role") == "vendor" else {}
    cur = db.product_questions.find(qry, {"_id": 0}).sort("created_at", -1).limit(100)
    items = await cur.to_list(100)
    # Attach product name for context
    pids = list({q["product_id"] for q in items})
    prods = await db.products.find({"id": {"$in": pids}}, {"_id": 0, "id": 1, "name": 1, "image_url": 1}).to_list(500)
    pmap = {p["id"]: p for p in prods}
    for q in items:
        p = pmap.get(q["product_id"]) or {}
        q["product_name"] = p.get("name") or "Product"
        q["product_image"] = p.get("image_url") or ""
        q["answered"] = bool(q.get("answers"))
    items.sort(key=lambda q: (q.get("answered"), -1 * (1 if q.get("answered") else 0)))
    # Two-bucket sort: unanswered (False) first, then by newest
    items.sort(key=lambda q: (q.get("answered"), q.get("created_at") or ""), reverse=False)
    unanswered = [q for q in items if not q.get("answered")]
    answered = [q for q in items if q.get("answered")]
    answered.sort(key=lambda q: q.get("created_at") or "", reverse=True)
    return {
        "pending_count": len(unanswered),
        "items": unanswered + answered,
    }
