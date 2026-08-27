# NetworkPay — Referral & E-commerce Platform

## Overview
Mobile-first (Expo) referral platform for the Indian market. Multi-level commission, mocked UPI registration, wallet-based e-commerce, in-app notifications, achievement tiers, and a comprehensive admin panel with analytics, KYC, audit log, RBAC, and CSV exports.

## Tech Stack
- Frontend: Expo SDK 54, expo-router, @expo/vector-icons, react-native-reanimated, react-native-svg, expo-clipboard, AsyncStorage, axios
- Backend: FastAPI, Motor (async MongoDB), bcrypt, PyJWT
- Auth: JWT Bearer tokens (AsyncStorage)
- Payments: MOCKED (`/api/payment/register-fee` simulates ₹100 UPI; `/api/orders/checkout` is wallet-only)

## Core Business Rules (admin-tunable via Settings)
- `registration_fee` (default ₹100)
- `payout_l1` — direct sponsor (default ₹400) credited every `directs_required` directs
- `payout_l2` — grand-sponsor (default ₹100) per signup
- `payout_l3` — great-grand-sponsor (default ₹50) per signup
- `directs_required` — direct count per L1 cycle (default 4)
Stored in `settings` collection (`id="global"`), applied live to `/payment/register-fee`.

## Roles & RBAC
- `role`: `user` or `admin`
- `admin_role` (admins only): `super_admin` (full), `manager`, `support` — only super_admin can update payout settings.
- Admin login (`admin@app.com` / `Admin@123`) is auto-seeded as super_admin.

## Implemented Features (Phase 1)
**User app (5 tabs)**: Dashboard (animated, tier pill, hero, level chips, activity feed) · Network (tree) · Wallet (withdraw, txn list) · Shop (cart) · Profile (UPI/bank, KYC link). Stack screens: cart, orders, notifications, kyc.

**Admin app (5 tabs)**: Home (analytics + 3 bar charts + KPIs + quick actions) · Users (search, edit modal with Block/Freeze/Wallet adjust/KYC approve) · Payouts (approve/reject) · Transactions · More (Operations links + 4 CSV exports + logout). Stack screens: settings, kyc queue, orders mgmt, audit log.

**New backend**: 
- Multi-level commission engine; mocked payments
- KYC text-based (Aadhaar/PAN/full name) with admin approve/reject
- User block/unblock; login enforces block
- Wallet admin adjust (credit/debit with reason), freeze/unfreeze (blocks withdrawal + checkout)
- Transaction filter (type/status/user/date/q), manual status update, manual refund
- Order management (placed/shipped/delivered/cancelled — cancel auto-refunds wallet)
- Admin audit log (every admin action recorded)
- Analytics (KPIs + 30-day daily series for revenue/users/txns)
- CSV export (users / transactions / withdrawals / orders)
- Multi-admin RBAC: only `super_admin` can update settings

**Tests**: 58/58 backend pytest pass.

## API Surface (selected)
**Auth**: `POST /auth/register|login|logout`, `GET /auth/me`
**User**: `/users/me/dashboard|network|kyc|bank`
**Wallet**: `POST /withdrawals`, `GET /withdrawals/me`, `GET /transactions/me`
**Cart/Orders**: `GET /cart`, `POST /cart/add|remove|clear`, `POST /orders/checkout`, `GET /orders/me`
**Notifications**: `GET /notifications/me`, `POST /notifications/me/read-all`
**Admin Users**: `GET/PATCH/DELETE /admin/users[/:id]`, password reset, `block`/`unblock`, `wallet`(adjust), `wallet/freeze`
**Admin KYC**: `GET /admin/kyc`, `POST /admin/kyc/{id}/approve|reject`
**Admin Txns**: `GET /admin/transactions/filter`, `PATCH /admin/transactions/{id}`, `POST /admin/transactions/{id}/refund`
**Admin Orders**: `GET /admin/orders`, `PATCH /admin/orders/{id}/status`
**Admin Misc**: `GET /admin/analytics`, `GET /admin/audit-logs`, `GET /admin/export/{kind}`
**Admin Settings (super_admin only)**: `GET/PUT /admin/settings`

## Phase 2 (deferred — needs keys / native build)
Real payment gateway (Razorpay/Cashfree), Mobile recharge API, Push notifications (FCM + EAS), SMS/Email gateway, KYC image uploads, Support ticket system.

## Test Credentials
See `/app/memory/test_credentials.md`


## Jun 2026 P0 Batch (post-handoff)
- Fixed Android hardware-back closing app on Dashboard/Chat/Profile/Wallet/Network — now navigates back to Shop tab.
- Fixed Admin Shop Layout force-close on subcategory selection (categories.map object-rendering bug).
- Added `q` search param on /api/products backed by pincode/vendor-eligibility filter so Shop search finds products beyond first-paint set.


## Jun 2026 Batch — Perf, Cart Stepper, Layout Crash
### Backend
- `/api/admin/products` paginated + slim projection (drops base64 images) — was crashing at ~150 products.
- `/api/cart` batched product fetch, slim projection — was 5-10s on N+1 loops.
- `/api/products?q=` free-text search.
- New `/api/cart/adjust {product_id, delta}` — supports negative deltas for stepper decrement.

### Frontend
- Shop-category product cards: qty stepper (− N +) replaces Add when in cart.  Optimistic updates.
- Admin products loader updated for paginated envelope.
- Admin shop-layout: fixed 3 categories.map object-render crashes on subcategory tabs.
- Android hardware-back on non-shop tab roots navigates to /shop instead of exiting.



## Jun 2026 Batch — Multi-Vendor Split, Wallet+COD, Order Cards, Vendor Panel (Iter 55)

### 1. Multi-vendor order splitting (backend + frontend)
- `POST /api/orders/checkout` now GROUPS cart items by `vendor_id` and inserts
  **one order document per vendor**. Each sub-order gets:
  `order_number` (`SC-<6 char group ref>` for single-vendor, `SC-<ref>-1 / -2 / …`
  when split), a shared `group_id`, plus `split_index` / `split_count`,
  `vendor_id`, `vendor_name`.
- Independent status thread per seller: vendor status PATCH, ETA/rider info,
  cancellation and commission settlement all operate on the sub-order.
- Response shape: `{ orders: [...], group_id, split_count, grand_total,
  wallet_paid, cod_due, …legacy top-level fields }`.
- `vendor_sales` ledger rows are scoped to the sub-order (`order_id`,
  `order_number`, `group_id`).
- Legacy pre-split orders are back-filled on read in `GET /orders/me`
  (synthetic `order_number`, resolved `vendor_name`, derived
  `wallet_paid` / `cod_due`) so old orders keep rendering.

### 2. Wallet + COD combo payment
- New `payment_method: "wallet_cod"` with `wallet_amount`.
- Wallet slice is debited atomically (guards double-submit) and allocated
  across sub-orders in cart order; the split always ties back to the basket
  total. Per-order fields: `wallet_paid`, `cod_due`,
  `payment_status` (`paid` / `partial_cod` / `pending_cod`),
  `paid_via` (`wallet` / `cod` / `wallet_cod`).
- Degrades safely: `wallet_amount = 0` → pure COD, `>= total` → pure wallet.
- On insufficient balance → 400 + product stock rolled back.
- Vendor payout + platform margin are credited immediately ONLY for fully
  prepaid sub-orders; anything with cash due settles on `delivered`.
- Cancellation refunds exactly the wallet-funded slice (full total for pure
  wallet, `wallet_paid` for combos, nothing for pure COD) — both the user
  cancel route and the admin/vendor status PATCH.
- Checkout UI: third payment option "Wallet + Cash on Delivery" reveals a
  slider (`@react-native-community/slider`) defaulting to **auto-max**
  wallet, with ₹0/25/50/75/Max chips and a live "FROM WALLET / CASH ON
  DELIVERY" breakdown. Sticky footer shows `WALLET ₹X + CASH` / cash amount.

### 3. My Orders redesign
- Card is now: seller row (shop avatar + vendor name + order number +
  "Order 1 of 2" for splits) → status pill → 3-step tracker
  (Placed / Shipped / Delivered, hidden when cancelled) → thumbnails +
  item count + total → payment line (`Wallet + Cash · ₹30 paid, ₹70 on
  delivery`) → action row.
- New `POST /api/orders/{order_id}/chat-vendor` opens (or reuses) a direct
  buyer↔seller thread without the chat-request handshake, powering the
  one-tap **"Ask this seller"** button.
- Invoice modal now shows ORDER / SELLER / PAYMENT, a wallet-vs-cash
  breakdown and an amber "Hand ₹X in cash to the delivery agent" banner.

### 4. Vendor panel cleanup
- **ROOT CAUSE FIX**: `/vendor/me/stats`, `/vendor/me/earnings` and
  `/vendor/me/sales` were reading `db.vendor_pos_sales`, a collection the
  POS module never writes to — so "Store Sale" always showed ₹0 / 0
  invoices. They now read `db.offline_sales` (`status: "completed"`, money
  at `totals.grand_total`, `customer{}`, `payments[]`, `invoice_no`).
- Cancelled / refunded / returned orders are now EXCLUDED from
  `total_sales`, `today_earnings`, `online_total` and the order counts.
- Renames: "POS sales" → **Store sale**, "Invoices" → **All invoices** tile /
  "Shop order & Store sale Invoices" screen title, "Sales history" →
  "Store sale history", channel pills `NEW SALES · POS` → **STORE SALE** and
  `ONLINE SHOP` → **SHOP ORDERS**, drill-down chips `ALL CHANNELS / SHOP
  ORDERS / STORE SALE`, row tags `SHOP` / `STORE`.
- "TODAY ORDERS" stat card is now tappable → `/vendor/orders`.
- Stats grid rebuilt as an even 2-column layout (`statCell` 48.5% +
  `minHeight: 108`) so all six boxes align.
- Vendor order cards show the `SC-` order number and an amber
  "Collect ₹X in cash · ₹Y already paid online" strip for live COD orders.

### Testing
- `/app/backend/tests/seed_iter55.py` — seeds the 2nd vendor + split fixtures.
- `/app/backend/tests/test_iter55_split_checkout.py` — happy-path E2E.
- `/app/backend/tests/test_iter55_edge_cases.py` — 13/13 pass.
- `/app/backend/tests/test_iter55_vendor_flow.py` — delivered settlement +
  wallet_cod cancel refund.
- Frontend verified via Playwright: slider auto-max ₹450→₹0, chips, footer
  split, order cards, invoice modal, Ask-this-seller → /chat/<id>, vendor
  dashboard STORE SALE ₹300/1 invoice, TODAY ORDERS → /vendor/orders.


## Jun 2026 Batch — Multi-Pincode Banners, Swipe Nav, Cash Summary, Group Orders (Iter 56)

### 1. Multi-pincode banner targeting
- `shop_layout` blocks now carry `scope_pincodes: string[]` alongside the
  legacy single `scope_pincode` (kept so every pre-existing block keeps
  working). `_norm_pincodes()` keeps only 6-digit numeric values, de-dupes
  preserving admin order and caps at 50.
- `_scope_filter()` matches a customer when their pincode appears in EITHER
  field; a block is "global" only when BOTH are empty. Blocks with targets
  are still hidden from customers whose location is unknown.
- Legacy docs are back-filled on read (`scope_pincodes = [scope_pincode]`).
- Admin UI: the single pincode input is now a chip builder — type a pincode
  → Add → removable chips + "Clear all", with a live "Shows only to
  customers in N pincodes." hint. Block cards show a `map-pin` badge reading
  the pincode (single) or "N PINCODES" (multi). The list filter + distinct
  pincode chips are multi-pincode aware.

### 2. Swipe between categories
- `shop-category/[name].tsx` now walks one conceptual list:
  `[All, sub-1, sub-2, …]` for the current category. A horizontal swipe
  (PanResponder, `|dx| > 60` with `|dy| < 24` so vertical scrolling is
  untouched) steps through sub-categories instantly (client-side filter,
  zero network) and, once past either end, hops to the neighbouring
  SIBLING category resolved from `/shop-categories/tree`.
- Explicit `cat-prev` / `cat-next` chevrons in the header mirror the same
  `swipeStep()` code path so the navigation is discoverable and testable.
- A dark toast names whatever the swipe landed on.

### 3. Delivery cash summary (vendors)
- `GET /vendor/me/stats` adds `cod_pending_total`, `cod_pending_count`,
  `cod_collected_today`, `cod_collected_today_count` computed from orders
  with `cod_due > 0` (pending = placed/shipped, collected = delivered today).
- `PATCH /admin/orders/{id}/status` now stamps `delivered_at` on the
  placed→delivered transition so "collected today" keys off when the cash
  actually changed hands.
- Vendor dashboard gets an amber "CASH TO COLLECT" card: Collected Today vs
  Still Out With Riders, tapping through to `/vendor/orders`.

### 4. Group order view
- `orders.tsx` injects a "1 checkout · N sellers" summary row above the
  first card of each multi-seller group (siblings are adjacent in the
  newest-first list), showing the combined total and an N/N progress count.

### Verified
- Multi-pincode: block targeting 517644+517640 shows for both, hidden for
  500001 and for unknown-location customers; legacy single-pincode block
  still shows for its own pincode.
- Swipe: Electronics → Fashion → Grocery → back to Fashion via the arrows
  (identical code path as the gesture).
- Cash summary: ₹60 collected today / ₹300 still out, 4 orders.
- Group header: "1 checkout · 2 sellers · ₹450 total · 2/2" above
  SC-929938-1 and SC-929938-2.


## Jun 2026 — Home Screen Swipe (Iter 57)

`src/shop-home.tsx` now supports the same left/right glide as the category
screen, but entirely in place:

- Conceptual list `catChain = ["all", …admin categories]`. A horizontal
  flick steps through it, setting `activeCategory`, which renders the
  existing in-screen filtered product grid from already-loaded products —
  **zero network calls**, so gliding across the shop is instant.
- Implemented with `PanResponder` on a wrapper around the home ScrollView.
  It only claims the touch when `|dx| > 24 && |dy| < 24` (release threshold
  `|dx| > 60`), so vertical scrolling and the horizontal category strip keep
  working. Verified: a vertical drag does NOT change the category.
- The category strip auto-scrolls (`catStripRef.scrollTo`) so the newly
  active chip stays in view and stays highlighted, mirroring the swipe.
- A dark toast (`swipeHint`) names whatever the swipe landed on
  ("All categories" for the reset position).

### Testing note (important for future agents)
`PanResponder` on react-native-web does NOT respond to Playwright
`page.mouse.*` events — you must dispatch real touch events over CDP:
```python
client = await page.context.new_cdp_session(page)
await client.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": 330, "y": 520}]})
# …touchMove xN…  then {"type": "touchEnd", "touchPoints": []}
```
Also: after `page.goto(...)` the Slangcart splash overlay sits on top of the
app and swallows touches — navigate INSIDE the app (tap through) when
testing gestures, otherwise the gesture silently never fires.

### Verified
- Home: All → Electronics → Fashion → Grocery on successive left flicks,
  right flick back to Fashion, vertical drag leaves the category unchanged.
- Category screen (navigated in-app, no splash): left flick on Electronics
  with no sub-categories hopped to the Fashion sibling as designed.


## Jun 2026 — One App-Wide Left/Right Swipe (Iter 58)

User feedback (with a WhatsApp screen recording): tab-to-tab swipe did nothing
(Shop→Services→Dashboard→Chat→Profile), My Orders had no swipe, and the dark
"black box with white letters" toast + the two manual arrow keys on the shop
category screen were unwanted. Ask: ONE consistent swipe animation everywhere
tabs exist.

### New shared primitive — `src/use-swipe-pager.ts`
`useSwipePager({ onNext, onPrev, enabled })` returns PanResponder handlers.
Single source of truth for the feel:
- claims the touch only on a clearly horizontal drag (`|dx| > 24 && |dy| < 24`)
- commits on `|dx| > 60` OR a fast flick (`|vx| > 0.35`)
- non-capturing, so vertical ScrollViews, horizontal chip strips and buttons
  keep their own gestures
- callbacks live in a ref, so the responder is created once

### Where it's wired (one behaviour, no exceptions)
| Screen | Swipe walks |
|---|---|
| `app/(tabs)/_layout.tsx` | Shop · Services · Dashboard · Chat · Profile |
| `app/orders.tsx` | All · Placed · Shipped · Delivered · Cancelled |
| `app/(tabs)/shop-category/[name].tsx` | sub-sections, then sibling categories |
| `app/vendor/dashboard.tsx` | Overview · Products · Sales · Q&A |
| `app/vendor/orders.tsx` | all · placed · shipped · delivered · cancelled |
| `app/vendor/invoices.tsx` | All · Store sale · Shop orders |

Bottom tabs also got `animation: "shift"` so the outgoing screen slides out
while the incoming one slides in, matching the reference video.

### Precedence rule (important)
The FIVE main tab screens let the TAB pager own horizontal swipes. The home
screen therefore does NOT claim them any more (its category swipe from
iteration 57 was removed) — otherwise Shop→Services could never fire once
shop categories existed. Non-tab screens (My Orders, category detail, vendor
panel) own their own strip. `tabIndex < 0` disables the tab gesture on
drilled-in routes such as `shop-category/[name]`, `wallet` and `network`.

### Removed per user request
- The dark swipe toast on shop home AND the category screen (`swipeHint`).
- The manual `cat-prev` / `cat-next` chevrons beside the cart icon
  (plus their `navArrows` styles). The header eyebrow still reads
  "SWIPE ↔ CATEGORY" as the only affordance.

### Bugs found and fixed while building this
1. `stepFilter` originally did `setFilter(cur => { …scrollToIndex… })` — a
   side effect inside a state updater, which React 18 dev double-invokes, so
   swipes skipped filters. Now computed outside the updater.
2. The My Orders chip `FlatList` stretched to fill the column once the list
   body was wrapped in a flex View. Fixed with
   `chipStripOuter: { flexGrow: 0, flexShrink: 0 }`.

### Known pre-existing (NOT caused by this change, web-preview only)
The buyer Dashboard renders blank below the earnings card on react-native-web
because the Reanimated `entering={FadeInDown…}` blocks stay at opacity 0.
Verified identical with `animation: "shift"` removed and on a direct page
load. Works on device.


## Jun 2026 — One Product Card Everywhere + Add-to-Cart from Search (Iter 59)

User report: "Shop when users search the product all the products showing
different features -33% 4.4* 48k reviews but in categories and sub categories
showing different view — apply only one type of product displayment, as per
that categories-wise view is good. Also when search, after product display,
unable to add items in the cart. Use every existing resource and remove
unwanted thing app could perform faster."

### New shared primitives
- **`src/product-grid-card.tsx`** — `ProductGridCard` + `productGridStyles.wrap`.
  THE product card for the shop: square image, 2-line name, price, and either
  an "Add" pill, an inline −/+ stepper (when already in the cart) or a
  SOLD OUT chip. Extracted from the category screen (the look the user liked).
- **`src/use-shop-cart.ts`** — `useShopCart()` returning
  `{ cartCount, cartQty, addedFlash, refresh, addToCart, decrement }`.
  Optimistic adds with rollback on failure; `+` → `POST /cart/add`,
  `−` → `POST /cart/adjust { delta: -1 }` (because `/cart/add` rejects qty<=0
  and the server deletes the row at 0).

### Unified surfaces
Search results, the shop-home in-screen category grid and the category
screen all render `ProductGridCard` wired to `useShopCart`. Search results
previously used a DIFFERENT, flashier card with **fabricated** numbers
(`seededDiscount` → "-33%", `seededRating` → "4.4★",
`12 + (id.length % 40) + "k reviews"`) and, critically, **no Add button at
all** — which is exactly why nothing could be added to the cart from a search.

### Cart bugs fixed
1. **Search results had no Add control.** Fixed by the unification above.
2. **`ShopLayoutRenderer` Add buttons were dead in two places.**
   - shop-home posted `POST /cart { product_id, quantity: 1 }` — an endpoint
     that does not exist (the real one is `POST /cart/add { product_id, qty }`)
     and the failure was swallowed by a `console.warn`.
   - the category screen never passed `onAddToCart` at all.
   Both now route through the shared cart controller.
3. Added an "Added • <product>" confirmation strip to the shop home / search
   grid (the category screen already had one) so a tap gives visible feedback.

### Dead code / perf cleanup (net −301 lines)
Removed from `src/shop-home.tsx`: `seededRating`, `seededDiscount`,
`productImage`, local `formatINR`, `POPULAR_CATEGORIES`, `dealsOfTheDay`,
`bestSellers`, the old `ProductCard`, `SectionHeader`, the whole
`banners`/`activeBanner` block, `bannerIdx` state, `useWindowDimensions`,
`FlatList`/`resolveImageUrl` imports, a duplicate `hList` style key and ~21
orphaned `p*`/`section*` styles.
Removed from `app/(tabs)/shop-category/[name].tsx`: the local cart state and
handlers (now the hook), the inline card + its 11 styles, the dead
`hasLayout` state and — importantly — **a duplicate `GET /shop-layout`
request that fired on every category open just to set that unread flag**
(`ShopLayoutRenderer` already fetches its own blocks). Plus unused
`useRef` / `Image` / `ActivityIndicator` / `Alert` / `api` / `formatApiError`
/ `resolveImageUrl` / `formatINR` / `FadeSlideIn` imports.

### Native crash risk fixed
`<View style={styles.headerRow}>        <TouchableOpacity …` — an earlier
edit in this session collapsed a newline, leaving 8 literal spaces as a text
child of a `<View>`. That logs `Unexpected text node: A text node cannot be a
child of a <View>` on web and **crashes on native RN**. Newline restored;
warning count went 6 → 0.

### Verified
Search "widget" → 2 products on the clean card with no fake badges; Add →
stepper, + → 2, − → 1, all confirmed against `GET /cart`; category screen
hydrates the stepper for items already in the cart; optimistic rollback
restores the Add button when `/cart/add` is aborted; admin layout-block Add
adds to the cart on the category screen; text-node warnings gone.

### Known pre-existing (web-preview only, NOT from this change)
Reanimated `entering={FadeInDown/FadeSlideIn}` stays at opacity 0 on
react-native-web, so `ShopLayoutRenderer` on shop-home and the buyer
Dashboard below the earnings card render blank in the web preview. Works on
device / Expo Go. Same root cause both places.

---

## Aug-2026 · Registration-fee revenue categorisation, CSV exports, GST maths

### Bugs fixed
1. **"Registration Fee Revenue showing 1 user only"** — `/admin/transactions`
   filtered by `type` CLIENT-side over a single 20-row page. Now filtered
   SERVER-side: `GET /api/admin/transactions?type=&source=&q=&limit=&offset=`
   (aggregation `$lookup` on users → `registration_source`). Offline/cash and
   UPI-manual joinings are visible again.
2. **`/admin/system-wallet` red screen** — `Cannot access 'load' before
   initialization` (TDZ: `load` was referenced in `useCallback` dep arrays
   ~200 lines before its declaration). `const load = useCallback` hoisted
   above `closeRefund`.

### New endpoints
- `GET /api/admin/transactions/summary?type=&q=` → `{total:{count,amount},
  by_source:{razorpay,upi_manual,offline_cash,unknown}}` (whole result set,
  not the loaded page) — drives the category tabs.
- `GET /api/admin/users?source=razorpay|upi_manual|offline_cash|unpaid`
- `GET /api/admin/users/source-counts`
- `GET /api/admin/export/registration-fees?source=` → CSV (reference,
  paid_on, name, member_id, email, phone, join_source, amount,
  gst_18_inclusive, net_excl_gst, status, razorpay ids, utr, sponsor).
- `GET /api/admin/export/users?source=` → richer CSV with `join_source` +
  `admin_approved` columns.

### GST business rule (owner decision, Aug-2026)
Entry GST = `fee × 18/118` is recognised **only for Razorpay-gateway
joinings**. UPI-manual / offline-cash / admin-approved joinings are NOT in the
GST ledger. Implementation is **derived** (no new ledger rows → zero risk of
double-count or wallet drift):
- `routes/finance.py` Group 3 = `registration_gst` (derived from Group-1
  razorpay registration revenue) + `other_gst` (service/POS `gst_collected`
  rows, EXCLUDING rows tagged `gst_kind:"registration_entry"` or whose
  description matches /registration|direct signup/i).
- Group-3 drilldown emits one synthetic `18.00` line per razorpay joining.
- `gst_payable` remains a liability subtracted in Company Net Worth.
- All entry-GST txn writers now tag `gst_kind:"registration_entry"`
  (`_credit_no_ref_signup_to_admin`, offline-create, `routes/upi_manual.py`).

### "Admin Approved" (was "Registration paid")
`PATCH /api/admin/users/{id}` with `registration_paid:true` now also stamps
`commission_triggered:true`, `admin_approved_only:true`, `admin_approved_at/by`
and writes an audit row — **guaranteeing no referral commission is ever paid
to the upline and no revenue row is created** for manually-approved accounts.

### Short references
`_short_txn_ref()` → `REG-4F9K2P` / `GST-…` / `PAY-…` / `WDL-…` (prefix map
per txn type). Shown in the list rows and the detail sheet ("Reference").

### Frontend
- New `src/source-tabs.tsx` — shared category pill bar (label + count),
  used by `/admin/transactions` and `/admin/users`.
- `/admin/transactions?type=registration_fee`: tabs (All/Razorpay/UPI
  manual/Offline), search, CSV button, per-row source badge + short ref +
  phone + member ID + gateway ref.
- `/admin/users`: tabs (All/Razorpay/UPI manual/Offline/Not approved) with
  DB counts, CSV button, per-row source badge; edit slide renamed to
  **Admin Approved** with the "no commission / no revenue" note.
- `/admin/system-wallet` Group 3 now shows "↳ Joining GST · Razorpay (N
  payments)", "↳ Other GST (services · POS)" and the exclusion note.

### Verified
16/16 pytest in `backend/tests/test_iter_jan2026_reg_revenue.py`
(report `test_reports/iteration_60.json`). Preview seed:
`backend/tests/seed_reg_revenue.py` (3 razorpay + 2 upi_manual + 2 offline
users, 30 filler payouts) → summary 7/₹826, razorpay 3/₹354, GST ₹54.
Screens verified in web preview after the TDZ fix.
