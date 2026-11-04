# Permanent product images — Jun 2026

## Confirmed root causes

1. **Smart Search / DeoDap imports went blank days later.**
   `src/rich-product-editor.tsx` wrote the *external* CDN URL (DeoDap/Shopify
   CDN, GSMArena, Openverse→Flickr) straight into `product.image_url` and
   `product.images[]`. Nothing was ever copied into storage we control, so
   hotlink rules, rotated object paths and deleted originals turned cards blank
   over time. **Yes — external image URLs were responsible, and Smart Search was
   storing third-party URLs (not temporary signed URLs, but equally volatile).**

2. **Images blank everywhere in the Android release APK.**
   `app.json` `extraProguardRules` kept only `com.facebook.react.**`. React
   Native's `<Image>` renders through **Fresco** (`com.facebook.drawee`,
   `imagepipeline`, `imageutils`, `animated`, `common`, `soloader`) and fetches
   through **OkHttp**, none of which were kept. R8 + `shrinkResources` stripped
   them from the release build, which is exactly why the same URL opened in
   Chrome but rendered nothing inside the APK.

3. **APK crashed when opening an imported product.**
   Shopify-CSV→JSON catalogues ship `images` as OBJECTS (`{src, position}`).
   `app/product/[id].tsx` passed each entry to `resolveImageUrl`, which called
   `.startsWith` on an object → TypeError during the hero-card render → the
   release build closed immediately.

4. **"Only 200 items" after a backup restore.**
   `app/admin/products.tsx` hardcoded `limit: "200"` with no pagination, and
   `/vendor/me/products` had a hard `$limit: 1000` with no offset. The restore
   itself was never capped — only the display was.

## Storage method

Permanent photos live in **MongoDB**, collection `product_image_files`, keyed by
the SHA-1 of the normalised bytes:

```
/api/img/<sha1>.<ext>            →  routes/images.py
/api/img/<sha1>.<ext>?w=360&q=72 →  grid-sized variant
```

Served with a strong ETag and `Cache-Control: public, max-age=31536000,
immutable` (safe because the key *is* the content hash), plus a small in-process
LRU.

MongoDB was chosen over Emergent Managed Object Storage because object storage is
credit-metered and returned `401 key is not active` in this environment — a
product photo must never become unviewable because a balance ran out or an
external service was unreachable. Images are downscaled to ≤1280 px JPEG q82 on
ingest (60-200 KB each), which is *smaller* than the base64 covers the app
already kept inside product documents. No provider migration was performed.

## How it works

`core/image_store.py`
- `_download()` — 3 bounded retries, identified bot UA for Wikimedia / browser
  UA elsewhere, **no Referer spoofing** (a site that refuses us is recorded as a
  failure, not worked around), `Accept` excludes AVIF so CDNs serve decodable
  formats, 12 MB ceiling.
- Validation — magic-byte sniff + content-type; HTML "enable JS" pages served as
  `image/jpeg` are rejected. AVIF/HEIF is transcoded to JPEG or reported as
  unsupported rather than stored unviewable.
- `normalize_gallery()` — flattens Shopify objects, honours `Image Position`,
  removes duplicate URLs, keeps every unique image.
- `persist_product_images()` — rewrites `image_url` + `images[]` in place,
  promotes a working gallery photo to the thumbnail when the chosen cover fails,
  and returns `{imported, reused, failed, failures[], status}`.
- A failure **keeps the original URL** and sets `image_import_status: "failed"`
  with `image_import_failures[]`, so a retry is always possible and a dead link
  is never passed off as stored.
- `image_assets` is a ledger of every source URL → ref / error, which also makes
  re-imports a cheap lookup.

Write paths hooked: `POST/PATCH /admin/products`, `POST/PATCH
/vendor/me/products`, `POST /vendor/me/catalogue/import`, `POST
/admin/backup/restore`. The two bulk paths use a ~22 s per-chunk budget so a
25-product chunk with 300 photos can't blow the 60 s edge timeout; the remainder
is marked `pending` and finished by the background worker.

## Repairing products that are already broken

Three ways, all driven by `repair_product_images()`:

| Trigger | Entry point |
|---|---|
| Admin button | `POST /api/admin/products/repair-images` (Products → "Fix product photos") |
| Automatic | paced background worker started ~25 s after boot and after a restore |
| On first open | `maybe_repair_one()` fired by `GET /api/products/{id}` |

`GET /api/admin/products/image-health` reports permanent / inline / external /
object-shaped / needs-repair / failed / no-image counts.

Products whose reference an **earlier** repair blanked are recovered from the
URLs recorded in `image_import_failures` (`RECOVERABLE_FILTER`). Repair only ever
writes the image fields — price, stock, description, variants, GST and categories
are never touched (covered by `test_d3`).

## Frontend

- `src/product-image.tsx` — THE product image component. Skeleton while loading,
  **one** cache-busted retry for transient failures, a grey placeholder carrying
  the product name when the image is genuinely unavailable, and a retry counter
  keyed on the resolved URI so recycled rows never show a stale error. A failure
  is contained inside the image box — name, price, Add and cart are unaffected.
  Used by: shop grid, product hero + thumbnail strip, rails, wishlist, cart,
  checkout, orders, admin grid, vendor grid.
- `src/product-shape.ts` — `sanitizeProduct()` coerces every field of an imported
  document to the shape the screens expect (the APK crash fix). Server-side,
  `_shape_product()` guarantees the wire never carries an object inside `images`.
- `resolveImageUrl()` hardened against non-string input.
- Admin + vendor product lists: server-side search + Load-more pagination with a
  true total. POS pages through the whole catalogue.
- Restore reports show photos stored / failed / queued **plus the failing URLs
  and reasons**, separately from the product counts.

## ProGuard additions (`app.json`)

```
-keep class com.facebook.drawee.**        { *; }
-keep class com.facebook.imagepipeline.** { *; }
-keep class com.facebook.imageformat.**   { *; }
-keep class com.facebook.imageutils.**    { *; }
-keep class com.facebook.animated.**      { *; }
-keep class com.facebook.fresco.**        { *; }
-keep class com.facebook.common.**        { *; }
-keep class com.facebook.soloader.**      { *; }
-keepclassmembers class * { native <methods>; }
-keep class okhttp3.** { *; }
-keep class okio.**    { *; }
-keep class com.facebook.react.modules.network.** { *; }
```

**This one can only be finally confirmed on a production release APK** — publish,
rebuild and reinstall before closing that item.

## Tests

`backend/tests/test_jun2026_permanent_images.py` — 22 passing:
permanent storage, servability + caching, restart survival, de-duplication,
honest failure reporting, failure recovery/retry, base64 covers untouched,
Shopify ordering + de-duplication, 1/5/10/15 images per product, no objects on
the wire, lazy repair, image health, repair endpoint, non-image fields untouched,
admin pagination, vendor pagination, whole-catalogue paging.


## Iteration-106 code-review fixes (same change-set)

An independent review found four further defects, all fixed and covered by
tests `test_e1`-`test_e5` in `tests/test_jun2026_permanent_images.py`:

1. **Unstable paging skipped and repeated products.** `created_at` alone is not
   unique — a bulk import writes hundreds of products in the same second, so a
   skip/limit walk overlapped and silently lost rows. The admin list
   (`server.py` admin_list_products), the vendor list (vendor_my_products) and
   the vendor export (`backup.py`) now sort on `{created_at, id}`; the admin
   full-backup dump, the account dump and the streamed backup file now sort on
   `_id`. Verified: admin 285/285 unique, vendor 277/277 unique, export 277 rows
   / 277 distinct.
2. **Re-running a vendor restore duplicated products.** The export strips product
   ids, so a merge restore is now keyed on the shop's own product NAME: a second
   run reports `updated`, not `created`. Also, `replace` mode deleted only the
   first 5,000 products — it now deletes by query.
3. **SSRF in the image downloader.** A vendor-supplied URL could point at
   `http://127.0.0.1:27017` and the error text revealed which internal ports
   were open. `_blocked_target()` now refuses non-web ports, `localhost`/
   `.internal` names and any hostname resolving to a private, loopback,
   link-local, reserved, multicast or unspecified address; **every redirect hop
   is re-checked** (redirects are followed manually); the refusal message is
   uniform and leaks nothing.
4. **Background repair looped forever on partly-fixed products.** A `partial`
   product keeps its dead URL for a retry, so it still matched
   `NEEDS_REPAIR_FILTER`. The automatic sweep now uses `PENDING_FILTER`, which
   excludes both `failed` and `partial`; the admin's "Retry failed photos"
   (`retry_failed=true`) still reaches them.

The reviewer also fixed three frontend bugs in this change-set, reviewed and kept:
stable `onLoadStart`/`onLoad` callbacks in `src/product-image.tsx` (an inline
arrow caused ~130 "Maximum update depth exceeded" errors per product page), an
explicit height on each image container (admin grid, vendor grid, wishlist,
product thumbnail strip — without it the box collapsed and looked blank), and a
`products-search-input` testID.


## Iteration-107 retest fixes — a backup can now restore the image store

The retest confirmed paging and vendor-restore idempotency, and found that the
FULL-APP backup still could not bring product photos back. Root cause: the
export's `_json_safe()` deleted `_id` from every document and `json.dumps(...,
default=str)` turned raw image bytes into the literal text `"b'\xff\xd8...'"`.
In `product_image_files` the `_id` IS the key inside every `/api/img/<key>`
link, so a backup restored into a fork came back with every photo blank, and
`counters` restored as nameless `{seq: N}` (new short IDs then collided with the
unique `short_ids.code` index).

Fixed in `routes/backup.py`:
* `_json_safe()` KEEPS `_id`, tags ObjectIds as `{"$oid": ...}` and encodes
  binary as `{"$b64": ...}`; new `_json_revive()` is the exact inverse and runs
  on every document being restored.
* The restore upserts id-less documents on `_id` (short_ids, image_assets,
  payout_keys, product_image_files…) instead of blind-inserting them, so
  replaying a file twice is a no-op; `upserted` now counts `matched_count` so a
  re-restore of identical documents no longer reports 0.
* `GET /admin/backup/dump?collection=product_image_files` no longer 500s with
  a UnicodeDecodeError.
* Vendor merge restore claims each existing row at most once per chunk (a shop
  may hold two products with the same name, and a file may list that name
  twice — collapsing them was the data loss we are fixing), and it no longer
  unpublishes a matched LIVE product.

Verified end-to-end through the real admin API with a temporary Danger PIN:
the whole `product_image_files` collection was WIPED and restored from the
backup file, and all 7/7 photos served again with byte-identical content.

Known limitation (by design): the VENDOR catalogue export carries
`/api/img/<key>` links, not image bytes, so it is for moving a catalogue
between shops in the SAME deployment. Cross-deployment moves use the full-app
admin backup, which now carries the bytes.

Suites: `test_jun2026_permanent_images.py` 27, `test_iter106_images_pagination_review.py` 9,
`test_iter107_pagination_backup_retest.py` 40 — 76 passing. `test_iter66_app_backup.py`
(admin restore round-trip, real Danger PIN) PASS.


## Iteration-108 fixes — three restore crashes / one more lost product

The final backend check cleared defects 1, 2, 3 and 5 and found three more:

1. **A product was still lost when the same name spanned two upload chunks.**
   The app posts `IMPORT_PAGE = 5` products per request, and the "claim each
   row once" set only lived for ONE request — so chunk 2 re-read the shop,
   found the row chunk 1 had just created and overwrote it. The client now
   generates one `restore_session` id per file and sends it on every chunk;
   the server stamps `restore_session` on every row it creates or updates and
   excludes stamped rows when matching by name. A repeat restore (new session)
   still matches and reports `updated`, so it stays idempotent.
2. **Admin merge restore 500'd when a row already existed under a different
   `_id`.** Keeping `_id` in the export meant `ReplaceOne({"id": …}, d)` tried
   to change an existing document's `_id`, which Mongo refuses (error 66).
   Since the client walks collections in order, a failure at `settings`
   (created independently in every deployment) would have aborted every
   collection after it. The replacement body now drops `_id` when matching on
   `id`; the `_id` match is used only for documents that have no `id`.
3. **Retrying a `wipe`-mode chunk 500'd on a duplicate `_id` (error 11000).**
   A flaky mobile upload retry is now a no-op: wipe-mode chunks upsert on
   `_id` instead of blind-inserting.

Also removed a single orphan `counters` row keyed by ObjectId instead of a
name — dead weight left by the old name-stripping restore (counters are only
ever read by name, so it was unreachable) that would otherwise have been
copied into every future backup.

Suites: iter108 15, iter107 40, iter106 9, permanent-images 27 — **91 passing**,
plus `test_iter66_app_backup.py` PASS and 48 passing across the layout/COD,
catalogue-backup and festival suites.


## Iteration-109 fix — a restore no longer locks the admin out mid-way

All three iter108 issues verified fixed. The retest then found one more HIGH
bug while exercising the `settings` case:

**Restoring `settings` overwrote the live `danger_pin_hash`.** The restore
screen re-sends the same PIN for every collection and walks them
alphabetically, so a file from another deployment (or taken before the PIN was
changed) replaced the hash and the VERY NEXT collection came back 401 "Invalid
Danger PIN". Everything after `settings` — `users`, `transactions`,
`vendor_*`, `wallet_topups`, `withdrawals` — was never restored, and the admin
silently lost their own PIN. A `wipe` of a settings page with no global row
deleted the PIN entirely ("Danger PIN not set").

Fix: the live PIN is read BEFORE anything is deleted, stripped from every
incoming settings document, and re-applied (upsert on `id: "global"`) after the
write. Covered by `test_2d_settings_from_other_deployment_with_different_pin`
and the new `test_2e_wipe_settings_keeps_the_live_pin`.

Also fixed from the same report:
* `restore_session` / `restored_at` / `restored_from_backup` are now in
  `OWNERSHIP_FIELDS`, so a previous restore's bookkeeping no longer travels
  inside a fresh vendor export (`test_2f_restore_session_is_not_exported`).
* A retried wipe chunk is reported as `replayed`, not counted again as
  `inserted`.

Deliberately NOT changed: an APK installed before `restore_session` existed
sends no session id, so its chunks share no key and a name split across two
chunks can still merge onto one row. Every server-side substitute (e.g. a time
window) makes a repeat restore duplicate the whole catalogue, which is worse;
the fix is to install the new build. The code says so at the matching site.

Suites: iter109 14, iter108 15, iter107 40, iter106 9, permanent-images 27 —
**105 passing**, plus `test_iter66_app_backup.py` PASS.
