# Phase 3 — Anti-Tampering Deployment Runbook

This document describes what the operator needs to do **once EAS Android
builds are unblocked** to fully activate every Phase 3 protection.

Phase 3 Session A + B have been shipped in code — but most of the native
checks only ACTIVATE in an EAS Dev Client / production build, not in Expo
Go. This runbook is the bridge from "code is ready" to "actually
protecting users in production".

---

## 0. Pre-flight checklist (before first EAS build)

- [ ] EAS Android build pipeline is unblocked (Expo billing / infra resolved)
- [ ] Production API hostname is finalised (e.g. `api.networkpay.in`)
- [ ] Production API has a valid TLS certificate (Let's Encrypt or otherwise)
- [ ] Google Play Console developer account is active
- [ ] App is uploaded to Play Console (at least internal-testing track)

---

## 1. SSL Pinning (Android)

### 1a. Extract the two SHA-256 pins
```bash
HOST=api.networkpay.in   # ← REPLACE
# Primary pin (current leaf cert public key):
openssl s_client -showcerts -servername "$HOST" -connect "$HOST:443" < /dev/null 2>/dev/null \
  | openssl x509 -pubkey -noout \
  | openssl pkey -pubin -outform der \
  | openssl dgst -sha256 -binary \
  | openssl enc -base64
# Backup pin (intermediate CA public key — let's encrypt R3 etc.):
# Copy the SECOND certificate block from the s_client output to /tmp/intermediate.pem then:
openssl x509 -in /tmp/intermediate.pem -pubkey -noout \
  | openssl pkey -pubin -outform der \
  | openssl dgst -sha256 -binary \
  | openssl enc -base64
```

### 1b. Update the four `REPLACE_WITH_*` placeholders

**File 1:** `/app/frontend/assets/network_security_config.xml` (Android)
- Replace `REPLACE_WITH_PROD_API_HOSTNAME` with the hostname
- Replace both `REPLACE_WITH_PRIMARY_PIN_SHA256_BASE64` and `REPLACE_WITH_BACKUP_PIN_SHA256_BASE64`

**File 2:** `/app/frontend/app.json` (iOS)
- Same three replacements inside `ios.infoPlist.NSAppTransportSecurity.NSPinnedDomains`

### 1c. Test BEFORE shipping to production
1. Build an EAS Dev Client (`eas build --profile development --platform android`).
2. Install the APK on a real device.
3. Hit the API normally — should work.
4. Set up `mitmproxy` on your laptop, set the device's Wi-Fi proxy to the laptop. Install the mitmproxy CA into the device.
5. Open the app and try any API call. It MUST FAIL with a TLS handshake error. If it succeeds, pinning isn't active.

### 1d. Kill switch (cert rotation emergency)
If a cert rotation bricks the app:
- Ship a hotfix that **removes** the `<pin-set>` block from `network_security_config.xml` (keeping `<domain-config>` intact).
- The app falls back to standard CA trust — secure but unpinned.

---

## 2. Play Integrity API (Server-side verification)

### 2a. Set up GCP project
1. Open https://play.google.com/console → your app → **Setup → App integrity**.
2. Click **Link a Google Cloud project** → create one or pick an existing one.
3. In GCP Console, enable the **Play Integrity API**.
4. Create a service account: IAM → Service Accounts → "Create service account"; grant role **Play Integrity API · Service Account User**.
5. Download the JSON key for that service account.

### 2b. Configure backend
Place the JSON key on the production server, then:

```bash
# backend/.env
PLAY_INTEGRITY_ENABLED=1
PLAY_INTEGRITY_PACKAGE_NAME=com.networkpay.app   # ← REPLACE with your real package
GOOGLE_APPLICATION_CREDENTIALS=/secure/path/play-integrity-sa.json
```

Install Python deps:
```bash
cd /app/backend && pip install google-auth httpx && pip freeze > requirements.txt
sudo supervisorctl restart backend
```

Verify activation:
```bash
curl -s http://localhost:8001/api/branding > /dev/null  # any 200 works
grep "play integrity" /var/log/supervisor/backend.err.log    # should be silent (no warnings)
```

### 2c. Client-side token request (separate package)
Install on FE side (need EAS Dev Client first):
```bash
cd /app/frontend && yarn expo install react-native-google-play-integrity
```
Then update `frontend/src/tamper-detection.ts` `checkPlayIntegrity()` to call:
```ts
const { GooglePlayIntegrity } = require("react-native-google-play-integrity");
const nonce = await fetch("/api/security/integrity-nonce").then(r=>r.json());
const token = await GooglePlayIntegrity.requestIntegrityToken(nonce.value);
return { name: "play_integrity", passed: true, available: true, token };
```
(also add a `/api/security/integrity-nonce` endpoint returning a fresh UUID
nonce; the backend stores it in `nonces` collection with TTL=10min for replay protection)

---

## 3. APK Signature Verification

The Play Integrity token's `appIntegrity.appRecognitionVerdict` field is
the authoritative signal — `PLAY_RECOGNIZED` means the APK was signed with
your real upload-key AND distributed by Google Play. Anything else
(`UNRECOGNIZED_VERSION`, `UNEVALUATED`) means side-loaded / repackaged.

No additional code needed — `core/play_integrity.py.evaluate_verdicts()`
already includes this check.

---

## 4. ProGuard / Hermes obfuscation

Already enabled in `app.json` via `expo-build-properties`:
```json
"enableProguardInReleaseBuilds": true,
"enableShrinkResourcesInReleaseBuilds": true
```

Hermes is default in Expo SDK 50+. No action needed.

After a release build, verify obfuscation:
```bash
# Pull the APK
adb pull /data/app/com.networkpay.app-*/base.apk /tmp/
# Inspect — class names should be mangled (a, b, c...)
apkanalyzer dex packages /tmp/base.apk | head
```

---

## 5. Smoke-test runbook (post-deploy)

| Check | How to test | Expected |
|---|---|---|
| Root / jailbreak | Install on a rooted phone (Magisk) | App opens but `POST /api/withdrawals` returns 403 device_compromised |
| Emulator | Run on Android emulator | Same as above, plus integrity report has `emulator:warn` |
| Dev mode | Enable USB debugging | Same — read_only block |
| SSL pin | mitmproxy with cert | Network calls fail with TLS error |
| Play Integrity | Side-load APK from third-party store | `appRecognitionVerdict != PLAY_RECOGNIZED` → hard_block screen |
| Clean device | Stock Pixel + Play Store install | All checks pass, no block |

---

## 6. Operational maintenance

- **Cert rotation**: 30 days before expiry, deploy a build with the rotated cert's pin added. Wait until ≥95% of installs are on that build (Play Console gives you these stats), THEN rotate the cert on the server. The old pin remains valid as the backup until the next build cycle.
- **Play Console signing key**: do NOT lose your upload key — without it you cannot publish updates to the existing Play listing. Back up the keystore + password to a vault.
- **Disable hot fix**: to disable all anti-tamper checks in one place: set `PLAY_INTEGRITY_ENABLED=0`, ship a server-side change setting `block_level=none` for everyone (`db.users.update_many({}, {"$set":{"integrity_status.block_level":"none"}})`), restart backend.
