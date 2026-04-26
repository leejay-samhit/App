# NetworkPay — Referral & E-commerce Platform (MVP)

## Overview
A mobile-first (Expo / React Native) referral platform for the Indian market with a 1+4 recursive referral model, ₹100 registration fee, mocked UPI payments, wallet/withdrawal flow, admin panel, and e-commerce placeholder.

## Tech Stack
- **Frontend**: Expo SDK 54, expo-router (file-based), @expo/vector-icons, AsyncStorage, axios
- **Backend**: FastAPI (Python), Motor (async MongoDB), bcrypt, PyJWT
- **Database**: MongoDB
- **Auth**: JWT Bearer tokens (AsyncStorage on mobile)
- **Payments**: MOCKED (no real gateway). All "Pay ₹100" flows simulate success.

## Core Business Rules
- Registration fee: ₹100 (mocked)
- Each user must refer **4 directs** to unlock a **₹400 payout**
- Referral payouts repeat for every additional 4 directs (cycle-based)
- Withdrawals require an active UPI ID or bank account, and admin approval
- Locked amount on withdrawal is refunded on reject

## Roles
- **Admin** (auto-seeded `admin@app.com` / `Admin@123`): manages users, approves/rejects payouts, monitors txns
- **User**: dashboard, network tree, wallet & withdrawals, profile (UPI/bank), shop preview

## Implemented Features
- Auth: register (with optional sponsor code), login, /me, logout, JWT Bearer
- Mock UPI payment for ₹100 registration fee (`/api/payment/register-fee`)
- 1+4 referral payout engine (auto-credits ₹400 to sponsor on 4th paid direct)
- User dashboard, network tree (4 levels deep)
- Bank/UPI update; withdrawal request with locked balance
- Admin: users list, payouts (pending/approved/rejected), transactions, stats
- E-commerce product catalog (seeded; cart deferred)
- Beautifully designed Organic Earthy theme (#143D2E primary, #E57A44 accent)
- testID attributes on key interactive elements

## Deferred / Future Scope
- Real Razorpay/Cashfree integration
- E-commerce cart, checkout, order management
- Mobile recharge API (Jolo/CyberPlat)
- Push notifications for payouts
- Referral link deep-linking

## API Surface (under `/api`)
Auth: `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `POST /auth/logout`
User: `GET /users/me/dashboard`, `GET /users/me/network`, `POST /users/me/bank`
Wallet: `POST /withdrawals`, `GET /withdrawals/me`, `GET /transactions/me`
Payment (mock): `POST /payment/register-fee`
Shop: `GET /products`
Admin: `GET /admin/users`, `GET /admin/withdrawals`, `POST /admin/withdrawals/{id}/approve|reject`, `GET /admin/transactions`, `GET /admin/stats`, `POST /admin/products`

## Smart Business Enhancement
The 1+4 recursive engine doubles as a viral growth loop: each ₹100 acquired user funds a ₹400 payout only after sourcing 4 paying users — guaranteeing 4× revenue per payout cycle. Every approved withdrawal recycles capital into the network without requiring outside funding.

## Test Credentials
See `/app/memory/test_credentials.md`
