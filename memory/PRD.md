# NetworkPay — Referral & E-commerce Platform

## Overview
A mobile-first (Expo / React Native) referral platform for the Indian market with 1+4 multi-level commission, ₹100 mock UPI registration, wallet-based e-commerce, in-app notifications, achievement gamification, and admin panel.

## Tech Stack
- **Frontend**: Expo SDK 54, expo-router, @expo/vector-icons, react-native-reanimated, expo-clipboard, AsyncStorage, axios
- **Backend**: FastAPI, Motor (async MongoDB), bcrypt, PyJWT
- **Auth**: JWT Bearer (stored in AsyncStorage)
- **Payments**: MOCKED — `/api/payment/register-fee` simulates ₹100 UPI; `/api/orders/checkout` deducts wallet balance only

## Core Business Rules
- Registration fee: ₹100 (mocked)
- **Multi-level Commission**:
  - Level 1 (direct sponsor): ₹400 every 4 paid directs (1+4 cycle)
  - Level 2 (grand-sponsor): ₹100 per signup
  - Level 3 (great-grand-sponsor): ₹50 per signup
- Withdrawals require active UPI/bank + admin approval; locked balance refunded on rejection
- Wallet earnings can be spent in the in-app store

## Achievement Tiers (auto-derived by team size)
- Bronze (0-3) · Silver (4-15) · Gold (16-63) · Platinum (64-199) · Diamond (200+)

## Roles
- **Admin** (`admin@app.com` / `Admin@123`): manages users, approves payouts, monitors transactions
- **User**: dashboard with tier/notifications/level chips, network tree, wallet, shop, cart, orders, profile

## Implemented Features (Iteration 2)
- JWT auth (register w/ optional sponsor code, login, /me, logout)
- Mock UPI payment for ₹100 registration; multi-level (L1/L2/L3) auto-credits
- 5-tab user app: Dashboard / Network / Wallet / Shop / Profile
- 4-tab admin app: Users / Payouts / Transactions / Account
- Animated dashboard with tier pill, hero with decor, level chips, recent activity preview
- Notifications: bell badge + dedicated `/notifications` screen with mark-all-read
- Cart + Checkout (wallet-based) + Orders history
- Copy & Share referral code (WhatsApp-friendly message)
- Withdrawal request, locked balance, admin approve/reject with notifications
- Seeded sample products & admin

## API Surface
**Auth**: `POST /auth/register|login|logout`, `GET /auth/me`
**User**: `GET /users/me/dashboard`, `GET /users/me/network`, `POST /users/me/bank`
**Wallet**: `POST /withdrawals`, `GET /withdrawals/me`, `GET /transactions/me`
**Payment (mock)**: `POST /payment/register-fee`
**Shop**: `GET /products`
**Cart**: `POST /cart/add`, `GET /cart`, `POST /cart/remove`, `POST /cart/clear`
**Orders**: `POST /orders/checkout`, `GET /orders/me`
**Notifications**: `GET /notifications/me`, `POST /notifications/me/read-all`
**Admin**: `GET /admin/users|withdrawals|transactions|stats`, `POST /admin/withdrawals/{id}/approve|reject`, `POST /admin/products`

## Smart Business Hook
1+4 cycle is self-funding (₹100 in × 4 → ₹400 out per cycle). Adding L2 ₹100 + L3 ₹50 means each ₹100 signup is recycled deeper into the upline so retention grows: a 3-deep upline earns ₹150 passively per L3 signup, so leaders with deep teams keep earning even when their own directs slow down.

## Test Credentials
See `/app/memory/test_credentials.md`. 27/27 backend tests pass.

## Future Scope
- Real Razorpay/Cashfree gateway, KYC upload, mobile recharge API, push notifications, deep-link shareable signup URL
