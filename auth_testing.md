# Auth Testing Playbook (Emergent Google Auth + JWT)

## Setup notes
- App uses **JWT Bearer tokens** stored in AsyncStorage on mobile (NOT cookies — adapted from the web pattern).
- Emergent Google auth flow on Expo:
  1. Frontend opens `https://auth.emergentagent.com/?redirect=<EXPO_PUBLIC_BACKEND_URL>/api/auth/google/callback` via `WebBrowser.openAuthSessionAsync`.
  2. After Google login the URL lands on `/api/auth/google/callback#session_id=…`. The WebBrowser returns the URL to the app.
  3. App parses `session_id` and POSTs to `/api/auth/google/exchange` (with optional `referral_code`).
  4. Backend calls Emergent `/session-data`, finds/creates the user, returns our JWT bearer token + user.
  5. App stores token in AsyncStorage and navigates as usual.

## Quick backend test
Requires a real Emergent session_id obtained via the auth UI — cannot be mocked easily. For automated unit tests, mock the `httpx` call to Emergent's `/session-data`.

## Allowed test accounts
Any Google account works (Emergent allowlist not enforced). Use a personal Google account during manual UI tests.

## Things to verify
- New Google sign-in creates user with `kyc_status='none'`, `registration_paid=false`, generates referral_code, optional sponsor link via `referral_code`.
- Returning Google user (same email) does NOT create a duplicate; existing record is reused.
- Blocked users (`is_blocked=true`) get 403 even via Google.
- After Google auth, all existing endpoints (`/api/auth/me`, dashboard, etc.) work with the returned Bearer token.
- Email/password login still works (backwards compatible).
