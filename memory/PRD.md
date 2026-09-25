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

---

## Aug-2026 · ₹118 becomes a SUBSCRIPTION (free tier + benefits card)

### Owner report
New users landed on the payment wall ("PAY TO ACTIVATE") with only a Pay
button and could never enter the app — even after admin approval.

### Business rules now
- ₹118 is a **subscription**, not a gate. `POST /api/payment/skip-subscription`
  records `subscription_skipped=true`; `app/index.tsx` + `app/login.tsx` route
  `unpaid && !subscription_skipped → /payment`, everyone else → `/(tabs)/shop`.
- **Admin approval never blocks entry** — `/pending-approval` gained a
  "Continue to the app" button and is no longer a redirect target from index.
- Free tier = browse + shop only. Wallet / cashback / referral earnings /
  withdrawals are member-only (`/withdrawals` already 400s for unpaid).
  Dashboard hides the Total-Earnings + Withdraw card; `/wallet` shows
  `SubscriptionLocked`; Shop / Dashboard / Profile show `SubscribeBanner`.
- Free users stay in the referral tree with zero commission (unchanged).
- **Admin Approved ON** (customer paid the admin by hand) now records ₹118 as
  `offline_cash` registration revenue + a `direct_added` system-wallet mirror,
  sets `registration_source/paid_at/admin_approved_*`, and keeps
  `commission_triggered=True` → still NO GST and NO referral commission.
  Idempotent (never a second fee txn).

### New UI kit — `src/subscription.tsx`
`SubscriptionHero` (gradient · "SUBSCRIPTION" · ₹118 · "Complete your
registration with ₹118"), `SubscriptionBenefits` (the 8 owner-specified
benefits), `SkipSubscriptionButton` (in-app Modal confirm — NOT Alert.alert so
it behaves the same on web + native), `SubscribeBanner`, `SubscriptionLocked`.
Used by BOTH payment screens (`app/payment.tsx` Razorpay and
`app/payment-upi.tsx` UPI-manual) so they never drift.

### Admin
`/admin/users` category tab labelled **"No subscription"** (key `unpaid`),
roster badges `₹118 PAID` / `NO SUB`, and a **Paid status** pill in the edit
slide next to the Admin Approved switch.

### Verified
5/5 pytest in `backend/tests/test_iter60_subscription.py` + full Playwright
pass (report `test_reports/iteration_60.json`). Test accounts:
`freetier1@test.com` (admin-approved → ₹118 paid) and `freetier2@test.com`
(skipped → free), password `Just@4me`.

---

## Sep-2026 · Phase 1 — Two account types + Admin Approved = referral switch

### Rules implemented
- **Only two account types**: `Subscriber` = Razorpay payment successful ·
  `Non-subscriber` = continued without subscription. UPI-manual & offline-cash
  removed from all account-creation paths (`/payment` no longer redirects to
  `/payment-upi`; `POST /admin/users/create` always creates a non-subscriber
  with `subscription_skipped=true`, `referral_enabled=false`, and writes NO
  fee / GST / system-wallet rows — so treasury + GST maths stay exact).
- **Paid status is immutable**: `registration_paid` removed from
  `AdminUserUpdate` and popped in `admin_update_user`. A Razorpay-paid member
  can never be shown unpaid again.
- **"Admin Approved" is now a referral-payment switch only** —
  `POST /admin/users/{id}/referral-approval {enabled, note}` (note ≥ 3 chars,
  mandatory). ON → sets `referral_enabled`, fires the L1..L10 cascade for paid
  subscribers. OFF → "refund done": `_clawback_referral_payouts()` debits each
  upline by the net paid, rolls back `total_earned`, tracks `refund_debt`,
  writes `refund_clawback` + `platform_fee_reversal` txns and marks the
  original payouts `reversed`. Every switch is pushed to
  `referral_switch_history` and surfaced in the Users CSV
  (`admin_approved`, `admin_approved_note/on/by`, `account_type`, `paid_status`).
- `_trigger_referral_commissions` now returns early unless `referral_enabled`
  is true; `/admin/approvals/{id}/approve` turns the switch ON.
- **One-time startup migration** `two_account_types_migration_2026_08`:
  legacy UPI-manual/offline members → non-subscriber (historical revenue rows
  KEPT), and `referral_enabled` seeded from the existing approval state
  (preview run: 10 converted, ON=3, OFF=24).
- Admin → Users tabs are now **All · Subscribers · No subscription** (Legacy
  only while legacy rows exist). Add-new-user modal lost the mark-paid switch,
  source chips and UTR field.

### Verified
10/10 pytest `backend/tests/test_iter61_two_account_types.py` (clawback
arithmetic verified to the rupee) + Playwright UI pass — report
`test_reports/iteration_61.json`. The one bug the tester found (immutability
patch had landed in the wrong function) is fixed and re-tested green.

### Remaining phases (owner-approved order)
2. Product image bugs (vendor→admin bin image, publish without re-upload,
   multi-image gallery select, product-detail gallery)
3. Admin Products vendor-first loading + one-click "publish all of vendor"
4. Smart-search suggestions in Add Product (item-wise unique, import price/images)
5. Vendor POS invoice ↔ web sync, cash summary, GST & tax return
6. Tablet (12") shop images + hero card alignment

---

## Jun 2026 — Phase 2 batch (iterations 62 & 63) ✅

### Fixed / built
- **Vendor product images missing in Admin bin** — root cause: `GET
  /api/products/{id}/image` 404'd whenever `is_published` was False, and
  vendor products are unpublished until approved. Publish gate removed.
  Admin product list also now surfaces gallery-only products (aggregation
  adds a `_gallery_n` count without shipping the base64 array).
- **Gallery multi-select** — new `pickAndFitImages()` in
  `src/image-fitter.ts`; wired into admin products + rich product editor.
- **Product detail** — cover image now leads the gallery (was last) and
  relative thumb URLs are resolved.
- **Smart search** — new `GET /api/products/search-suggest` groups by
  lower-cased product name and returns a price band + `vendor_count`.
  Shop-home has a debounced typeahead dropdown; results still list every
  published vendor listing.
- **Admin Products** — new `POST /api/admin/products/publish-all`
  (`{vendor_id?, publish}`) + "Publish all / Unpublish all" buttons with a
  confirm modal.
- **POS cash summary** — all POS day windows are now IST-based
  (`_ist_day_bounds`); cash-summary adds `total_collected` + `bills`. The
  vendor Cash screen sends the LOCAL date, not the UTC one.
- **Tablet / 12-inch** — the fake centred "phone frame" wrapper in
  `app/_layout.tsx` is deleted; product grid columns, layout-block
  columns and banner height all derive from `useWindowDimensions()`.
  Form screens (login/register) use a 560 px centred column.
- **Product grid 1-per-row bug** — percentage basis + pixel `gap` summed
  over 100%. All grids are now pure-percentage cells.

### Shop Layout spec (owner list)
- NEW **Spotlight** block: full-width immersive card ≈1/3 of the phone
  screen, product chip strip, CTA that only shows when a target is set.
- Brand slider: taps navigate, bigger tiles, label under the logo.
- Announcement strip: leading ⚡ icon removed.
- Product grid: Manual source only, no subtitle, no wishlist heart, shows
  ALL manually-picked products (`product_count` no longer caps manual).
- Horizontal slider: Manual + Category only, no subtitle, price + Add row.
- Content box: image is now 72 % of the card.
- Flash sale: Manual only, date+time picker with presets.
- Multi-product picker: search, per-vendor chips, select-all/clear,
  thumbnails. `product_count` / `product_ids` caps raised 50 → 500.
- Category screen: dead band above the grid removed, section heading
  added, client-side guard so only that category's blocks render.
- Cold-cache bug: freshly fetched layout was overwritten with `[]`.

## Jun 2026 — Phase 1 of the 16-item owner list (iteration 64) ✅

- **Layout-block "+" never added to cart** — `products.find()` returned
  undefined for products outside the screen's own list and we bailed. Now
  falls back to an id-only stub. Header badge uses the live `useShopCart`
  count so it updates instantly (mobile + tablet).
- **Category / sub-category blocks showed no products** —
  `/products/by-source` matched only the top-level `category` field, and
  case-sensitively. Now matches `category` / `sub_category` /
  `subcategory`, case-insensitive.
- **Vendor cover image** — single-select → multi-select; first pick becomes
  the cover, the rest append to the gallery (cap 10), preview paints
  immediately.
- **Admin → System Wallet Treasury** — "Add Direct-Added Money (UTR)"
  button, its modal and `submitDeposit()` removed (never reflected in bank
  tally / net worth).
- **Flash sale auto-hide** — expired blocks render nothing (server doc is
  preserved, so a new end time brings it straight back).
- **Category Circles** — MAIN categories only; per-block image override
  stored in `block.items` keyed by category name, so the master image in
  /admin/shop-categories is untouched.
- **Vendor dashboard slow + Cloudflare "could not parse response"** — root
  cause: `GET /api/vendor/me/products` returned every base64 cover plus the
  full `images[]` gallery (20-40 MB for 150 SKUs). List is now slim
  (`gallery_count`, thumbnail URLs, no `images`) and a new
  `GET /api/vendor/me/products/{id}` serves the full doc to the editor.

### Verified
`backend/tests/test_iter64_phase1_bugs.py` 10/10 + Playwright:
cart badge 1→4 live, /cart persists, spotlight CTA → /shop-category/General,
UTR button gone, treasury intact. Report `test_reports/iteration_64.json`.

### Remaining phases (owner-approved order)
2. Shop-Layout blocks styled for tablet; instant product-page open (no
   white screen); swipe polish (no green splash flash, lighter gesture,
   category highlight follows the screen).
3. Product variants — Fashion sizes with the correct chart per product type
   (shoes/slippers UK-EU numbers, apparel S-XXL, inches where relevant) with
   per-size stock/price; mobiles RAM/ROM with price deltas.
4. Backup & restore — vendor-only Products export/import (clone a shop's
   catalogue into another vendor login, then edit qty/price/delete), plus a
   full A-to-Z app backup file (users, products, sales, invoices, chat,
   service, wallet maths) with wipe-replace / merge chosen at upload.
5. Maps & server — vendor Delivery Radius edit not saving; customer
   "Deliver to" map missing pincodes the vendor radius map captures (make
   both use one engine).

### Notes for the next agent
- Owner's `lee@gmail.com` vendor login does NOT exist in the preview DB
  (production only). Use `testvendor@test.com / Test@1234`.
- Owner runs a separate PRODUCTION deployment — always ask whether a
  reported bug is in PREVIEW or PRODUCTION.

## Jun 2026 — Phase 3: PRODUCT VARIANTS (iteration 65) ✅

Owner choices: 1a stock per variant · 2c both price modes · 3 all charts ·
4a size required + size guide · 5 no uploaded chart image.

### Data model (products)
```
variant_chart       "" | apparel | footwear_uk | footwear_eu | footwear_kids
                    | waist_in | kids_age | free_size | ram_rom | custom
variant_price_mode  "extra" (base + delta) | "absolute" (full price each)
variants            [{id,label,sku,stock,price_extra,price_abs,price,active}]
has_variants        bool
base_price          the price the vendor typed (so "extra" deltas survive edits)
stock               DERIVED = sum of active variant stock
price               DERIVED = cheapest BUYABLE variant  → shop shows "from ₹X"
```
Keeping `stock` / `price` derived means every existing stock badge, low-stock
warning, price filter, POS screen and out-of-stock query works untouched.

### Backend
- `core/variants.py` (NEW) — chart catalogue (9 charts with real measurement
  tables), `normalize_variants` (de-dups labels, drops blanks, clamps
  negative stock), `apply_variants_to_payload`, `find_variant`,
  `effective_line_price`.
- `GET /api/product-variant-charts` — server is the single source of truth so
  app / admin / web can't drift.
- Vendor + admin product create/update run the normaliser.
- `GET /api/products/{id}` ships `variants[{id,label,price,stock,in_stock}]`
  (sold-out options included, flagged) plus `variant_guide`.
- List endpoints expose `has_variants` / `variant_count` only (no heavy array).
- Cart rows are keyed by (user, product, variant). Adding without a size →
  400 `variant_required` **with the option list**; sold-out → friendly 400.
  `/cart/remove` with a variant removes one row, without removes all.
- Checkout decrements `variants.$.stock` AND the product total in ONE
  conditional update (oversell-proof) and rolls both back on failure. Order
  items carry `variant_id` + `variant_label` + the variant price.

### Frontend
- `src/variant-editor.tsx` (NEW) — chart chips → price-mode chips → tap the
  sizes you stock → per-row stock & price, with a live "customers will see
  this size guide" preview. Sits between Stock and Category in the product
  editor; the product Stock field becomes read-only and shows the computed sum.
- Product page: SELECT SIZE card (sold-out struck through + untappable),
  headline price "from ₹499" → the picked option's price, qty capped at the
  variant's stock, Add-to-Cart blocked until a size is chosen, and a Size
  guide sheet with the measurement table (selected row highlighted).
- Cart: green size pill per line, variant unit price, per-variant remove.
- Shop cards: variant products show **SELECT** (opens the picker) instead of
  a "+" that the API would reject — on the shared card, Product Grid blocks
  and Horizontal Slider blocks.

### Verified
`backend/tests/test_iter65_variants_phase3.py` 16/16 (incl. absolute mode,
base-price recompute, de-dup, oversell race, rollback) + browser: size
selector, sold-out strike, ₹549 flip, size guide, cart XL pill, SELECT card
button, and a real COD checkout taking XL 2→0 / total 10→8 with
`variant_label: "XL"` on the order line. Report `test_reports/iteration_65.json`.

### Still to build (owner-approved order)
- **Phase 2** — Shop-Layout blocks styled for tablet; instant product-page
  open (no white screen); swipe polish (no green splash flash, lighter
  gesture, category highlight follows the screen).
- **Phase 4** — vendor-only Products export/import (clone a catalogue into
  another vendor login, then edit qty/price/delete) + full A-to-Z app backup
  with wipe-replace / merge chosen at upload.
- **Phase 5** — vendor Delivery Radius edit not saving; customer "Deliver to"
  map missing pincodes the vendor radius map captures (one shared engine).

---

## Sep 2026 — Phase 2 (UI polish) + Phase 4 (Backup/Restore) + Phase 5 (Maps & payload) ✅ · iteration 66

### Phase 2 — UI/UX polish
- **Tablet layout** — `src/content-width.tsx` (NEW): the app renders into a
  centred column capped at `TABLET_MAX_WIDTH = 760` on tablets (owner's choice:
  "keep 2–3 columns, centre with max-width"). `TabletContainer` in
  `app/_layout.tsx` supplies it; every width-aware component (banner slider,
  spotlight, product grid, product hero) reads `useContentWidth()` instead of
  the raw window width, so blocks stop stretching. Phones and desktop web
  (≥1024, DesktopShell) are untouched. Verified at 834×1112 → centred, 3-up grid.
- **No more green flash** — the root `Stack` painted `#143D2E` (splash green)
  behind every screen transition. Navigator background is now `colors.background`
  and the bottom tabs get `sceneStyle` with the same colour.
- **Instant product open** — `src/product-preview.ts` (NEW) LRU cache. Cards
  stash name/price/cover before navigating; `/product/[id]` seeds state from it
  and paints on the first frame, hydrating the rest in place (size picker shows
  a placeholder, buy buttons stay inert until the real doc lands).
- **Lighter swipe** — `useSwipePager` claims at |dx|>14 (was 24), commits at
  |dx|>40 or |vx|>0.22, and requires the drag to be clearly horizontal.
- **Category highlight follows the swipe** — the sub-category strip on
  `shop-category/[name]` auto-centres the active chip.

### Phase 4A — Vendor catalogue backup  (`routes/backup.py`)
- `GET /api/vendor/me/catalogue/export?offset&limit` (limit ≤ 25) — paged, so a
  photo-heavy catalogue never travels in one oversized response. Ownership
  fields (`id`, `vendor_id`, `store_*`, delivery zone, counters) are stripped.
- `POST /api/vendor/me/catalogue/import` — `{products, mode: merge|replace,
  first_chunk}`. Re-stamps a new id + the importing vendor's identity and
  delivery zone, normalises images + variants, and lands everything as
  **hidden drafts** (`is_published=false`, `restored_from_backup=true`).
  `replace` wipes that vendor's products on the first chunk only.
- UI: `app/vendor/catalogue-backup.tsx` (Download / Choose file / Merge vs
  Replace with a destructive confirm), reachable from the Products tab row and
  the empty state of the vendor dashboard.

### Phase 4B — Full app backup, merged into ONE admin screen
- `GET /api/admin/backup/manifest`, `GET /api/admin/backup/dump?collection&offset&limit`,
  `POST /api/admin/backup/restore` (`merge` = upsert by id, `wipe` = delete then
  insert; 6-digit **Danger PIN** required; audit-logged). super_admin only.
  Excluded: `db_snapshots`, `db_snapshot_chunks`, security events, analytics,
  caches, and `pincodes` (reference data, opt-in).
- Money is restored exactly as in the file — it's a data replay, no commission
  or payout logic runs (owner's choice).
- **Merged screens** — `admin/backups` is now the single "Data backups" screen
  with two tabs: **File backup** (`src/app-backup-panel.tsx`) and
  **Snapshots**. `admin/backup-file` is a redirect for old links.
- **Snapshot engine rewritten** (`server.py`): the old one crammed the entire
  DB into ONE Mongo doc (16 MB cap → silently degraded to a useless
  "metadata-only" backup) and covered only 19 hardcoded collections. Now it
  streams into `db_snapshot_chunks` (≤200 rows / ~6 MB per chunk) with a small
  index doc, covers **all 53 collections** (same list as the file backup),
  restores chunk-by-chunk (legacy `data` snapshots still restorable), and prunes
  auto snapshots harder (`BACKUP_AUTO_RETENTION=6`) since each is a full copy.

### Phase 5A — ONE delivery-zone engine  (`core/delivery.py` NEW)
- `vendor_zone()` reads coordinates from flat `lat`/`lng` **or** GeoJSON
  `location`; `zone_covers_pincode()`, `zone_covers_point()`, `vendor_covers()`,
  `eligible_vendor_ids()`.
- **Root-cause fix** for "the vendor's radius map covers this pincode but the
  customer sees nothing": with no GPS fix the radius rule was skipped entirely.
  The engine now resolves the **pincode centre** (geocoded once via Nominatim
  and cached onto the `pincodes` row) and runs the same radius test →
  `reason: "radius_pincode_centre"`.
- `products_public._eligible_vendor_ids` (and therefore the shop filter, the
  category screens and the checkout guard) delegates to it.
- **Vendor edits now save**: `vendor_edit_requests` uses `exclude_unset`
  (explicit `null` radius / empty pincode list used to be dropped, so a vendor
  could never switch the radius off), the app always sends the pincode array,
  and approving an edit keeps `store_pincode` + flat `lat`/`lng` in sync with
  the new `location` (a moved shop used to keep serving its old area).
- New: `GET /api/vendor/me/delivery-zone`, `…/check?pincode=`,
  `GET /api/delivery/check?pincode=&lat=&lng=`. The vendor Request-Edit screen
  shows a **"My live delivery zone"** card + pincode tester.

### Phase 5B — Cloudflare "could not parse response"
- Root cause: `GET /shop-layout` and `/admin/shop-layout` inlined base64
  artwork — up to 4 MB per image, 30 slides per block, 200 blocks. Lists now
  return `/api/shop-layout/{id}/image` and `…/items/{n}/image`; the bytes are
  served on demand with a 1-day cache. Saving a block back with that URL is
  treated as "image unchanged" (matched by slide index) so nothing is wiped.
- Frontend resolves those relative URLs via `resolveImageUrl` in the renderer
  and the admin layout screen.
- Added an **oversized-response watchdog** middleware: any response > 2 MB is
  logged with its path, so the next offender names itself.

### Verified
`tests/test_iter66_catalogue_backup.py`, `test_iter66_app_backup.py`,
`test_iter66_delivery_engine.py`, `test_iter66_layout_payload.py`,
`test_iter66_snapshot_engine.py` (53 collections, 34 chunks, lossless restore)
all PASS, plus the testing agent's `test_iter66_edge_cases.py` 11/11. Browser:
vendor download → "✅ Backed up 11 products", admin download → "✅ Saved 890
records across 53 collections", merged Data backups tabs, tablet 834×1112
centred column.

### Still open
- File **restore** (upload) paths are backend-verified; the file-picker step
  needs a human pass on a real device / browser.
- Phase 2 leftovers the owner said are already fixed: Product-Grid "+" add,
  vendor gallery multi-select.
- Backlog: multi-vendor order splitting, wallet+COD combo, device login
  history, Razorpay (deferred).

### Sep 2026 — Product page "advanced look" redesign (owner request, iteration 66b)
Design blueprint: `/app/design_guidelines.json` (personality: iOS-Native Clean).
Implemented in `app/product/[id].tsx`:
- **Hero card** — was a full-bleed square with `resizeMode: "cover"`, which
  sliced the sides off phone photos (owner's screenshot). Now an inset,
  elevated white card sharing the page's left/right edge, radius 20, 1:1
  canvas, each slide `contain`-fitted with 14px breathing room. Gallery pages
  are CARD width (`heroW = contentWidth − 2×screen`) so paging lands centred.
  Wishlist FAB is 44×44, the pager shows both dots (brand green) and a
  translucent "1/n" pill, and the thumbnail strip (48×48, 2px active border)
  now lives INSIDE the hero card.
- **One box recipe** — `styles.card` / `tableCard` (surface, radius 16, 1px
  border, 16px padding) for title+price, variants, quantity, details, specs,
  description, reviews; `infoWrap` gives a 12px rhythm and the single 16px
  outer margin, so every box lines up on the same edge.
- **Text alignment** — key-value rows keep label-left / value-right for short
  values, but STACK (label above, value left-aligned) when the value is > 24
  characters (SIM strings, network band lists) instead of wrapping raggedly;
  empty values render "—" (fixes the blank "Custom UI" row). Spec tables reuse
  the same `DetailRow`. Price shows "STARTING FROM" as a micro-label above the
  amount so the number keeps its baseline.
- **Variant chips** — selected is a green outline + `brand100` tint (not a
  filled slab), out-of-stock is dashed + struck through, and every chip carries
  its own price hint so options can be compared without tapping.
- **Sticky bar** — 50pt buttons, 12px gap, top shadow/elevation, and
  `insets.bottom` safe-area padding.

---

## Sep 2026 — Reset centre, service chat fee, layout save & orders bug (iteration 67)

### Reset centre (replaces the three blind Danger-Zone buttons)
New screen `app/admin/reset-center.tsx` (Admin → More → Reset centre). Old
`Wipe all users` / `Reset shop products` / `Reset app to zero` rows + modals in
`admin/more.tsx` were deleted, along with the `/admin/system/wipe-users`
endpoint.

Owner's rule enforced everywhere: **no in-app snapshot for resets — the backup
FILE must be downloaded first, and restores happen only by uploading that file**
(Admin → Data backups → File backup). The wipe button stays disabled until the
download completes, and the API rejects any reset without `backup_downloaded`.

- **One account** — search + pick a user → per-account manifest → download →
  PIN → **Clear data** (keeps the login, wallet → ₹0) or **Delete user**.
  `POST /api/admin/system/account-reset {user_id, mode: clear|delete,
  danger_pin, backup_downloaded}`.
- **One shop** — pick a vendor → `POST /api/admin/system/reset-shop-products
  {vendor_id, …}` clears THAT vendor's products, reviews/cart/questions for
  them, their POS + online sales/invoices, and scrubs their product ids out of
  admin layout blocks (empty blocks removed). Other vendors untouched.
- **Whole app** — `POST /api/admin/system/wipe-all` rewritten to walk EVERY
  collection (was a hand-maintained list of ~22, so chat, POS invoices, wallet
  ledgers, layouts, services, wishlists all survived a "reset to zero").
  Keeps `settings`, `branding`, `db_snapshots*`, `pincodes` and the seed
  super-admin (wallet/counters zeroed). Still needs PIN + typed "RESET".
- **Per-account backup** — `GET /api/admin/backup/account/{id}/manifest` and
  `/dump` in `routes/backup.py`. Ownership is found by LINKING UP every
  plausible id/email field (`scope_query`) instead of a hardcoded map, so new
  collections are covered automatically. The file uses the app-backup envelope
  so the existing File-backup restore merges it straight back.

### Service unlock fee + chat (owner: one global fee, 0–100)
- **Chat after paying was broken**: `routes/chat.py` looked for
  `customer_id` + a `status` field on `phone_reveal_invoices`, but a paid
  reveal writes `user_id` and no status → every paying customer still got
  "reveal the phone first". Now matches `user_id`/`customer_id`, no status.
- `phone_reveal_fee or 1.0` in `server.py` swallowed a deliberate ₹0, so the
  fee could never be turned off. Read as configured; a ₹0 total skips the
  wallet debit, the transaction rows and the admin bucket credit entirely.
- "Start Chat" on `services/[id]` is always visible: free when the fee is ₹0
  or already unlocked, otherwise it reuses the pay sheet and drops the
  customer into the thread after payment (`payIntent`).
- Admin → Service Analytics has an **UNLOCK FEE (PHONE + CHAT)** card:
  edit ₹0–₹100, shows the GST-inclusive total, saved via `PUT /admin/settings`.

### Bug fixes
- **Free users' orders** — the whole lower dashboard (YOUR NETWORK, QUICK
  ACTIONS, My orders row + recent-orders hero, RECENT ACTIVITY) was inside the
  `expanded &&` earnings block, which unsubscribed users can never open
  (their earnings card is hidden). Free-tier users saw an empty dashboard and
  had no route to My Orders. Only the earnings charts collapse now. Also
  removed a duplicate style key in that file.
- **Shop layout "save failed"** — layout images are now compressed
  server-side on create/patch (`compress_data_url`), so an oversized photo is
  downscaled instead of failing the 4 MB field cap; managed-image-URL index
  parsing hardened with a regex. Verified: every block type saves, and 1–5 MB
  payloads pass through the edge proxy.

### Verified
`tests/test_iter66_reset_centre.py` (link-up manifest, clear/delete, scoped
vendor reset, all three wipe-all guards) PASS; chat/fee flow script PASS
(403 before pay → 200 after pay → free chat at ₹0);
`test_iter66_layout_payload.py` PASS; browser: free-tier dashboard now shows
My orders + recent orders, Reset centre 3 tabs with per-account (3 records)
and whole-app (920 records) manifests and the download gate.

---

## Sep 2026 — Sub-role landing, device login history, dashboard avatar (iteration 68)

### Device login history + new-device alerts (NEW)
- `core/login_history.py` — `record_login(user, request, sid, method)` writes a
  `login_history` row on every sign-in (password + Google) using the
  `X-Device-FP` fingerprint the app already sends, a new `X-Device-Name`
  label (expo-device model · OS, or a browser name on web), IP, session id and
  `method`. Capped at the newest 50 rows per user, indexed on
  `(user_id, created_at)`.
- A fingerprint the account has never used raises an **alert**: an in-app
  notification "New device signed in" (kind `security`, `action_url
  /login-history`) plus a best-effort push. The FIRST login on an account is
  deliberately NOT alerted.
- `routes/login_history.py`:
  `GET /api/users/me/login-history` (rows + `is_current` / `is_active` /
  `active_devices`), `POST /api/users/me/login-history/{id}/revoke`
  (400 if it's this device), `POST /api/users/me/login-history/revoke-others`
  (keeps the caller alive), `GET /api/admin/users/{id}/login-history`
  (super_admin only).
- `get_current_user` now exposes the token's sid as `user["_sid"]` so those
  routes can tell "this device" apart; `serialize_user` strips `_sid` **and**
  `password_recovery_ciphertext` (the Fernet copy used to ride along on
  `/auth/me`).
- UI: `app/login-history.tsx` — device rows with platform icon, time, IP,
  "THIS DEVICE" / "SIGNED IN" pills, per-row Sign out and "Sign out all other
  devices". Reachable from Profile → **Login activity**.

### Scoped manager landing bug (was: 403 straight after login)
- `login.tsx` sent every admin to `/admin/home` and `index.tsx` to
  `/admin/shop` — both hidden and API-blocked for the four scoped manager
  roles, so a promoted manager landed on a dead screen. New shared
  `src/admin-roles.ts` (`SCOPED_ADMIN_ROLES`, `isScopedAdmin`, `adminLanding`)
  is now the single source for the tab layout AND both redirects → managers
  land on `/admin/manager-home`.
- `admin/admins.tsx` no longer resets the role picker to the legacy
  `manager` value after creating/promoting.
- `ADMIN_AREAS` entries may now be **method-scoped** (`"GET /admin/products"`).
  Used so a Shop Layout manager can pick products into blocks while still
  being unable to create, edit or publish a product.

### Dashboard avatar
The top-right initials circle was a plain `View`. It is now a 44×44
TouchableOpacity → `/(tabs)/profile` with `hitSlop` and
`pointerEvents="none"` on the inner `Text` (RN-web swallowed the tap on the
nested text node).

### Verified
`tests/test_iter68_login_history.py` 17/17 PASS (login history + revoke rules,
new-device notification only on the 2nd fingerprint, all four scoped roles
own-area-200/others-403, layout_manager GET products 200 / POST 403, password
reveal 403 for managers, `/auth/me` leak check, multi-vendor split
`SC-…-1`/`SC-…-2`). Browser: `/login-history` renders with the THIS DEVICE
pill, `manager-home` shows only "My section"+"Profile" tabs, My Orders shows
the "1 checkout · 2 sellers" group with both sub-orders, and the dashboard
avatar now navigates to Profile.
Seed: `tests/seed_iter67_managers.py` (4 manager logins, `Manager@123`).

---

## Sep 2026 — Session stability, tray notifications, admin orders, services polish (iteration 69)

Owner's batch report: random auto-logout, fingerprint quirks, slow logout,
Admin→Users crash, services near-me placement, chat/order pushes missing,
products-manager vendor filter empty, layout-manager can't see the live shop,
admin orders too thin.

### 1. "The app logs me out by itself" (root causes, all fixed)
- `auth.tsx refresh()` wiped the tokens on **any** `/auth/me` failure — a
  network blip, a 5xx or a cold-start timeout signed the user out. It now
  only signs out on 401/403 and keeps the session on transport errors.
- `POST /auth/refresh` rotates the refresh token. If the phone never received
  the response (app killed, weak signal, two parallel refreshes), its stored
  token was already dead → `session_revoked`. `rotate_session` now records the
  swap and `rotation_target()` lets a token rotated within
  `ROTATION_GRACE_SECONDS` (default 300) be replayed once, returning the
  CURRENT session. A never-issued sid still 401s.
- Repeated logins on one phone used to fill the 10-slot session pool and evict
  other devices. `record_login` now pulls the sids that the SAME
  `X-Device-FP` used before, so it's one live session per device.
- **Logout is instant**: local tokens/user are cleared first and
  `/auth/logout` is fired in the background with an explicit Authorization
  header (the token is captured before the wipe) and an 8 s timeout.

### 2. Fingerprint login
- `api.ts` now calls `syncBiometricTokens()` after every successful refresh,
  so the SecureStore copy never goes stale — that stale copy was why
  fingerprint fell back to "please login with password once".
- `login.tsx` gives **3 scan attempts** (`MAX_BIO_TRIES`), counting down in
  the error line, then reveals the password form instead of re-prompting.

### 3. Admin → Users force-close (P0)
`UserEditModal` declared the password-reveal `useState`s AFTER
`if (!user) return null`, so the hook count changed between renders →
"Rendered more hooks than during the previous render" red screen on every
user tap. Hooks moved above the bail-out; `init()` also resets the revealed
password when switching users.

### 4. Chat + order notifications in the phone tray
- `core/notifications.create_notification(..., push=True)` is now the
  DEFAULT: every bell row also goes to the tray. Call sites that already
  batch their own `send_push` (order created, order status, chat) pass
  `push=False` so nothing double-fires.
- Chat pushes were skipped whenever the recipient had a live socket — on
  Android the socket survives backgrounding (location service), so pushes
  never arrived. The WS now carries `{"type":"viewing","thread_id":…}`
  (sent by `chat/[id].tsx` on focus/AppState, re-announced on reconnect) and
  the push is suppressed ONLY when that exact thread is on screen.
- Tapping a tray notification routes to its `action_url`
  (`addNotificationResponseReceivedListener` in `app/_layout.tsx`).
- ⚠️ Tray delivery needs a real build: `EMERGENT_PUSH_KEY` is a placeholder
  in preview and Expo Go can't receive native pushes.

### 5. Admin sub-roles
- `ADMIN_AREAS` entries may be method-scoped (`"GET /admin/vendors"`):
  products_manager can now READ the vendor roster (its "Filter by vendor"
  picker was empty) without gaining vendor write access; layout_manager can
  READ products for layout blocks.
- layout_manager (and every scoped role) gets a **Shop live preview** row on
  `manager-home` → `/admin/shop`; the quick-manage chips on that screen are
  filtered per role so nobody taps into a 403.

### 6. Admin → Orders
- `GET /admin/orders` rows are enriched by `_attach_order_parties()` with
  buyer name/email/phone and seller shop/email/phone (one batched user query).
- New `GET /admin/orders/{id}` → `{order, siblings}`.
- Cards show the order number, customer + phone and the seller, and open an
  **order details sheet**: product hero preview, CUSTOMER / SELLER /
  PAYMENT (wallet vs cash) / ITEMS / DELIVERY ADDRESS boxes and a
  "SAME CHECKOUT" list for multi-vendor splits. Phone is shown in full
  (owner's choice).

### 7. Services UI
- The services header (title + search + pincode + **Use my location**) is one
  sticky block, so near-me sits ABOVE "Browse by category" and stays put.
  The near-me card is a two-line row with a clear/chevron affordance.
- Provider profile bottom bar rebuilt: info line on top, two equal-width
  50pt buttons below (Get number · Start Chat) with safe-area padding — it
  used to overflow. The pay sheet's T&C row is now a bordered card that
  tints when checked.

### Verified
`tests/test_iter69_session_orders_push.py` 19/19 PASS (refresh grace, device
eviction, logout scope, method-scoped RBAC, order enrichment + detail,
push default/suppression, WS viewing registry) + Playwright: near-me pinned
above the grid at 390 px, equal CTA buttons, admin order detail sheet with all
sections, layout-manager shop preview without 403, admin user rows open with
no crash. Report `test_reports/iteration_69.json`.
Biometric + tray push are native-build-only — code paths asserted, real
delivery needs a published build.

## Sep 2026 (later session) — Legal pages + Chat Records

### 8. Legal & Policies (admin-editable, one source of truth)
- `legal_pages` kinds are now: `about`, `contact_us`, `privacy`, `refund`,
  `terms`. `about` was previously hardcoded in `app/legal/about.tsx` — that
  screen now renders `<LegalPageView kind="about" />`, and the admin editor
  (`app/admin/legal-pages.tsx`) has an "About us" tab.
- Contact was TWO screens (`/legal/contact` hardcoded pre-login vs
  `/legal/contact-us` admin-editable post-login). Unified into
  `/legal/contact`: admin text via `LegalPageView` + a new optional `footer`
  prop carrying the support-ticket / track-ticket cards. `contact-us.tsx`
  deleted; `more.tsx` repointed. Login footer now lists
  Terms · Privacy · Refund · Contact · About.

### 9. Admin → Chat = two groups (owner: legal/court compliance)
- `app/admin/chat.tsx` is now a wrapper with a segmented switcher:
  1. **Message users** → the normal `ChatListScreen` (unchanged; admin can
     still text anyone).
  2. **Chat records** → `src/chat-audit.tsx`, SUPER-ADMIN ONLY, read-only.
     Non-super admins never see the switcher.
- `backend/routes/chat_audit.py` (all `require_admin_role("super_admin")`):
  - `GET /admin/chat-audit/threads?q=` — every conversation (user↔user AND
    admin↔user) with FULL identities (name/email/phone/ref/role), message,
    deleted and photo counts.
  - `GET /admin/chat-audit/threads/{id}/messages` — whole transcript incl.
    deleted messages, image blobs stripped (`has_image` flag only).
  - `GET /admin/chat-audit/messages/{id}/image` (bytes) and
    `/image-data` (data URL, used by the app so `<Image>` works on web).
  - `GET /admin/chat-audit/threads/{id}/export` and
    `GET /admin/chat-audit/users/{id}/export` → `{filename, content}` plain
    text; the app saves it with `src/download.ts`. Format: confidential
    header, lettered participants with full contact details, then
    `[n] dd-mm-yyyy hh:mm:ss AM IST  Sender (A) -> Other (B) [flags]` with
    flags `EDITED`, `PHOTO attached — visible in app`, `REPLY to #n`,
    `DELETED at … — content recovered / not recoverable`.
  - Every read and export writes an `audit_logs` row
    (`chat_audit.read_thread` / `.export_thread` / `.export_user`).
- **Deleted-message archive**: the three delete paths in `routes/chat.py`
  (`delete_message`, `clear_thread_messages scope=everyone`,
  `delete_for_everyone`) now copy the original into `audit_text` /
  `audit_image_data_url` and stamp `deleted_at` / `deleted_by` before wiping
  the live fields. Participants still see "deleted". Messages deleted BEFORE
  this change are NOT recoverable and are reported as such.

### 10. Suspicious-word flagging (chat review queue)
- `core/chat_flags.py`: `ABUSE_WORDS` (also the send-time block list used by
  `routes/chat.py`) + ~60 `SCAM_PHRASES` (OTP/PIN/CVV harvesting, QR & money
  transfer bait, guaranteed-income / crypto / lottery bait, off-platform
  pulls). `scan(text)` → `{categories, words}`.
- `chat_flags` collection: one upserted doc per message
  (`kind="message"`) plus `kind="blocked_attempt"` rows capturing abusive
  text the send filter REJECTED (never delivered, but the attempt is the
  signal). Fields: thread_id, message_id, sender_id, categories, words,
  text, status open|reviewed, reviewed_by/at.
- Scam wording is deliberately NOT blocked (evidence + blocking only teaches
  rephrasing); abuse stays blocked at send AND flagged.
- Admin endpoints (super admin only):
  `GET /admin/chat-audit/flags?status=open|reviewed|all&category=`,
  `POST /admin/chat-audit/flags/{id}/review`,
  `POST /admin/chat-audit/rescan` (re-scans all history incl. archived
  deleted text; idempotent).
- Chat records UI gained a "Conversations | ⚠ Flagged (N)" switch, a
  To review / Reviewed filter, cards with ABUSE / SCAM / "BLOCKED — not
  delivered" badges + matched words + Open chat / Mark reviewed, an
  "⚠ N to review" chip on conversation cards and a SCAM/ABUSE badge on the
  offending bubble inside the transcript.

### 11. Multi-vendor split — buyer-facing UI (Jun 2026, verified iteration 72)
Backend already created ONE order per vendor per checkout (shared `group_id`,
`split_index`/`split_count`, per-sub-order `wallet_paid`/`cod_due`). What was
missing was buyer visibility BEFORE paying:
- `GET /api/cart` now returns `vendor_name` on each line's `product`
  (single batched users lookup).
- `server.py::_vendor_name()` aligned to the same priority as
  `routes/cart.py` (vendor_business_name > shop_name > name) so the seller
  name in the bag matches the name printed on the placed order.
- `app/cart.tsx`: bag grouped by seller. With 2+ sellers it shows
  `cart-split-notice` ("Items from N sellers — this will be placed as N
  separate orders…") and a per-seller header with that seller's subtotal.
  Single-seller carts render exactly as before. Removed a duplicate
  `useFocusEffect` that loaded the cart twice on focus.
- `app/checkout.tsx`: ORDER SUMMARY grouped by seller with ORDER 1 / ORDER 2
  badges + per-seller subtotals and `checkout-split-notice`. ScrollView
  bottom padding grows to 240 in `wallet_cod` mode so the sticky footer
  stops covering the split quick-chips.
- Wallet+COD combo verified: wallet money is allocated across sub-orders in
  cart order (first seller fully paid → `wallet`, next → `wallet_cod`
  partial_cod / `cod` pending_cod). `/orders` shows the group header
  "1 checkout · N sellers" with per-order seller name, order number
  SC-XXXXXX-1/-2 and the wallet vs cash breakdown.
- Vendor isolation confirmed: each vendor sees only its own sub-order.
- API-level regression test: `backend/tests/test_multivendor_split_ui.py`.

### 12. Cart quantity, Razorpay online payment, Reorder (Jun 2026, iterations 73–74)
**Cart quantity stepper**
- `app/cart.tsx` bag lines have a − / qty / + stepper (`qty-minus-*`,
  `qty-value-*`, `qty-plus-*`) hitting `POST /cart/adjust`. At qty 1 the
  minus becomes a trash icon and deletes the row.
- `routes/cart.py::cart_adjust` now also caps PLAIN (non-variant) products at
  the product's stock → 400 "Only N left in stock".

**Razorpay online payment for orders (MOCK mode until keys are added)**
- `core/razorpay.py` (new): shared creds (admin settings > env > mock),
  HMAC `verify_signature`, `create_order`, `fetch_payment`.
  `server.py::get_razorpay_creds` is now a thin wrapper over it so the
  registration-fee flow and the order flow can never diverge.
- `routes/order_payments.py` (new), collection `order_payments`:
  `POST /orders/payment/start` (prices the cart server-side, computes the
  online remainder, creates the Razorpay order, one open attempt per user),
  `POST /orders/payment/verify` (HMAC + live cross-check of status/amount),
  `GET /orders/payment/pending` (a paid-but-unplaced attempt so the app can
  resume instead of charging twice).
- `POST /orders/checkout` accepts `payment_method: online | wallet_online`
  plus `payment_id`. It consumes the verified attempt exactly ONCE
  (`consumed_order_group`), so a reused/unverified payment is rejected 400.
  Allocation per sub-order is wallet → online → COD; `online_paid` is stored
  on every order. Fully-prepaid sub-orders (cod_due == 0) credit vendor +
  platform immediately — the payout gate is now "no cash outstanding",
  not "paid_via == wallet".
- Cancellation refunds `wallet_paid + online_paid` to the wallet
  (both in the admin status route and `POST /orders/{id}/cancel`).
- `app/checkout.tsx`: "Pay Online" option + "Use my wallet balance too"
  switch → wallet+online combo reusing the split box (right column becomes
  PAY ONLINE). Gotchas fixed in iteration 74: the wallet slider is capped at
  `total − ₹1` so the gateway always has something to collect, the combo
  defaults to a 50/50 split when the wallet could cover everything, and
  dragging the wallet to the full amount places a plain wallet order instead
  of calling the gateway. A yellow resume banner finishes a captured-but-
  unplaced payment.
- `src/notify.ts` (new): `Alert.alert` is a NO-OP on react-native-web, so
  every cart/checkout/orders message was invisible in the browser preview.
  `notify()` keeps the native dialog and falls back to
  window.alert / window.confirm on web. Use it (not Alert.alert) for any new
  user-facing message in those screens.

**Reorder**
- `POST /orders/{order_id}/reorder` re-adds each line, SKIPPING delisted /
  out-of-stock / "seller no longer delivers to you" items (checked with the
  shop's own `_eligible_vendor_ids`) and returning
  `{added, skipped:[{name,reason}], cart_count}`; 400 with
  `detail.code = "reorder_unavailable"` when nothing can be added. Quantities
  never exceed available stock, and a second reorder stacks up to that cap.
- `app/orders.tsx`: "Reorder" button on every order card (`reorder-<id>`)
  → dialog listing added + skipped with an "Open bag" action. New pay labels
  "Paid online" / "Wallet + Online"; the invoice modal breaks payment into
  wallet / online / cash rows. `app/admin/orders.tsx` shows a "Paid online" row.
- Tests: `backend/tests/test_online_payment_reorder.py` (stepper + stock cap,
  mock start/verify, unverified rejection, wallet+online split across two
  vendors, reuse blocked, reorder) and
  `backend/tests/test_multivendor_split_ui.py`.

### 13. Backup: streamed download + one-account restore (Jun 2026, iteration 75)
Owner report: the whole-app backup died on Android with
`java.lang.OutOfMemoryError: Failed to allocate a 126097912 byte allocation`
from `FileSystem.writeAsStringAsync`, and the Reset centre could take a
one-account / one-shop backup but offered no way to restore-and-merge it.

- Root cause: the app paged through every collection, stitched a ~120 MB JSON
  string in JS, then asked the native module to write that string — two full
  copies of the backup in the phone's heap.
- `routes/backup.py` now streams the finished file:
  `GET /admin/backup/file` (whole app) and
  `GET /admin/backup/account/{user_id}/file` (one account/shop) return a
  `StreamingResponse` that emits the JSON envelope and then documents 50 at a
  time, with `Content-Disposition: attachment`. Same `slangcart.app-backup`
  format, so the existing chunked `POST /admin/backup/restore` still replays
  them. Nothing is buffered end-to-end on either side.
- `src/download.ts::downloadServerFile()` (new): native streams to disk with
  `FileSystem.downloadAsync` then opens the share sheet; web fetches with the
  auth header and triggers a browser download. `downloadText` stays for small
  CSV/TXT exports.
- `src/backup-restore-card.tsx` (new, shared by Admin → Data backups → File
  backup AND Admin → Reset centre): picker + merge/wipe + Danger PIN +
  chunked replay. An ACCOUNT-scoped file is ALWAYS merged and never sends the
  empty-collection wipe calls — restoring one shop can't delete other
  sellers. On native it refuses files > 40 MB with "restore this from a
  browser on a computer" instead of crashing (JSON.parse of a 120 MB string
  is the same OOM).
- Reset centre now also uses `notify()` (window.alert/confirm on web) so its
  errors and confirmations are visible in the browser admin.
- Verified: `backend/tests/test_backup_stream_restore.py` (streamed full file
  == manifest count and valid JSON, account file scope/count, wrong PIN 401,
  181-doc account merge replay) plus iteration 75 UI run (real browser
  downloads: 25 / 182 / 1337 records, 9.3 MB full file).

### 14. Emergent managed push notifications — verified against the playbook (Jun 2026)
The relay was already in place from an earlier session; this pass audited it
against the current Emergent push playbook and closed the gaps.
- Backend `routes/push.py` matches the playbook exactly: `POST /register-push`
  (JWT-checked so nobody can register a token under another user id) and
  `send_push(recipients, data, idempotency_key)` → `/api/v1/push/trigger`
  with `X-Push-Key: EMERGENT_PUSH_KEY`, chunked at 100 recipients, never
  raising. `POST /push/test` sends a single push to the calling super admin.
  With the dev `placeholder` key the endpoints return
  `{"status":"deferred","reason":"key_missing"}` — expected; the deployer
  swaps the real key in at publish time. NEVER edit EMERGENT_PUSH_KEY.
- Event senders already wired: chat messages (`routes/chat.py`), order
  placement + status changes (`server.py`), broadcasts
  (`routes/broadcast.py`), new-device logins (`core/login_history.py`) and the
  generic in-app notification helper (`core/notifications.py`).
- FIXED: `app/_layout.tsx` registered TWO
  `addNotificationResponseReceivedListener`s (one in `PushReRegister`, one in
  `RootLayoutInner`), so every notification tap navigated twice. There is now
  exactly one, in `RootLayoutInner`, handling warm taps,
  `getLastNotificationResponseAsync()` cold starts, `action_url` / `deeplink`
  / `url`, and http(s) links via `Linking.openURL`.
- ADDED: the denied-permission weekly nudge — when `status === "denied"` and
  `canAskAgain === false` we can never re-prompt, so once every 7 days
  (throttled via AsyncStorage `pushNudgeAt`) the user gets a dialog with an
  "Open Settings" CTA (`Linking.openSettings()`). Both the CTA and "Later"
  stamp the key.
- ADDED: Admin → Broadcast now has a "Send test to my phone" button
  (testID `broadcast-test-push`) hitting `POST /push/test`, with copy stating
  it only works in a published build.
- Config confirmed: `expo-notifications` plugin present in `app.json`
  (mandatory — Android pushes are data-only and render through its Firebase
  messaging service), module-scope `setNotificationHandler` +
  high-importance `default` channel, native token via
  `getDevicePushTokenAsync()` (never the Expo token), re-registered on every
  app open / auth change, and a real
  `frontend/google-services.json` (project `slangcart`, package
  `com.slangcart.app`) wired via `android.googleServicesFile`.
- Cannot be tested in Expo Go or the web preview — needs Publish → Deploy →
  Generate build (iOS also needs an APNs .p8 key; Android a Google service
  account JSON, both prompted in the build UI).

### 15. Notification settings + 5-stage order tracking + chat channel (Jun 2026, iteration 76)
User picked ALL the offered options, so all of it shipped.

**Notification preferences**
- `routes/push.py`: `GET/PUT /api/me/notification-prefs` storing
  `notification_prefs` on the user doc. Categories: `orders`, `chats`,
  `offers`, `login_alerts`, `vendor_new_order` (seller-only row). Absent or
  partial dicts mean "everything ON", so existing users keep their alerts.
- `send_push(..., category=...)` now drops muted recipients via
  `filter_by_prefs()`. Categories wired at EVERY call site: chat → `chats`,
  order placed / status change → `orders`, the seller's new-order ping →
  `vendor_new_order` (a separate send so a shop can mute everything but
  orders), broadcasts → `offers`, new-device login → `login_alerts`, and
  `core/notifications.py` maps notification `kind` → the same categories so
  the bell and the push obey one switch. Omit `category` for must-deliver
  sends (e.g. the admin's own test push).
- UI: `app/notification-settings.tsx`, linked from Profile → "Notifications".
  Optimistic toggles that roll back on failure. Cold deep-link retries once
  after 1.5 s because the session may still be hydrating (a 401 on the first
  attempt is normal).

**Five-stage order tracking**
- Flow is now `placed → confirmed → shipped → out_for_delivery → delivered`
  (+ `cancelled`), defined once in `server.py` as `ORDER_STATUS_FLOW` /
  `ORDER_STATUSES` / `COD_PENDING_STATUSES` / `ORDER_STATUS_COPY`.
- Every real transition appends to `status_history`:
  `{status, at, by_name, by_role}` (role is `admin`, `seller` or
  `customer`). Checkout seeds the `placed` entry. Re-saving the same status
  is a no-op, so the timeline never duplicates.
- COD "cash pending" totals count all four pre-delivery stages; settlement
  still fires only on `delivered`.
- Buyer UI: five progress dots + a live "On the way · 11 Jun, 4:05 pm · by
  Test Shop" line on the card, and a full vertical TRACKING timeline in the
  order modal with the existing vendor-set "Arrives by <ETA>".
- Seller UI: ONE contextual next-stage button (`vnext-<orderId>`) walks
  Confirm order → Mark shipped → Out for delivery → Mark delivered.
  Filter tabs, colours and labels (`STATUS_LABEL`, "ON THE WAY") updated for
  buyer, vendor and admin lists.

**Chat sound**
- Chats push with `channel_id: "chat"` and `app/_layout.tsx` creates a second
  Android channel ("Chat messages", MAX importance, own vibration pattern) at
  module scope, so the owner can set a different sound per channel in phone
  settings. When a `.wav` is supplied later: add it to the
  `expo-notifications` plugin `sounds` array, create a NEW channel id
  (`chat-v2` — Android freezes a channel's sound after creation) and add
  `sound: "<file>.wav"` to the chat `send_push` data for iOS.
- Test: `backend/tests/test_notif_prefs_tracking.py`.

---

## Jun 2026 — Cashback lifecycle verification + push tray diagnostics (iteration 78)

### Cashback / delivery lifecycle — VERIFIED
`backend/tests/verify_cashback_flow.py` → **36/36 pass** against the live API:
delivery flat charge under the free threshold, free delivery at/above it,
`cashback_status=awaiting_delivery` with NO credit before delivery, +₹ on the
`delivered` transition, duplicate `delivered` cannot double-credit (one
`cashback_credit` row), vendor-wallet-short → PENDING → `POST
/admin/cashback/{order}/fund`, platform funding → `vendor_outstanding` →
`…/outstanding/{vendor}/recover` (customer never credited twice), clawback on
return with refund netting + `delivery_charge_reversal`, wallet+COD parity
(`wallet_paid + cod_due == grand_total`), multi-vendor delivery cap with
allocations summing to the cap, and zero new referral/cascade transactions.

### "Chat & order notifications don't reach the phone status bar"
Root cause is environmental, not a code defect: the whole push path matches the
Emergent managed-push playbook (native `getDevicePushTokenAsync`, backend-only
relay, module-scope handler + `default`/`chat` channels, tap + cold-start
handlers, `google-services.json` present for `com.slangcart.app`). Tray
delivery needs `EMERGENT_PUSH_KEY`, which is `placeholder` in preview and is
injected only by the deploy pipeline — and Expo Go / web can never receive a
native push. In-app bell rows keep working because they're pure DB rows.

Made that diagnosable instead of invisible:
- `POST /api/register-push` now stamps `users.push_registration
  {status, platform, at}` (**never** the device token) for every outcome, so
  "this phone never registered" is distinguishable from "relay key missing".
- `send_push()` returns a status string (`sent` / `key_missing` /
  `opted_out` / `relay_unreachable` / `upstream_4xx`) instead of `None`.
  All 6 call sites ignore the return value, so nothing changed for them.
- `POST /api/push/test` (super admin) now answers
  `{ok, relay, key_configured, device_registration, hint}` with a plain-English
  hint naming the actual blocker. Admin → Broadcast's "Send test to my phone"
  prints those lines.
- `src/push.ts` caches the registration only when the relay answers
  `registered`; a `deferred` answer is retried on the next app open (it used to
  be cached, leaving the install unreachable for the whole session).

### Also fixed
`(tabs)/_layout.tsx` registered a phantom `network` tab from the retired MLM
branding entry (`No route named "network" exists in nested children` on every
render). Registration is now filtered to routes that exist, and the `network`
tab is gone from `DEFAULT_BRANDING.tabs`.

### Verified
`backend/tests/test_iter78_push_and_cutover.py` 18/18 (report
`test_reports/pytest/iter78_push_cutover.xml`): push diagnostics + RBAC,
register-push stamping, chat POST still 200 with the relay 401, MLM endpoints
dead (`/wallet/transfer` 404, buyer `/withdrawals` 403, `/admin/users/tree`
404), short-id backfill idempotent, and `GET /api/admin/wallet/export/groupwise`
returning a real openpyxl workbook (buyer 403). Browser: buyer wallet shows the
cashback chips with no transfer/withdraw, tab bar renders 5 tabs with the route
warning gone.

### Still open / needs the owner
- `chat_ping.wav` for the custom chat notification sound (owner will send later).
- Live Razorpay keys — payments stay in Mock mode until then.
- Real tray-push confirmation needs a published build (Publish → Deploy →
  generate Android/iOS build).
- Note: `GET /api/admin/finance/export/transactions` is CSV; the group-wise
  **xlsx** export is `GET /api/admin/wallet/export/groupwise`.

---

## Nov/Jun 2026 — Heavy battery drain (owner bug) — FIXED · iteration 79

Owner: "registration / login / ordering all work, but the app eats the
phone's and tablet's battery." Four always-on drains were found; all four are
now FOREGROUND-ONLY.

1. **The periodic location ping was the main offender.** `LocationGate` runs
   `useLocationTracking` for EVERY logged-in non-admin, and the hook fired
   every **30 seconds** — `requestForegroundPermissionsAsync()` **plus a fresh
   `getCurrentPositionAsync({Balanced})` sensor fix** and a network POST, about
   **120 GPS + radio wakes an hour, all day**, because the JS timer kept
   running while the phone was in a pocket.
   Now: cadence **5 min**, the tick bails unless `AppState.currentState ===
   "active"` and the interval is torn down on background / rebuilt on
   foreground, coordinates come from the new
   `getTrackingCoords()` (`getLastKnownPositionAsync({maxAge})` first — free,
   no radio wake — falling back to one real fix only when that is stale, and
   reading the permission with `getForegroundPermissionsAsync` so it can never
   prompt), and the POST is skipped unless the user moved **≥ 150 m**
   (`metresBetween` haversine in `location.ts`) or the server copy is older
   than 20 min. Offline coords still cache in AsyncStorage and flush later.
2. **Chat WebSocket kept alive in the background** with a 20 s heartbeat, plus
   reconnect storms every time the carrier dropped the idle socket — bottom
   tabs stay mounted, so one visit to the Chat tab meant a socket for the rest
   of the day. It now closes on background (`paused` flag stops the backoff
   reconnect) and re-opens instantly on foreground; on web `visibilitychange`
   maps hidden → pause, visible → resume. Offline delivery is the push relay's
   job, so nothing is lost.
3. **`shop-layout-renderer` timers**: `useCountdown` ran a **1-second**
   interval for the whole life of the shop screen **even when no flash sale
   existed** (≈3,600 re-renders/hour); the banner carousel advanced every 4 s
   in the background; the impression-analytics flush polled every 5 s. Now the
   countdown only runs while a sale is genuinely live (and stops on expiry /
   background), the carousel pauses on background, and the flush is 15 s and
   skipped when inactive.
4. **Polling screens** `/admin/products` (15 s), `/admin/shop-layout` (20 s)
   and `/payment-upi` (6 s) skip the work when the app isn't in the foreground.

Untouched on purpose: the provider background-location task (`bg-location.ts`)
is already 30 min / 250 m and only runs for providers who switch themselves
Available.

### Verified (iteration 79)
`backend/tests/test_iter79_battery_fix.py` 9/9 — `/api/service/me/location`
still updates `service_location`, shop-layout analytics still accepts batched
events, chat POST + `/api/ws/chat` (hello / pong) still work, product
pincode+GPS filtering unchanged, all three logins fine. Browser: buyer / admin
/ vendor screens render clean; on the Chat tab, dispatching
`visibilitychange → hidden` **closed** the socket and produced **zero**
`/api/service/me/location` POSTs, and `→ visible` re-opened it immediately.
Report `test_reports/iteration_79.json`. Real battery numbers can only be read
from a published build on a real device.

---

## Jun 2026 — "Add money" opened the ₹118 subscription + admin wallet credits were dead (iteration 80)

### 1. Add money is now a real wallet top-up (was: the subscription wall)
`Add money` on the wallet screen pushed `/payment` — the ₹118 SUBSCRIPTION
screen — so nobody could load their wallet. New flow:

* **`routes/wallet_topup.py`** (NEW, mounted with the `/api` prefix):
  - `GET /wallet/topup/config` → `{min_amount: 10, max_amount: 5000, presets,
    balance, wallet_frozen, key_id, is_mock}`; max is tunable via
    `settings.wallet_topup_max` (owner's rule: **₹5,000 per top-up**).
  - `POST /wallet/topup/start {amount}` → server-side clamp (400 outside
    10 … 5,000, 403 on a frozen wallet), creates the Razorpay order and ONE
    open `wallet_topups` attempt per user.
  - `POST /wallet/topup/verify` → live mode HMAC-verifies + cross-checks the
    captured amount; then a `created → paid` claim on the attempt gates the
    money, so a double tap / retry / webhook replay returns
    `already_verified` and can **never** credit twice. Writes the wallet
    credit, a `wallet_topup` transaction with a sequential `TXNA<n>`
    reference, and a `bank_ledger` CREDIT (cash in the company account
    against the new wallet liability → company net worth unchanged, which is
    the correct treatment).
* **`app/wallet-topup.tsx`** (NEW): balance card, amount field, preset chips
  (₹100 … ₹5,000), live "You can add ₹10 to ₹5,000 in one go" hint, an
  over-limit warning that disables the pay button, mock-mode notice, and a
  success strip with the new balance. Live Razorpay opens in the WebView
  modal on native / Checkout on web; mock mode simulates the gateway so the
  whole path is exercisable before the owner supplies live keys.
* `wallet-add-money` and the buyer dashboard's "Add money" button both route
  here; nothing points at `/payment` any more.

### 2. Withdraw is VENDOR-ONLY in the app
`canWithdraw` was `isSeller || isAdminUser`. It is now approved vendors only —
customers and service providers use the wallet inside the app, and company
money is settled from Admin → System wallet. The backend still 403s plain
buyers.

### 3. Admin → Users → Wallet adjust now spends COMPANY NET WORTH
Root cause: the credit path called `debit_admin_bucket("direct_added", …)`,
and the only way to fill that bucket — the "Add Direct-Added Money (UTR)"
button — was deleted in iteration 64. So **every** admin credit failed with
"Insufficient Direct-Added funds in system wallet".
Credits now come straight out of company net worth: the user-wallet liability
rises and `net_worth` already subtracts that liability, so the rupee is
accounted for with no extra ledger row. The treasury mirror
(`direct_added`) still moves (it may go negative — that honestly means more
has been paid out than was ever deposited) and the response returns
`funded_from: "company_net_worth"` plus the user's new balance.
Deliberately **no hard cap** on the figure: this DB reports a negative net
worth from legacy MLM data, and a guard would have re-broken credits exactly
like the old gate. The number is shown instead — the admin edit sheet now
reads "Funded from Company Net Worth · available ₹X" (or "overdrawn by ₹X"),
and the old Direct-Added copy is gone from both `admin/users` and
`admin/system-wallet`.

### Verified (iteration 80)
`tests/test_iter80_wallet_topup_and_admin_adjust.py` 11/11 + Playwright:
top-up screen with every limit/preset/success state (₹500 credited, balance
₹19,875), over-limit disables pay, buyer has no withdraw button or settlement
history, vendor has both, admin has neither, admin credit ₹50 succeeds and
net worth moves −50 (restored by the debit). Report
`test_reports/iteration_80.json`.

---

## Jun 2026 — PHASE 1: core checkout / payment / wallet / treasury financial fix (iteration 81)

### The one money engine — `core/shop_money.py` (NEW)
Every shop-order rupee now moves through ONE module, so App, Customer Web,
Vendor and Admin can never calculate differently (the frontend computes
nothing — it renders what the backend returns).
* `post()` writes a fully-described ledger row: `short_id` (**TXNA<n>**, also
  the user-facing `reference_number`), txn_group, type, customer/vendor,
  shop, order id + number, payment id, source/destination wallet, debit,
  credit, amount, **previous_balance / new_balance**, cashback % + amount,
  delivery charge, GST, settlement status, payment method, remarks.
* `credit()` / `debit()` — a debit is a CONDITIONAL `$inc` guarded by the
  balance, so a wallet can never go negative and a transaction can never
  half-complete; a refused debit raises `InsufficientFunds` ("…available
  balance is insufficient. No money has been deducted.") and is recorded in
  `financial_errors` for admin (`GET /api/admin/finance/errors`).
* **Idempotency is enforced by the DATABASE**: unique sparse index on
  `transactions.idempotency_key`, keys like `VENDORSALE:{order}`,
  `DELFEE:{order}`, `DELREV:{order}`, `WDL:{id}`, `RECON:{payment}`. A
  replayed webhook / double tap / retried status change moves money zero
  extra times. If a ledger row loses the race after a deduction, the money
  is put straight back — a deduction can never exist without its row.

### Money model, as specified
* **Shop commission = ₹0.** `platform_share` is now 0 and `vendor_share` is
  the full line total; no `shop_commission` row is written anywhere in the
  shop flow (legacy historical rows are left untouched).
* **Vendor is credited the PREPAID money** (wallet slice + Razorpay slice,
  delivery included) at placement — `₹470 + ₹30 = +₹500` — exactly once.
* **COD** credits nobody: the seller takes the cash in person. No fake
  customer-wallet credit, and the customer's history/invoice now carries a
  "Cash on Delivery order — ₹X to be paid to the delivery agent" row
  (`cod_order`, zero wallet impact).
* **Wallet + COD**: only the wallet slice is credited (₹200), never the cash
  ₹300. **Wallet + online**: one single ₹500 vendor credit linked to the
  wallet txn, the Razorpay payment id and the order id.
* **Delivery fee settles ONCE, on delivered**: vendor wallet −₹30 → treasury
  +₹30 + Revenue-Ledger row (`delivery_charge_collected`). It is no longer
  taken at placement. **Free delivery moves ₹0 and writes no revenue row.**
  If the vendor wallet cannot cover the fee, nothing is deducted: a
  `vendor_outstanding` (kind `delivery_fee`) + a financial error are raised.
* **Cancellation** reverses exactly what the LEDGER recorded (vendor credit,
  and the delivery fee back to the vendor / out of the treasury). This also
  fixed a real defect: the old cancel path debited the vendor reversal from
  `wallet_balance` (customer/referral money) instead of the vendor wallet.

### Checkout ↔ Razorpay mismatch (₹470 collected on a ₹500 order) — FIXED
`routes/order_payments._price_cart()` priced the GOODS only. It now runs the
same `compute_cart_delivery` engine as checkout and returns
`{goods, delivery, total}`, so `items + delivery − wallet = online amount`,
and `/orders/payment/start` also returns `goods_total` / `delivery_total`.
The app already renders `amount_paise` from the server, so display and
collection can no longer disagree.

### Paid but no order — `routes/payment_recon.py` (NEW)
* Every online checkout writes a `payment_reconciliations` row the instant the
  payment is claimed (`awaiting_order`) and flips it to `completed` when the
  order group exists. Anything left behind is a real orphan.
* `GET /api/admin/finance/reconciliations` lists them (plus a scan for paid,
  unconsumed attempts) with the open total;
  `POST …/{payment_id}/resolve {action: refund_to_wallet|close, note}`
  refunds to the customer wallet exactly once (`RECON:` key) and is audited.
* The customer can always resume instead of paying again
  (`GET /orders/payment/pending`); the amount is never applied to a later
  order and no fake wallet balance is created.
* `POST /api/payment/webhook` — HMAC-verified (`RAZORPAY_WEBHOOK_SECRET`;
  refuses unsigned payloads on live keys), idempotent per Razorpay payment id
  via `payment_webhook_events`, and it only marks the matching attempt paid —
  it never moves money itself.

### Vendor wallet + withdrawal
`users.vendor_earnings` IS the vendor wallet. New `GET /api/vendor/me/wallet`
returns available balance, ledger credits/debits, `unledgered_difference`,
`in_sync`, outstanding, `min_withdrawal` and `can_withdraw` — computed by the
BACKEND so the UI can never show a different number.
Withdrawals: **minimum ₹5,000**, eligibility from the AVAILABLE balance only
(never total/lifetime sales, pending money or customer liability), the hold is
a ledgered atomic debit out of the correct wallet, one settlement in progress
at a time (double-tap / duplicate-callback proof), and a rejection returns the
money to the SAME wallet it was held from (`WDL_REJECT:` key).

### Audit (read-only)
`tests/audit_phase1_finance.py` reports payment-without-order,
order-without-payment, duplicate Razorpay ids, duplicate vendor/delivery/
cashback postings, post-cutover commission rows, unsettled delivery fees,
negative wallets, vendor ledger drift, the net-worth formula (unchanged:
bank_tally_net + pending − user wallets − pending withdrawals − GST) and open
financial errors. It never writes.

### Verified — TEST A … H all pass
`tests/verify_phase1_money.py` **56/56**: online ₹500 (Razorpay collects 500,
vendor +500, then −30/treasury +30, commission 0, re-delivery takes nothing
twice), wallet ₹500, COD ₹500 (no wallet credit either side), free delivery
(₹0 both sides, no revenue row), wallet+COD (no duplicate ₹300), wallet+online
(single ₹500 credit), paid-but-no-order (resume + reconciliation + one-time
refund), duplicate webhook (one payment, one order, one vendor credit, same
payment can't buy twice), plus the withdrawal rules. The earlier
`verify_cashback_flow.py` still passes 36/36 — no regression.

---

## PHASE 2 — Returns · Refunds · Inventory · Vendor Net Worth · GST · Profit · Excel · Reconciliation
*(Jun-2026 — built on the verified Phase-1 engine; Phase-1 rules unchanged)*

### One engine per concern
* `core/gst.py` — **THE** GST calculator. `split_gst(base, pct, qty)`,
  `split_inclusive()`, `pricing_block(product)`, `public_pricing()`.
  Whole app is **GST-EXCLUSIVE**: `base` is the taxable value, GST is added on
  top, and `CGST = SGST = GST ÷ 2` (cgst + sgst always equals total_gst to the
  paisa). Product, invoice, purchase, sales, vendor ledger, reports, Excel,
  returns and refunds all call it. `GET /api/gst/compute?base=&pct=&qty=`
  (auth'd) exposes it so **no screen ever does its own GST maths** — the
  product editor's live CGST/SGST/profit panel is server-computed.
* `core/returns.py` — the only place a delivered order can travel backwards:
  eligibility, request, seller decision, goods received, refund, cashback
  claw-back, inventory restoration, per-return audit.
* `core/shop_money.py` — still the only place money moves.
  Added `post_opening_balance()`: an audited **opening balance journal entry**
  that explains a pre-ledger / directly-seeded balance without moving a rupee,
  so `opening + credits − debits = closing` becomes provable everywhere.

### Return lifecycle
`delivered → return_eligible → requested → vendor_review → approved →
returned (goods back) → refund_processed → inventory_restored → completed`,
with `rejected` and `refund_pending` as the two off-ramps. Every stage is
appended to `returns.timeline` with actor + timestamp + note and is shown to
the customer, the seller and admin.

### The money rules (exactly as the owner specified)
* **Window** — `settings.return_window_days` (default **7**) from
  `delivered_at`. Inside it a delivered order offers **Return** and never
  Cancel; past it the order simply reads **Completed** and the button is gone.
  The window is computed on the SERVER (`/orders/me` and
  `GET /api/orders/{id}/return-state`) so app and web can never disagree.
* **Direction** — refunds are **always vendor wallet → customer wallet**, for
  wallet, COD and online orders alike. COD cash was physically collected by
  the seller and an online payment was already credited to the seller, so the
  seller is the payer in every case. No money is ever generated.
* **Partial returns** refund the returned line only, priced from what was
  actually charged (`line_total ÷ qty × returned_qty`) — never re-derived from
  the live product price. ₹200 + ₹300 + ₹500 returning the ₹300 item refunds
  ₹300, not ₹1,000, and restocks only that product.
* **Delivery charge is NOT refunded** (`settings.return_delivery_refundable`,
  default off). When switched on it is refunded only on a whole-order return
  and always as its own ledger component — never mixed into the item refund.
* **Cashback** — `reverse_partial_cashback()` claws back only the cashback
  ACTUALLY credited for the returned lines, capped by the order's remaining
  un-reversed cashback (several partial returns can never over-recover), it
  references the original cashback transaction, refunds the funder
  (vendor wallet or platform bucket) for what was recovered, and nets any
  shortfall the customer's wallet couldn't cover off the refund instead of
  pushing a wallet negative.
* **Vendor balance safety** — if the seller wallet can't cover the refund,
  **NOTHING is deducted**: the return parks as `refund_pending`, a
  `vendor_outstanding` row and a `financial_errors` entry are written, the
  seller is notified, and admin retries via
  `POST /api/admin/returns/{id}/refund` once the seller funds up. Admin
  cannot conjure the money — the debit still comes from the seller.
* **Duplicate-proof** — `RETURNDEBIT:{return_id}` / `RETURNCREDIT:{return_id}`
  idempotency keys, and stock restoration is *claimed* with a unique
  `_id = INV:{return}:{product}:{variant}` in `inventory_adjustments`
  (referencing product, order, return, qty and the refund txn id), so a
  retried request, a double tap or a replayed webhook acts exactly once.
* **Purchase price privacy (§16)** — `purchase_price` and `purchase_gst_pct`
  are excluded **at the query** from customer-facing product responses;
  customers get `gst_breakdown` (selling side only) and never see cost or
  margin.

### Vendor Net Worth & ledgers (all backend-derived)
* `GET /api/vendor/me/net-worth` — available balance, COD cash still to
  collect, pending withdrawals, and a breakdown of opening / sales / delivery
  charges / refunds / withdrawals / cashback funded / adjustments, plus a
  `reconciliation` block proving `opening + sales − delivery − refunds −
  withdrawals = available`.
* `GET /api/vendor/me/sales-ledger` — four sections with the exact fields
  requested: **Cash on Delivery**, **Wallet Payment**, **Online Payment**,
  **Return Items** (original order, return id, product, qty, original amount,
  refund amount, original payment method, vendor debit, customer credit,
  inventory restored, transaction id).
* `GET /api/vendor/me/offline-ledger` — counter sales split Cash / UPI / Card
  with reference, GST and net-worth impact.
* `GET /api/vendor/me/profit-report` — profit per unit, margin % and total
  potential stock profit, from the one GST engine.
* `GET /api/vendor/me/net-worth/export` — an 8-sheet workbook (Net Worth
  Ledger with all 23 specified columns, Sales · COD / Wallet / Online, Return
  Items, Offline · Cash / UPI / Card, Reconciliation) filterable by date,
  order id, payment method, transaction type, settlement status and sale type.

### Error register & final reconciliation
* `financial_errors` records error id, type, transaction / order / payment /
  return / vendor refs, expected vs actual vs difference, timestamp and
  resolution status. `GET /api/admin/financial-errors` +
  `POST …/{id}/resolve`.
* `GET /api/admin/reconciliation` re-derives and PROVES: customer wallets,
  vendor wallets, treasury (delegating to the approved company net-worth
  formula so nothing is double counted), inventory (every completed return
  restored its units exactly once — none missing, none doubled), return money
  (vendor debit = customer credit = refund paid) and GST. It is read-only: it
  reports and logs, it never "fixes" a balance.
  `POST /api/admin/reconciliation/opening-balance` posts the audited opening
  entries (verified NOT to mutate `wallet_balance` / `vendor_earnings`).

### Screens
Buyer: `/returns/new` (qty steppers, reason chips, refund preview stating the
delivery charge is not refundable) and `/returns` (status + full stage
timeline). Seller: `/vendor/returns` (approve · decline · item received · pay
refund, with the honest short-balance message) and `/vendor/net-worth` (hero,
breakdown, five ledger tabs, date filters, Excel). Admin: `/admin/returns`
(returns · refunds due · error register · run reconciliation). Product editor
gained Purchase price (private) / Purchase GST / Selling GST with the
server-computed tax & profit panel. `/orders` now shows Return inside the
window, no Cancel on delivered orders, and a Completed badge after expiry.

### Verified
`tests/verify_phase2_returns.py` **81/81** (run twice), covering full return,
partial return, wallet / COD / online returns, duplicate refund, duplicate
return request, vendor-short refund + admin resolve, 7-day expiry, cashback
reversal, GST + profit, purchase-price privacy, net worth, all ledgers, Excel
sheet totals and global reconciliation. `tests/verify_phase1_money.py`
re-run **56/56** — Phase 1 did not regress. The testing agent's independent
gap suite `tests/test_iter82_phase2_gaps.py` passes 19/19 (state-machine
skipping, cross-role 403 matrix, cost-leak protection, Excel sheets, and
proof that the opening-balance entry moves no money).

---

## Android tray push notifications — root cause & fix (Sep 2026)

**Symptom:** in-app notification rows appear, the native Android notification
bar stays empty.

**Root cause 1 — nothing was ever handed to Firebase, and nobody could see it.**
`send_push()` returned a status string that every call-site discarded, so a
`notifications` row was being read as proof of delivery. The relay actually
answers `401 {"error":"invalid X-Push-Key"}` whenever `EMERGENT_PUSH_KEY` is
the placeholder — and the *same* 401 was silently rejecting DEVICE
REGISTRATIONS too, so the relay held no token for any phone.

**Root cause 2 — Android freezes a notification channel at creation.**
The `default` / `chat` channels already existed on devices from earlier
builds, so raising `importance` to MAX in app code afterwards had no effect
(and a user/OEM toggle can mute them outright). A push can then be accepted,
delivered, written to the in-app bell and still never surface in the tray.

**Fix**
* `push_log` records EVERY attempt — stage
  (`created → sent_to_relay → accepted | rejected | skipped`), relay HTTP
  status, relay response body, channel, category, recipient count.
* `push_devices` records every registration with a non-reversible token
  fingerprint (sha256 prefix + last 6 chars + length — the raw token is never
  stored), the relay's answer, build ownership (Expo Go cannot receive push),
  real-device flag, OS version and the live permission status. Multiple
  devices per user are kept.
* Channel migration to `orders_v2` (Orders & delivery) and `chat_v2` (Chat
  messages), both born at MAX importance with PUBLIC lockscreen visibility;
  the legacy channels are still created so nothing already routed to them
  breaks and no user's channel settings are lost. `app.json`
  `defaultChannel` → `orders_v2`. `send_push()` fills `channel_id` in
  centrally from the category and remaps legacy ids, so no call-site changed.
* `src/push.ts` re-registers when the user **or the token** changes and
  listens for FCM token rotation (`addPushTokenListener`) — previously a
  rotated token was never re-sent, leaving the relay with a dead token.
* `core/login_history.py` pushed a new-device alert twice (once through
  `create_notification`, once through an explicit `send_push`) → one event now
  produces exactly one DB row and one push.
* **Admin → More → Push notification diagnostics** (`/admin/push-diagnostics`)
  and `GET /api/admin/push/diagnostics[/user]` expose the whole pipeline:
  relay key state, live relay probe, per-device registration, and the last 50
  attempts with the relay's literal status and body. `POST /api/push/test`
  can target any account by email and returns `relay_http_status`,
  `relay_response`, `channel_id`, `stage` and the device list — it can never
  report success when the relay rejected the send.

**Untouched:** the in-app notification system (records, history, read/unread,
UI, categories, targeting), `EMERGENT_PUSH_KEY`, the Emergent/SuprSend relay,
and all unrelated business logic. No local-notification workaround was added.

**Verified:** 14/14 pipeline tests + 5/5 direct-DB checks (channel routing per
kind, legacy remap, opt-out logging, one-push-per-login, multi-device rows,
raw token absent from the database), RBAC 403 for buyer / vendor /
products_manager / anonymous, and Phase 1 (56/56) + Phase 2 (81/81) with no
regression. Tray *display* itself can only be confirmed on the deployed
Android build — the diagnostics screen is the instrument for that.

---

## Wallet top-up + GST-inclusive pricing fixes (Sep 2026)

### "Razorpay took my money, the app said failed, wallet not credited"
**Root cause:** `/wallet/topup/start` DELETED any existing open attempt. A
second tap (or the screen re-mounting) orphaned the attempt the paid callback
was about to verify → verify returned 404 → the app showed "payment failed,
please try again" while Razorpay had already collected the money. Nothing was
credited, so nothing appeared in the wallet or in System Wallet group 2
(user liability) either.

**Fix**
* Open attempts are **never deleted** — they are parked as `abandoned`, and
  verify accepts `created | abandoned`.
* Verify resolves the attempt by OUR id **or** either Razorpay id, so a client
  that lost its local id can still claim its own payment.
* The credit goes through `shop_money.credit()` with idempotency key
  `TOPUP:{attempt_id}` — so it carries credit/previous/new balance, shows up
  correctly in the user-liability group, and reconciles in net worth. The
  matching `bank_ledger` credit is upserted per attempt (asset side), so a
  top-up leaves company net worth unchanged.
* **`POST /wallet/topup/recover`** asks *Razorpay* (new
  `core/razorpay.fetch_order_payments`) whether the order was actually
  captured, and credits exactly once. Tappable repeatedly, can never double
  credit, and when Razorpay reports nothing captured NO money is invented.
* `GET /wallet/topup/pending` lists recoverable attempts; the screen
  auto-recovers before it will ever show a failure, and shows a
  "Paid but not credited? → Recover payment" card.
* A claimed attempt can never end up paid-with-no-money: if the ledger
  refuses the write, the existing credit is returned or the attempt is handed
  back as recoverable.

### GST is now INCLUSIVE (owner's rule)
**Root cause:** `core/gst.py` added GST **on top** of the entered price, so the
"selling total" came out higher than the price the vendor typed — the exact
confusion reported.

**Fix:** `pricing_block()` / `public_pricing()` use `split_inclusive()`:
* the price typed **is** the final price; the tax is pulled out of it
* `base_amount + total_gst == final_amount` exactly, `CGST = SGST = GST ÷ 2`
* ₹944 @ 18% → base ₹800 · CGST ₹72 · SGST ₹72 · total stays ₹944
* ₹1,180 @ 18% → base ₹1,000 · CGST ₹90 · SGST ₹90 · customer pays ₹1,180
* `/api/gst/compute` now defaults to inclusive (`inclusive=false` for an
  explicit add-on-top quote)
* **Cashback** via `cashback_block()` — percentage **or** flat, never both
  (5% of ₹500 = ₹25, or a flat ₹25, never ₹50); a percentage wins if both are
  set and a flat amount can never exceed the price
* **Profit = selling price − purchase price − cashback**, with the margin
  before cashback reported separately, and potential stock profit = profit ×
  stock
* Purchase price / purchase GST remain vendor-private; the customer's
  breakdown always totals the price on the card

GST is display/reporting only — it never touches money movement, so Phase 1
and Phase 2 financial behaviour is unchanged.

**Verified:** `tests/verify_wallet_topup.py` 23/23 (run twice),
`tests/verify_phase2_returns.py` 93/93, `tests/verify_phase1_money.py` 56/56,
plus the testing agent's `test_iter84_wallet_topup_gst.py` (cross-user 404,
request-body amount ignored, inclusive default, percent-wins-over-flat) and
the /wallet-topup + product-editor screens verified on mobile.

## Sep-2026 Cleanup Round
- Wallet CASHBACK/PENDING chips: solid white labels, stronger chip fill (AA contrast on emerald gradient)
- GET /api/gst/compute: now vendor/admin-only (buyer 403, unauth 401); tests updated in test_iter84_wallet_topup_gst.py (9 passed)
- Legacy /my-orders route: verified absent, nothing to remove
- expo-notifications web warning: deferred per user
- User confirmed live Razorpay keys uploaded and working

## Sep-2026 Reset Center Self-Clear Fix
- /admin/system/account-reset: self-reset now allowed in mode=clear (wipes own test data, keeps login); self-delete still blocked with clearer message
- Clear now also zeroes wallet_buckets so wallet truly reads ₹0
- E2E test: backend/tests/test_self_account_reset.py (7/7 PASS, temp admin + temp danger PIN, fully restored after)

## Sep-2026 Money/GST Rework — Phases 1-5 DONE (42/42 E2E pass)

Verification: `backend/tests/verify_sep2026_money.py` (42 checks, all pass)
Backfill:     `backend/tests/backfill_bank_ledger.py` (idempotent)

### Phase 1 — Money core
- NEW `core/bank.py`: Group 7 bank ledger. One idempotent row (`ref_key` unique)
  per real bank event, so **bank balance = Σcredits − Σdebits = bank statement**.
- Razorpay receipts now ALL land in bank_ledger: shop orders paid online,
  registration fees, wallet top-ups. Payouts write debits.
- Backfilled history: 51 order receipts, 3 reg fees, 27 top-ups keyed.
- **Vendor wallet unified**: shop money lives in `users.vendor_earnings`. The
  Vendor Wallet screen, Dashboard WALLET tile and withdraw gate now all read
  `/vendor/me/wallet` (ledger-derived). Was reading `wallet_balance` → money
  "invisible" + false "insufficient balance".
- Group 2 liability now includes **vendor_payable** (money owed to sellers).
- Group 2 drilldown lists EVERY liability row (was 3 legacy types → empty list).
- Net worth = bank + cash_on_hand + receivables − customer wallet − vendor
  payable − pending withdrawals − GST payable.
- Vendor Net Worth "Withdraw" now routes to the wallet; min ₹5,000; 24h promise.

### Phase 2 — Delivery charge + GST
- Delivery charge is GST-INCLUSIVE 18%: revenue row = fee×100/118 (Group 1),
  GST row = fee×18/118 (Group 3, `gst_kind=delivery_charge`). Reversal undoes both.
- Free delivery → no charge, no revenue row, no net-worth impact.
- Registration cash (offline/UPI-manual) + un-remitted COD = `cash_on_hand`,
  reported beside the bank balance, never mixed into it.
- Checkout shows Taxable value / CGST% / SGST% / Total GST, computed by the
  server on `GET /cart` (`gst_summary`, rate-wise). Frozen onto order lines
  + `orders.gst_summary` so app/order/invoice can never disagree.

### Phase 3 — Transactions & one invoice format
- `invoices.is_invoiceable` → EVERY money row gets a document (was a blocklist,
  so cashback/refund/top-up rows said "no invoice available").
- GST rows now suppressed BY DEFAULT (`suppresses_gst`) and shown only for a
  real taxable supply — no more bogus 18% on internal movements.
- Plain-English descriptions added for all 15+ money types.

### Phase 4 — Return retiming
- Customer window: **10 minutes** from delivery (`return_window_minutes`).
- Vendor window: **24 hours** (`return_vendor_window_hours`) — `vendor_can_act`.
- Return screen counts down live from the server's `seconds_left`.
- Refund stays vendor wallet → customer wallet; delivery charge never refunded.
- NEW `POST /admin/returns/{id}/refund-from-company`: admin covers a short
  seller from company net worth, booked as a recoverable vendor outstanding.

### Phase 5 — Vendor orders UX
- `vendor_sales` now stores `product_image_url`; older rows fall back to the
  parent order's item image, then the catalogue. Images no longer blank.
- Vendor order items are tappable → product page (same as the customer side).

### STILL PENDING
- Phase 6: Delivery Partner role (apply, admin vendor-mapping, order mgmt,
  net worth + wallet, COD collected → wallet, Pay-To-Admin via Razorpay
  webhook → Group 7 + Group 2 vendor-wise split, Excel, restricted nav,
  min withdrawal ₹1000, no earnings per delivery)
- Phase 7: Web parity pass on everything above

## Oct 2026 — Update pack (4 owner-reported items)

1. **POS search by serial / IMEI.** `frontend/src/device-identity.ts` is the
   single matcher (case-insensitive, ignores spaces/dashes, walks
   `serial_number`, `imei_1`, `imei_2` and every `device_units[]` row).
   `/vendor/pos` now searches name **or** any device code and shows a
   "Serial: 12340987" hint explaining WHY a chip matched.
2. **Per-unit device identity.** New `DeviceUnit` model + `device_units[]` on
   ProductCreate/ProductUpdate. The Device Identity section has a
   "Track every unit separately" switch: stock 10 ⇒ 10 unit cards, each with
   serial + IMEI-1 + IMEI-2 and a scan button. Rows resize with stock (capped
   at 200), duplicate codes across units are rejected on save, and unit #1 is
   mirrored into the legacy single serial/IMEI fields. `device_units: []` is
   sent when the switch is OFF so the server clears old rows.
3. **Admin bottom nav.** `delivery-partners` was auto-registering as a 7th tab
   and broke the locked 6-tab bar; it is now `href: null` and lives in
   /admin/more. New shared `src/tab-bar-icon.tsx` gives both the admin and
   buyer bars the same active-pill treatment (admin active tint moved from
   accent to primary for consistency).
4. **Map-shops 500 + rider-owned order flow.**
   * ROOT CAUSE of "could not load shops": `GET /admin/delivery-partners/
     {dp_id}/vendors` projected `{"id":1, ..., "dp_pincodes":0}` — MongoDB
     rejects inclusion mixed with exclusion. Rewritten to return every
     approved seller with `pincodes[]`, plus `all_pincodes` and the rider's
     own `dp_pincodes`.
   * Admin sheet: pincode filter chips (rider's PINs pre-selected),
     Select all / Clear, multi-select, save.
   * Rider `/delivery/orders` is grouped RETAILER-WISE (sticky shop header,
     "Only this shop").
   * `GET /vendor/me/delivery-partners` tells the seller panel it is
     rider-managed. `VENDOR_ALLOWED_WHEN_DP_MANAGED = ("confirmed",
     "cancelled")` — `PATCH /vendor/orders/{id}/status` 403s on shipped /
     out_for_delivery / delivered when a rider is mapped, and the seller UI
     shows a banner + inline lock instead of the advance button. Unmapped
     sellers are untouched. The return flow is unchanged.

Verified: `tests/verify_oct2026_updates.py` 27/27, plus regressions
verify_phase1_money 56/56, verify_phase2_returns 93/93,
verify_delivery_partner 40/40, and testing-agent iteration 86 green on
mobile 390x844 and desktop 1440x900.
