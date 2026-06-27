# Slangcart — Emergent Web Job Setup Guide

## TL;DR
To get a public website URL (e.g. `https://slangcart-web.emergent.host`) for Slangcart, you need to create a **second Emergent job** using the **Full Stack App** template that shares the existing backend + MongoDB.

---

## Step 1 — Create the new web job

1. From the Emergent home, click **"+ New job"** (or "Create app").
2. Choose **"Full Stack App"** template (NOT mobile/Expo).
3. Name it `slangcart-web`.

## Step 2 — First prompt to the new agent

Paste this:

```
Build the WEB FRONTEND for my existing Slangcart app. It is a referral
+ e-commerce + chat platform.

DO NOT build a new backend or MongoDB — I already have those deployed
on Emergent at this URL:
   <your network-pay-1 backend URL — see Step 3>

The new web frontend should:
- Use Next.js (React) or Vite + React + TailwindCSS
- Talk to the existing backend via the EXPO_BACKEND_URL secret
- Implement these screens (parity with my mobile app):
  • Login (email + password, JWT)
  • Dashboard (referrals, wallet, network stats)
  • Shop (product listing, search, categories, product detail, cart, checkout)
  • Services (apply, invoices)
  • Slang-Connect chat (thread list + chat detail, with media)
  • Wallet (balance, transactions, withdrawals)
  • Network (matrix tree)
  • Profile (edit, notifications, change password)
  • Admin (/admin/users, /admin/products, /admin/orders, /admin/broadcast, /admin/branding)
- Use the same brand colors: primary green #0F6E4F, light green #E8F4ED
- Brand name: Slangcart
- Responsive design with a left sidebar on desktop (≥ 1024px wide)
```

## Step 3 — Get your current backend URL

Open your **current job (`network-pay-1`)** → **Manage Deployments** → look at the "Your mobile app is deployed!" panel → the backend URL is shown there (or in **Secrets**).

It will look like: `https://network-pay-1.emergent.host`

## Step 4 — Set Secrets on the new web job

On the new job's **Manage Deployments → Secrets**, add these (copy values from `network-pay-1` Secrets):

| Key                          | Value                                                       |
|------------------------------|-------------------------------------------------------------|
| `EXPO_BACKEND_URL` *(required)* | The backend URL from Step 3                              |
| `JWT_SECRET` *(required)*    | Copy from `network-pay-1` — MUST be identical so logins work |
| `MONGO_URL`                  | Copy from `network-pay-1` (only needed if backend not shared) |
| `DB_NAME`                    | `referral_ecom_db`                                          |
| `EMERGENT_LLM_KEY`           | Copy from existing                                          |
| `EMERGENT_PUSH_KEY`          | Copy from existing                                          |
| `ADMIN_EMAIL`                | `support@networkrupay.com`                                  |
| `ADMIN_PASSWORD`             | Copy from existing                                          |
| `REGISTRATION_FEE`           | `100`                                                       |
| `PAYOUT_PER_LEVEL`           | Copy from existing                                          |

## Step 5 — Deploy

Click **Deploy** on the new job. In 5–10 min you'll get a permanent public URL like:

```
https://slangcart-web.emergent.host
```

## Step 6 — Verify same data as APK

1. Open the new URL in any desktop browser
2. Log in with the same email + password you use in the APK
3. Confirm you see the same wallet, chats, products, orders, network tree — it's the SAME backend, SAME database

---

## Important — your existing mobile job keeps working

Your current `network-pay-1` mobile job and the APK you installed continue to work independently. The new web job is a SEPARATE deployment that just happens to talk to the same backend + database.

---

## If you want a custom domain (slangcart.com)

After the web job is deployed:
1. Open the new web job's **Manage Deployments**
2. Look for **"Custom Domain"** or **"Add Domain"** option
3. Add your domain (e.g. `www.slangcart.com`)
4. Point your DNS CNAME → the Emergent URL
5. Wait for SSL provisioning (~5 min)
