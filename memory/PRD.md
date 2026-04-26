# NetworkPay — Referral & E-commerce Platform

## Overview
Mobile-first (Expo) referral platform for the Indian market. Multi-level commission, mocked UPI registration, wallet-based e-commerce, in-app notifications, achievement tiers, and an admin panel that can fully manage users + tune the payout structure live.

## Tech Stack
- Frontend: Expo SDK 54, expo-router, @expo/vector-icons, react-native-reanimated, expo-clipboard, AsyncStorage, axios
- Backend: FastAPI, Motor (async MongoDB), bcrypt, PyJWT
- Auth: JWT Bearer tokens (AsyncStorage on mobile)
- Payments: MOCKED — `/api/payment/register-fee` simulates ₹100 UPI; `/api/orders/checkout` deducts wallet only

## Core Business Rules (now admin-tunable)
- `registration_fee` (default ₹100)
- `payout_l1` — L1 sponsor (default ₹400) credited every `directs_required` paid directs
- `payout_l2` — Grand-sponsor (default ₹100) per signup
- `payout_l3` — Great-grand-sponsor (default ₹50) per signup
- `directs_required` — direct count per L1 cycle (default 4)

All values stored in `settings` collection (`id="global"`) and **applied live** to the `/payment/register-fee` chain.

## Achievement Tiers
Bronze (0-3) · Silver (4-15) · Gold (16-63) · Platinum (64-199) · Diamond (200+)

## Roles
- **Admin** (`admin@app.com` / `Admin@123`): full user CRUD + payout structure control + payouts approval
- **User**: dashboard / network / wallet / shop / profile

## Implemented Features
- JWT auth (register w/ optional sponsor, login, /me, logout)
- Mock UPI ₹100 registration → multi-level (L1/L2/L3) auto-credit
- 5-tab user app (Dashboard / Network / Wallet / Shop / Profile)
- 5-tab admin app (Users / Payouts / Txns / Settings / Account)
- Animated dashboard with tier pill, hero decor, level chips, recent activity preview
- Notifications: bell badge + dedicated screen + mark-all-read
- Cart + wallet checkout + Orders history
- Copy & share referral code (WhatsApp-friendly)
- Withdrawal request, locked balance, admin approve/reject (with notifications)
- **Admin user CRUD**: search, edit any field (incl. wallet & paid status), role toggle, reset password, delete (with safeguards: cannot delete self / last admin / demote last admin)
- **Admin payout structure tuner**: per-cycle Revenue/Payouts/Margin projection + 5 inputs; saved live

## API Surface
**Auth**: `POST /auth/register|login|logout`, `GET /auth/me`
**User**: `GET /users/me/dashboard|network`, `POST /users/me/bank`
**Wallet**: `POST /withdrawals`, `GET /withdrawals/me`, `GET /transactions/me`
**Payment (mock)**: `POST /payment/register-fee`
**Shop / Cart / Orders**: `GET /products`, `POST /cart/add|remove|clear`, `GET /cart`, `POST /orders/checkout`, `GET /orders/me`
**Notifications**: `GET /notifications/me`, `POST /notifications/me/read-all`
**Admin Users**: `GET /admin/users`, `PATCH /admin/users/{id}`, `POST /admin/users/{id}/reset-password`, `DELETE /admin/users/{id}`
**Admin Payouts**: `GET /admin/withdrawals[?status=]`, `POST /admin/withdrawals/{id}/approve|reject`
**Admin Misc**: `GET /admin/transactions|stats`, `POST /admin/products`
**Admin Settings**: `GET /admin/settings`, `PUT /admin/settings`

## Smart Business Hook
With dynamic settings, admin can adjust commission economics on-the-fly (e.g., aggressive L1 to drive viral acquisition, or richer L3 to reward depth-builders) without redeploying. Per-cycle Revenue/Payout/Margin projection is shown alongside the editor so admin can sanity-check unit economics before saving.

## Tests
40/40 backend tests pass (iter 1: 17 + iter 2: 10 + iter 3: 13). Frontend flows verified by testing agent end-to-end.

## Test Credentials
See `/app/memory/test_credentials.md`

## Future Scope
- Razorpay/Cashfree real gateway, KYC upload, mobile recharge, push notifications, deep-link signup URL
