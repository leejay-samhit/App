# Registration + Truecaller + payment-choice flow (Oct 2026)

## 1. Files changed

### New
| File | Purpose |
|---|---|
| `frontend/modules/truecaller/expo-module.config.json` | Registers the local Android module |
| `frontend/modules/truecaller/package.json` | Local module manifest |
| `frontend/modules/truecaller/android/build.gradle` | Pins `com.truecaller.android.sdk:truecaller-sdk:3.3.0` (Maven Central) |
| `frontend/modules/truecaller/android/src/main/java/com/slangcart/truecaller/TruecallerModule.kt` | OAuth consent flow: `TcSdkOptions.Builder` → `TcSdk.initAsync` → `isOAuthFlowUsable` → `setOAuthState` / `setOAuthScopes` / `setCodeChallenge` → `getAuthorizationCode` |
| `frontend/modules/truecaller/index.ts` | JS wrapper; resolves with the one-time code, rejects with a reason |
| `frontend/plugins/withTruecaller.js` | Injects `com.truecaller.android.sdk.ClientId` into the merged manifest |
| `backend/routes/truecaller_auth.py` | `/auth/truecaller/availability`, `/start`, `/verify` |
| `backend/core/pkce.py` | S256 code-challenge derivation |
| `backend/tests/test_registration_flow.py` | The owner's ten scenarios |

### Modified
| File | Change |
|---|---|
| `frontend/app.json` | Added the `./plugins/withTruecaller` plugin |
| `frontend/src/signup-gate-card.tsx` | "STEP 1 · VERIFY YOUR MOBILE NUMBER", a **Verify with Truecaller** button, an OR divider, and manual entry retained as the fallback |
| `frontend/app/payment.tsx` | "Complete Your Registration" title + description, a "STEP 2 · CHOOSE HOW TO CONTINUE" block, reworded lock note |
| `frontend/src/subscription.tsx` | Button label → **Continue Without Fee** (and its confirm dialog) |
| `backend/routes/signup_gate.py` | Derived `registration_status` / `registration_path` / `phone_verified*` / `auth_provider` / `truecaller_available`; manual entry records `phone_verified_method: "self_declared"` |
| `backend/server.py` | Mounted the Truecaller router + its index setup; **`/payment/verify` now requires a matching registration order for THIS user and short-circuits a repeat callback** |

Untouched on purpose: Razorpay keys/flow, GST split, cashback rules, wallet
accounting, transaction shapes, Google sign-in, manual registration, login
sessions and every existing MongoDB record.

## 2. Truecaller configuration required

In the **non-EU** console (`sdk-console-noneu.truecaller.com`):

1. Android credential with package **`com.slangcart.app`**.
2. Register the **SHA-1 fingerprint of every build variant** you ship —
   including the Emergent release signing key. A wrong/missing SHA-1 is the
   number-one cause of "unavailable" at runtime.
3. Enable scopes **`openid`, `profile`, `phone`** (the module requests exactly
   these; `openid` is required or `userinfo` returns 422).

## 3. Environment variables

| Name | Where | Why |
|---|---|---|
| `TRUECALLER_CLIENT_ID` | backend `.env` | Server-side token exchange (`/v1/token`) |
| `EXPO_PUBLIC_TRUECALLER_CLIENT_ID` | frontend `.env` | Read at prebuild and written into the Android manifest |

Both were supplied through the secure key card. An Android OAuth client ID is
necessarily shipped inside the APK, so it is an identifier rather than a
secret — the backend still verifies every code with Truecaller.

If either is missing, the build still succeeds: the plugin logs a warning, the
button is hidden and manual entry is the only path.

## 4. Backend behaviour

```
POST /api/auth/truecaller/start    → { state, code_challenge, scopes, ttl_seconds }
POST /api/auth/truecaller/verify   → { ok, phone, method, invite_code, user }
GET  /api/auth/truecaller/availability
```

* The **server** mints the `state` and the PKCE `code_verifier` and keeps the
  verifier (TTL collection `truecaller_states`, 5-minute window, single use).
  The app never sees it, so it cannot fabricate a pass.
* `/verify` consumes the state, exchanges the code at
  `https://oauth-account-noneu.truecaller.com/v1/token`, reads the number from
  `/v1/userinfo`, and only then sets `phone_verified: true`,
  `phone_verified_method: "truecaller"`, `phone_verified_at`, `truecaller_sub`.
* Duplicate protection reuses the signup-gate rules: a number owned by another
  account is refused (409) and never merged; an account that already has a
  *verified* number cannot silently swap it.
* Status is **derived**, never stored twice:
  `pending_verification` → `verified` → `payment_success` | `free_registration`,
  with `registration_path` = `paid` | `free` | `undecided`, read from the
  existing `phone_verified`, `registration_paid` and `subscription_skipped`
  fields.
* `POST /payment/skip-subscription` is unchanged and creates **no** transaction
  row — the free path never fabricates a payment.
* **Fix found by testing:** `/payment/verify` accepted any `razorpay_order_id`.
  In sandbox (where the gateway is simulated) a caller could post an invented
  order id and be marked paid. It now requires a `registration_fee` row for
  this user with that exact order id, and returns
  `{status: success, already_processed: true}` for a repeat callback.

## 5. Android build instructions

1. Publish → Deploy, then generate the **Android build** (the Kotlin and the
   Truecaller SDK compile for the first time there — they cannot compile in
   this container, which has no JDK, Gradle or Android SDK).
2. After `expo prebuild`, the merged manifest must contain
   `com.truecaller.android.sdk.ClientId`. The config plugin writes it from
   `EXPO_PUBLIC_TRUECALLER_CLIENT_ID`.
3. Install on a real Android phone **with the Truecaller app installed and
   signed in**, using a build whose SHA-1 is registered in the console.
4. R8 is on: the SDK ships consumer ProGuard rules, so no app-level keep block
   was added. If a minified build misbehaves, add
   `-keep class com.truecaller.android.sdk.** { *; }` and retest.

## 6. Test results

`backend/tests/test_registration_flow.py` — **51 passed, 0 failed**:

| Scenario | Result |
|---|---|
| 1 & 3 — manual registration → verify → pay / free | pass |
| 2 & 4 — Google account → verify → pay / free (provider preserved) | pass |
| 5 — Truecaller unavailable / cancelled / forged / replayed / expired / another account's state | pass (manual fallback works) |
| 6 — bad or unmatched payment callback | pass (account not marked paid) |
| 7 — duplicate payment callback | pass (no extra money rows) |
| 8 — already-verified account | pass (not asked again) |
| 9 — number owned by another account | pass (409, owner named, no takeover) |
| 10 — logout then login | pass (state and number survive) |
| ₹118 / 11800 paise shown and charged | pass |
| Shopping, cart, orders, wallet, admin unaffected | pass |

Regression: membership 35, SIM-binding 64, iter103 13, iter104 11, owner batch
13, iter98+99 20 — all green.

UI verified in the preview: "Complete Your Registration" + description, Step 1
card with manual entry (the Truecaller button is correctly hidden on web),
"Mobile verified" strip, Step 2 block, **Pay ₹118** and **Continue Without
Fee**.

## 7. Remaining blockers / honest limits

* **The Truecaller consent sheet has never run.** It needs a real Android
  build plus a registered SHA-1 and the Truecaller app on the device. The
  Kotlin also compiles for the first time in that build.
* **Razorpay stays in sandbox here**, so the live HMAC signature check in
  `/payment/verify` (unchanged) is still unexercised against real money.
* Truecaller became commercial on 1 Apr 2026 — per-verification charges apply;
  get written pricing before high volume.
* iOS and the website have no Truecaller SDK: both fall back to manual number
  entry, which is recorded as `self_declared` and never claimed as verified.

## Post-review hardening (iteration 105)

Fixes applied after the independent review:

1. **Legacy `/payment/register-fee` removed** — a leftover backward-compat
   mock endpoint marked an account paid without any gateway proof. Deleted;
   nothing in the app referenced it.
2. **Phone uniqueness is now enforced in the database** — partial unique
   index on `users.phone` (non-empty strings only), created at startup by
   `signup_gate.ensure_indexes()`. Both the manual confirm route and the
   Truecaller verify route catch `DuplicateKeyError` and return HTTP 409
   with `PHONE_TAKEN_MESSAGE`. Closes the parallel-request race that could
   previously attach one number to two accounts.
3. **Gate enforced on every payment path** — `/payment/skip-subscription`,
   `/payment/create-order` and `/payment/verify` all call the shared gate
   guard, so an unverified account cannot finish registration by calling
   the API directly while the UI is bypassed.
4. **Verified numbers cannot be silently swapped** — the manual confirm
   route refuses to overwrite a number that was verified by Truecaller.
5. **Payment verify is idempotent before the "already paid" guard** — a
   repeated or retried gateway callback for an order that is already
   settled returns `already_processed` instead of HTTP 400, while money
   still moves exactly once (one settlement row, one fee row, one cashback).
6. **Gate card fails closed** — if the status read fails, the screen stays
   locked instead of unlocking both registration options.
7. **Honest verification labels** — the confirmation strip reads "Mobile
   number verified (Truecaller)" only when the method really is Truecaller;
   a self-declared number reads "Mobile number saved". The web/Expo Go copy
   no longer promises Truecaller when the native module is unavailable.
8. **Native module corrections** — the Android bridge now registers its
   activity-result launcher through `activityResultRegistry`, waits for
   `onSdkReady` before claiming availability, and runs SDK calls on the
   main queue (`Queues.MAIN`).
9. **Pay CTA restyled to dark green** (`colors.primary`) to match the
   requested green / white / dark-green registration palette.

Index housekeeping note: three seeded test accounts shared placeholder
numbers with other fixtures; their `phone` was cleared so the unique index
could build. No real account was altered or deleted.

## Iteration 106 — adversarial re-verification

New suite: `backend/tests/test_iter106_adversarial.py` (12 tests, all green).
It seeds accounts directly in Mongo and mints tokens, because /auth/register
is deliberately rate limited to 5/min per IP and these probes need ~20
accounts.

Proven by test, not by reading code:
- `POST /api/payment/register-fee` returns 404 and leaves `registration_paid`
  false.
- `/payment/skip-subscription`, `/payment/create-order` and `/payment/verify`
  all return 403 for an account with no number on file.
- Five accounts confirming the SAME number in parallel: at most one 200 and
  exactly one account ends up owning the number.
- `+91…`, `0…`, spaced and padded variants all normalise to the same ten
  digits, so no format trick dodges the unique index. (Only signup_gate and
  truecaller_auth ever write `users.phone`, and both normalise first, so the
  index really is on a canonical value.)
- A self-declared number reports `phone_verified_method: "self_declared"`
  and never `phone_verified: true`.
- A callback for an order we never created is refused; one user cannot
  settle another user's order.
- The free path leaves `registration_paid` false, `subscription_active`
  false, an empty wallet, and withdrawal refused.
- All three Truecaller routes refuse anonymous callers; forged state and
  bogus authorization codes are refused and never set `phone_verified`.

### Sandbox payment hardening (the reviewer's HIGH finding)

In mock mode the gateway is simulated, so the client signs its own callback
and there is nothing real to verify. New env switch `ALLOW_MOCK_PAYMENTS`
(backend, default `true` for preview): when it is `false` and no live
Razorpay keys are present, `/payment/verify` returns 503 instead of settling,
and `/payment/config` reports `payment_enabled: false` so the UI greys out
the Pay button and explains that online payment is being set up. Adding live
Razorpay keys makes the switch irrelevant, since `is_mock` then goes false
and the full HMAC + Razorpay API cross-check applies.

**Before taking real money the owner must add live Razorpay keys** (or set
`ALLOW_MOCK_PAYMENTS=false`), otherwise the sandbox path would let a client
self-declare a ₹118 payment.

### Frontend fail-closed, verified in the browser

With `/api/auth/signup-gate/status` aborted, `/payment` renders Step 1 only:
Step 2 and the confirmation strip stay hidden. `onStartCheckout` also guards
on `gatePassed` and `payment_enabled` so a stale render cannot start a
checkout. The "Continue Without Fee" button now surfaces the server's own
reason (e.g. the 403 gate message) instead of blaming the connection.

### Regression after all of the above
test_registration_flow.py 51 passed · test_iter105_registration_probe.py 21
passed · test_iter105_regression_smoke.py 17 passed ·
test_iter106_adversarial.py 12 passed · test_sim_binding.py 64 passed ·
test_iter103 + test_iter104 24 passed · test_membership_batch.py 35 passed ·
reconcile_vendor_ledger.py --dry-run: already balanced.

### Known, accepted, pre-existing
- Live mode falls back to trusting the Razorpay HMAC when the Razorpay API
  is unreachable (predates this task).
- `server.py` is ~11k lines and wants splitting.
- The Truecaller native SDK still cannot run on web or Expo Go; the console
  must carry `com.slangcart.app` plus the build's signing fingerprint, and
  the one-tap flow can only be confirmed on a real Android build.
