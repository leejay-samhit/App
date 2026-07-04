# Cross-Job Update — Device Identity Fields on Add-Product (July 2026)

**For the `slangcart-web` job (the second Emergent workspace running the Next.js/Vite web frontend).**

---

## TL;DR
The backend hosted in this workspace (`network-pay-1`) was just extended with 3 new optional fields on the `Product` model. The mobile app already uses them. **Copy the prompt below into the `slangcart-web` job so its Add-Product form matches.**

---

## What changed on the backend (already deployed, no action needed)
The following endpoints now accept **3 additional optional fields** on the request body:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/vendor/me/products` | `POST` | Vendor create product |
| `/api/vendor/me/products/{id}` | `PATCH` | Vendor update product |
| `/api/admin/products` | `POST` | Admin create product |
| `/api/admin/products/{id}` | `PATCH` | Admin update product |

**New fields (all optional strings):**
```json
{
  "serial_number": "SN-2024-A12345678",  // free text, single unit tracking
  "imei_1": "490154203237518",           // 15 digits, Luhn-checksum-validated
  "imei_2": "356938035643809"            // 15 digits, dual-SIM devices
}
```

They also appear in every product **GET** response (`/api/products`, `/api/products/{id}`, `/api/vendor/me/products`, `/api/admin/products`).

**Verified working** via curl on `2026-07-04` — create/update/delete cycle for all three fields returned 200 OK.

---

## Prompt to paste into the `slangcart-web` job

```
Update the Add-Product and Edit-Product forms (both vendor and admin panels)
to include 3 new fields under a new "Device Identity" section:

1. Serial number  (free-text, auto-capitalized)
2. IMEI-1         (15-digit numeric, Luhn checksum validated)
3. IMEI-2         (15-digit numeric, Luhn checksum validated, for dual-SIM)

All three are OPTIONAL — vendors selling non-electronics can leave them blank.

Backend contract (already deployed, do NOT change):
- POST /api/vendor/me/products
- PATCH /api/vendor/me/products/{id}
- POST /api/admin/products
- PATCH /api/admin/products/{id}
Send these fields as { serial_number, imei_1, imei_2 } in the JSON body.
When editing an existing product, hydrate the form from the same field
names in the GET response.

Validation rules:
- IMEI must be exactly 15 numeric digits.
- IMEI must pass the Luhn checksum (see helper below).
- IMEI-1 and IMEI-2 cannot be identical.
- Block form submission if any IMEI is present but invalid.
- Show live inline feedback while typing:
    ✅ green "Valid IMEI (15/15)"     when digits==15 AND Luhn passes
    ⚠  red   "8/15 digits"             while still typing
    ⚠  red   "Failed Luhn checksum"    when digits==15 AND Luhn fails
    ⚠  red   "IMEI-1 and IMEI-2 cannot be identical"

Luhn checksum (paste this helper — same as the mobile app):

    export function isValidImei(raw) {
      if (!raw) return true;                 // optional field
      const digits = String(raw).replace(/\D/g, "");
      if (digits.length !== 15) return false;
      let sum = 0;
      for (let i = 0; i < 15; i++) {
        let n = parseInt(digits[i], 10);
        if ((15 - i) % 2 === 0) {            // "every second from right"
          n *= 2;
          if (n > 9) n -= 9;
        }
        sum += n;
      }
      return sum % 10 === 0;
    }

UI placement:
- Add a collapsible "Device Identity" section BETWEEN "Basics" and
  "Brand & Sub-features" so it's near the top but doesn't clutter the
  first fold. Icon: hash / #.
- Helper text under the section title:
    "Optional. For phones / branded electronics tracked per unit. IMEIs
     must be exactly 15 digits and pass the Luhn checksum."
- Sub-header on IMEI-2: "IMEI-2 (dual-SIM devices)"
- IMEI inputs should:
    - inputMode="numeric"
    - Strip non-digits on change: value.replace(/\D/g, "").slice(0, 15)
    - maxLength=15
    - Show current length ("8/15 digits") while typing
- Serial number input: autoCapitalize="characters", no length limit.

Sample valid IMEIs for testing (Luhn-passing):
  IMEI-1: 490154203237518
  IMEI-2: 356938035643809

Sample INVALID IMEI (fails Luhn — use to test error state):
  123456789012345

Do NOT change any other Add-Product fields, spec-tabs, or the master
search dropdown. Only ADD the Device Identity section. Verify by:
1. Creating a product with all 3 fields filled → confirm 200 OK and
   the fields appear in the vendor product list.
2. Editing that product → confirm the fields hydrate correctly.
3. Trying to save with imei_1=123456789012345 → confirm the form
   blocks submission and shows the Luhn error inline.
```

---

## Test credentials for the web job
- Admin: `support@networkrupay.com` / `Nlee@1115`
- Vendor: `test_alice_73dc7f@test.com` / `Passw0rd!`

Backend URL — the same `EXPO_BACKEND_URL` secret already configured in the `slangcart-web` job. No change needed.

---

## What already exists on THIS workspace (mobile + web-of-mobile-app at localhost:3000)
- ✅ `backend/models.py` — `ProductCreate` + `ProductUpdate` accept `serial_number`, `imei_1`, `imei_2`
- ✅ `frontend/src/rich-product-editor.tsx` — Device Identity section with Luhn validation
- ✅ Verified end-to-end via curl and browser screenshots

## What DOESN'T exist yet on the separate `slangcart-web` workspace
- ❌ The 3 fields on its Add/Edit-Product form — **user must paste the prompt above into that job**
