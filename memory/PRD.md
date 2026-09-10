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
