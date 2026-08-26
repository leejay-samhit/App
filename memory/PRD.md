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
