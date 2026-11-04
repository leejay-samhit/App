# Festival Themes (Oct-2026)

One-tap seasonal re-skin of the whole app, driven from
**Admin → Branding → Festival Themes**.

## How it works

A festival theme is NOT a second styling system. It writes a named palette
into the **existing branding document**, so every screen that already themes
itself from branding picks it up with no per-screen work.

```
core/festival_themes.py   registry: 10 festivals, palettes, gradients, decor
routes/festival_themes.py apply / clear / artwork / public listing + proxy
core/object_storage.py    Emergent Managed Object Storage helpers
src/theme.ts              palette boot: SYNCHRONOUS read before any StyleSheet
src/sync-store.ts(.native) localStorage (web) / expo-sqlite kv-store (native)
src/branding.tsx          festival field, theme_version polling, remount epoch
src/festival-decor.tsx    drawn diyas / rangoli / banner (react-native-svg)
src/admin-festival-themes.tsx  the admin cards, inline preview, apply/restore
```

## The one hard problem, and the fix

`StyleSheet.create` **snapshots** the colour values it reads, and Expo Router
evaluates every route module at bundle start — long before an async storage
read or a network call could resolve. So an async palette can never reach
those styles: screens keep the factory green for the whole session (it showed
up as a green cart button and green active tab sitting in a purple Deepavali
home screen).

Fix: the live palette is mirrored into **synchronous** storage and read back
in `theme.ts` *at import time*:
- web → `localStorage`
- native → `expo-sqlite/kv-store` (`getItemSync`)

The two implementations live in separate files (`sync-store.ts` /
`sync-store.native.ts`) because expo-sqlite's web build pulls in a worker that
breaks the web bundle — a `Platform.OS` branch inside one file is not enough.

Result: **frame one of every launch is already in the active theme.**

## Propagation to open apps

`BrandingProvider` polls the tiny `/api/festival-theme/active` payload every
45 s and on every foreground, and refetches `/branding` only when
`theme_version` moves. A moved version bumps `themeEpoch`, which remounts the
navigator (`ThemeSwitchGate` in `app/_layout.tsx`). Everything that reads the
palette at render time — gradients, the festival banner, decorations, tab bar
tints — repaints immediately; the remaining StyleSheet-captured colours land
on the next app open, which is now pixel-perfect thanks to the sync palette.

## Deepavali (the designed theme)

- primary deep purple `#4C1D95`, royal-blue support, gold accent `#F59E0B`
- warm ivory surfaces (`#FFF8EE`) so product photos and prices stay readable
- dark festive hero gradient `#190A33 → #3B1178 → #7C2D12`, glow `#FBBF24`
- drawn decorations: lit clay diyas, rangoli arc, gold glow — no image
  download, nothing to upload
- optional AI banner artwork (Gemini `gemini-3.1-flash-image-preview`) stored
  in Emergent Object Storage and served through `/api/festival-artwork/...`

The other nine festivals ship as preview cards with their real palettes and a
COMING SOON badge; `available: False` makes the backend refuse to apply them.
Adding one later = flip `available` and fill in `colors` / `gradient` /
`decor` / `artwork_prompt`. No screen changes.

## Safety

- Only `super_admin` can apply, clear or generate artwork (verified by test:
  anonymous and buyer both get 401/403).
- Applying stashes the admin's own palette in `pre_festival_colors` /
  `pre_festival_gradient`, so **Restore default returns THEIR colours**, not
  the factory ones. Branding colour edits made *while* a festival is live are
  written into the stash too, otherwise they'd silently revert.
- Re-applying the same festival never overwrites the stash.
- `POST /admin/branding/reset` now also clears the festival, so festive
  decorations can't sit on top of the factory green.
- `app_name`, `tabs` and support details are untouched by a theme change —
  the Slangcart name stays visible on every theme.
- No business logic, money, orders, permissions or user data is touched;
  a test asserts the wallet payload is byte-identical across apply+clear.

## Tests

`backend/tests/test_festival_themes.py` — 15 passed. The autouse fixture
snapshots and **replaces the whole branding document** afterwards; an earlier
version only restored the festival id, and the reset test wiped the owner's
tagline (restored manually to "Billing. Shop. Service. Connect"). Never write
a destructive branding test without the full snapshot.

Browser-verified: all 10 cards render, inline preview shows the mock app in
the festival palette, Apply re-skins Shop / Wallet / tab bar / headers,
Restore returns the green theme and removes the festival banner.

## Known limitations

- **AI artwork is currently blocked**: the Emergent Universal Key returns
  `API key is inactive`, so `/admin/festival-theme/artwork` reports
  `Artwork generation failed: ... API key is inactive`. The owner needs to
  top up the Universal Key balance (Profile → Manage plan → Universal Key).
  The drawn decorations work without it, so the theme is complete regardless.
- Open apps get the full palette on their next open (45 s poll handles the
  live parts). There is no forced JS reload — adding one would need
  expo-updates and would interrupt anyone mid-checkout.
- Festival dates are not automated; the theme only changes when an admin
  taps Apply (the owner chose this).

## Iteration 107 — screen-by-screen audit

Hard-coded greens that the theme could not reach, now fixed with the new
`withAlpha(colors.primary, a)` helper in `src/theme.ts` (never hand-write
`rgba(20,61,46,...)` again — it freezes the factory green):
- `app/_layout.tsx` root container background → `colors.primary`
- `app/product/[id].tsx` image-carousel dots
- `app/(tabs)/dashboard.tsx` cashback sparkline fill
- `app/chat/[id].tsx` reaction chips on other people's messages

Deliberately left alone: admin role chips (semantic identity colours), the
`primary`/`emerald` entries in `gradient-card.tsx` (they ARE the default
theme), iOS shadow tints `#0F2A1D` (invisible in practice) and the Android
background-location notification colour (an OS notification, not app chrome).

Browser audit with Deepavali applied — a computed-style sweep for the three
brand greens (`#143D2E`, `#2C6B50`, `#1F5E45`) across every element:

| screen | result |
|---|---|
| shop, services, dashboard, chat | no old-green |
| wallet, cart, orders, profile | no old-green |
| login (logged out, with diyas + rangoli) | no old-green |
| product detail, checkout | no old-green |
| vendor my-shop, vendor dashboard | no old-green |

Functional check with the theme live: add-to-cart worked, checkout showed the
item, delivery and total, Place Order present. `/auth/me` and
`/wallet/summary` are identical across an apply+restore cycle (asserted).

Artwork endpoint now returns **424**, not 502: the ingress replaces 5xx bodies
with a generic HTML error page, which hid the real reason from the admin
screen. Upstream HTML blobs are collapsed to a short sentence by `_short()`.

Tests: `test_festival_themes.py` 15 + `test_iter107_festival_authz_integrity.py`
11 = 26 passed, in both file orders (both files snapshot and replace the whole
branding document, so they never leave the owner's theme or text changed).


## Nov 2026 — all ten festivals are live

The nine placeholders are gone. Every festival now ships a complete design in
`core/festival_themes.py` (`_theme(...)`): a full palette, a dark festive hero
gradient, a drawn decoration and an AI artwork prompt. The backend no longer
has any `available: False` card, so the admin can preview and apply all ten.

Drawn decorations (`src/festival-icons.tsx`) — the strip, banner and corner
mark no longer repeat the same diya everywhere; each festival gets its own
react-native-svg icon mapped from `decor.pattern`:

  deepavali=diya · ugadi=mango-leaf kalasha · independence_day=tiranga shield
  with chakra · ganesh_chaturthi=modak · dussehra=bow & arrows ·
  maha_shivaratri=trishul · ramzan=crescent & star · christmas=tree & star ·
  new_year=fireworks · sankranti=kite

Palettes per festival (primary): Ugadi mango green, Independence Day navy with
saffron accent, Ganesh Chaturthi vermilion, Dussehra royal red, Maha
Shivaratri moonlit indigo, Ramzan emerald, Christmas pine, New Year midnight,
Sankranti harvest gold.

Tests: `test_festival_themes.py` now asserts every festival is applicable,
carries a complete palette + gradient + decor, has a DISTINCT decoration
pattern, applies with the right palette and restores cleanly, and that
A→B→restore still returns the admin's own colour. The two tests that encoded
the old "only Deepavali" contract were rewritten (unknown ids are still 404).
`test_festival_themes.py` (17) + `test_iter107_festival_authz_integrity.py`
(12) = **29 passed**.

Browser-verified end to end: all 10 cards render, Christmas applies (the whole
chrome re-skins: pine header, snow surfaces, berry-red CTA, LIVE chip), and
Restore default returns the standard Slangcart green. Branding doc left in the
default state (no active festival, tagline intact).

Known limitation (unchanged): AI banner artwork still needs the Emergent
Universal Key topped up — the drawn decorations work without it.
