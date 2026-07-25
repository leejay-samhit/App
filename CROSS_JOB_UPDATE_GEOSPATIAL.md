# CROSS-JOB UPDATE — Geospatial Marketplace Backend (Sept 2026)

**For:** Web-dev owning the production backend at `network-pay-1.emergent.host`.
**From:** Mobile agent — mobile client is already shipping the capture UI.

## Why
Owner wants location-based product visibility + a two-stage delivery verification (listing + checkout). Mobile has shipped:

- Vendor `/vendor/apply` payload NOW includes `location`, `pincode`, `state`, `district`, `city`, `store_address`, `delivery_radius_km`, `delivery_radius_mode`, `delivery_available`.
- Customer checkout `/orders/checkout` payload's `shipping_address` NOW includes `latitude`, `longitude`, `district`.

For the feature to actually enforce delivery-radius (server-authoritative), you need to ship the backend pieces below.

## 1. Schema additions

### `vendors` collection (or `vendor_applications` → then merge into vendor doc on approval)
```json
{
  "location": { "type": "Point", "coordinates": [<lng>, <lat>] },   // GeoJSON
  "pincode": "500001",
  "state": "Telangana",
  "district": "Hyderabad",
  "city": "Hyderabad",
  "store_address": "…",
  "delivery_radius_km": 5,           // 2 | 5 | 10 | 20 | 50 | null
  "delivery_radius_mode": "radius",  // "radius" | "pincode"
  "delivery_available": true
}
```

**Index:**
```python
await db.vendors.create_index([("location", "2dsphere")])
```

### `products` collection
Denormalise the vendor's location onto each product at product-create + when the vendor updates their shop location:
```json
{
  "vendor_location": { "type": "Point", "coordinates": [<lng>, <lat>] },
  "vendor_pincode": "500001",
  "vendor_delivery_radius_km": 5,
  "vendor_delivery_radius_mode": "radius",
  "vendor_delivery_available": true
}
```
**Index:**
```python
await db.products.create_index([("vendor_location", "2dsphere")])
```

## 2. Product listing endpoint

**`GET /api/products`** — accept optional `lat`, `lng`, `pincode` query params from customers:
```
GET /api/products?lat=17.4123&lng=78.4321&pincode=500001&category=Groceries
```

Behaviour:
- If BOTH `lat` and `lng` provided:
  - For radius-mode vendors: `$geoWithin: {$centerSphere: [[lng,lat], radius_km / 6378.1]}` filter matched against `vendor_location`.
  - For pincode-mode vendors: match on exact `vendor_pincode == customer.pincode`.
- If ONLY `pincode` (no GPS): exact `vendor_pincode == customer.pincode` match (fallback rule per owner).
- If NEITHER: return everything (backwards compat).
- Also filter `vendor_delivery_available: true`.
- Return `distance_km` (rounded to 1 decimal) on each product row so mobile can show "3.2 km away".

## 3. Checkout second-verification

**`POST /api/orders/checkout`** — after auth + cart validation, run this pre-flight:

```python
shipping = payload.shipping_address
if not shipping.latitude or not shipping.longitude:
    # Fallback — require pincode match
    for line in cart_items:
        prod = await db.products.find_one({"id": line.product_id})
        if not prod.get("vendor_pincode") or prod["vendor_pincode"] != shipping.pincode:
            raise HTTPException(422, detail={
                "code": "OUTSIDE_DELIVERY_ZONE",
                "message": "Sorry, this product is not deliverable to your selected address.",
                "product_id": line.product_id,
            })
else:
    for line in cart_items:
        prod = await db.products.find_one({"id": line.product_id})
        if not prod.get("vendor_delivery_available", True):
            raise HTTPException(422, detail={"code": "PICKUP_ONLY", "message": "…", "product_id": ...})
        mode = prod.get("vendor_delivery_radius_mode", "radius")
        if mode == "pincode":
            if prod.get("vendor_pincode") != shipping.pincode:
                raise HTTPException(422, detail=...)
        else:
            radius_km = float(prod.get("vendor_delivery_radius_km") or 5)
            hit = await db.products.find_one({
                "id": line.product_id,
                "vendor_location": {"$geoWithin": {
                    "$centerSphere": [[shipping.longitude, shipping.latitude], radius_km / 6378.1],
                }},
            })
            if not hit:
                raise HTTPException(422, detail={
                    "code": "OUTSIDE_DELIVERY_ZONE",
                    "message": "Sorry, this product is not deliverable to your selected address.",
                    "product_id": line.product_id,
                })
```

Return a machine-readable `code` so mobile can render a friendly toast without parsing English.

## 4. `AcceptedTermsBlock` still needs vendor_applications persistence — see prior handoff.

## 5. Reuse existing pincode-mapping (`distributor_areas`)
Owner asked to re-use the admin-panel Pincode Mapping table. When a vendor's captured pincode falls inside a mapped distributor area, tag the vendor with `distributor_area_id` for reporting. Not a hard requirement for MVP, but noted.

## Mobile side is already ready
No further mobile changes needed for backend items 2 + 3 above. As soon as `/api/products` starts accepting lat/lng, mobile will begin sending them (need one small mobile PR to read stored GPS from AsyncStorage on shop mount — will do that once you confirm the endpoint accepts the params without 400-ing).
