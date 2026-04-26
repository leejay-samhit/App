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
