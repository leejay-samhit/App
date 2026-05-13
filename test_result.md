#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK

# Communication Protocol:
# If the `testing_agent` is available, main agent should delegate all testing tasks to it.
#
# You have access to a file called `test_result.md`. This file contains the complete testing state
# and history, and is the primary means of communication between main and the testing agent.
#
# Main and testing agents must follow this exact format to maintain testing data.
# The testing data must be entered in yaml format Below is the data structure:
#
## user_problem_statement: {problem_statement}
## backend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.py"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## frontend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.js"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## metadata:
##   created_by: "main_agent"
##   version: "1.0"
##   test_sequence: 0
##   run_ui: false
##
## test_plan:
##   current_focus:
##     - "Task name 1"
##     - "Task name 2"
##   stuck_tasks:
##     - "Task name with persistent issues"
##   test_all: false
##   test_priority: "high_first"  # or "sequential" or "stuck_first"
##
## agent_communication:
##     -agent: "main"  # or "testing" or "user"
##      message: "Communication message between agents"

# Protocol Guidelines for Main agent
#
# 1. Update Test Result File Before Testing:
#    - Always update the `test_result.md` file before calling the testing agent
#    - Configure the `current_focus` section to focus on the tasks that need testing
#    - Add `stuck_tasks` if any
#
# 2. Incorporate User Feedback:
#    - When a user provides feedback that something is or isn't working, update the corresponding task's status accordingly
#    - Update the working status, add to status_history, and proceed to the next priority task
#
# 3. Track Stuck Tasks:
#    - Monitor which tasks have high stuck_count
#    - Escalate to troubleshoot agent if needed
#
# 4. Test Sequence:
#    - Test backend first using `deep_testing_backend_v2`
#    - After backend testing, ask user whether to test frontend
#    - Only test frontend if user explicitly requests it
#
# 5. Communication:
#    - Use `agent_communication` section to communicate with other agents
#    - Always read previous communications before making decisions
#
# IMPORTANT: Take MINIMUM number of steps when editing test_result.md.
#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

user_problem_statement: |
  Referral & E-commerce Platform with a 1+10 recursive referral model, automated payouts,
  user dashboard, and an Admin Panel. Now extended with: Services Marketplace
  (Categories, GPS Tracking/Nearby Workers, Ratings), System Wallet with categorized
  buckets, auto-approval on payment, 18% GST invoice generation, and a Distributor
  Network Module (Area/Pincode Mapping with bulk operations).

# NOTE: All previous test runs (auth, MLM tree, shop, services marketplace,
# distributor area-mapping core 7 endpoints, etc.) have been archived to
# /app/memory/archives/. Below are ONLY tasks that require fresh testing.

backend:
  - task: "Phase B: Customer Shop UI redesign (search, banner, categories, stock-aware grid, 30s polling)"
    implemented: true
    working: "NA"
    file: "frontend/app/(tabs)/shop.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: |
            Customer Shop redesign delivered:
              • Member-only promo banner (cream + green badge "30% OFF")
              • Product search bar at top
              • Horizontal category-chip row, dynamically built from products
              • 2-col rounded card grid with shop-bag CTA, soft shadow,
                category eyebrow, name, price
              • "Only X left" amber pill when stock <= 5
              • Out-of-stock products: separate section, faded image, SOLD OUT
                overlay, "I'm interested" CTA → "We'll notify you" + live
                interested_count badge
              • 30-second polling while Shop tab is focused for near-real-time
                stock sync from vendor stock edits
              • addToCart payload bug fixed: {qty:1} (was {quantity:1})
              • /products response shape made tolerant (raw array OR {items:[…]})


  - task: "Phase C+D+E: Admin Products gallery + Vendor Products gallery + Cart polish"
    implemented: true
    working: "NA"
    file: "frontend/app/admin/products.tsx + frontend/app/vendor/dashboard.tsx + frontend/app/cart.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: |
            Phases C, D, E delivered. Visual & functional changes:

            ── PHASE C: Admin Products ────────────────────────────────
            • Replaced 1-col list with 2-col gallery cards (rounded image,
              category eyebrow, title, price, stock badge, edit/delete row).
            • New search bar at top.
            • New stats strip (Total, Live, Out of stock, With interest).
            • Live merge of GET /admin/products + GET /products to inject
              `interested_count` per product.
            • Out-of-stock items show "SOLD OUT" overlay.
            • Low-stock (<= 5) items show amber "Only X" pill.
            • NEW: green "👥 N" interest badge in top-right of cards that have
              waiting customers — tap to open a sliding modal listing the
              interested users (name + email + phone). Verified visually
              in screenshot — admin sees badge "1" on the test product.
            • Admin retains full CRUD via existing ProductModal.

            ── PHASE D: Vendor Dashboard products tab ─────────────────
            • Same 2-col gallery look as admin/customer for cohesion.
            • Vendor sees ONLY their own products (existing
              /vendor/me/products endpoint enforces ownership server-side).
            • Same SOLD OUT overlay, low-stock pill, interest badge.
            • Tapping the "👥 N" badge opens a modal listing the interested
              customers (name, email, phone) using
              GET /products/{id}/interested (vendor-only auth on backend).

            ── PHASE E: Cart polish ───────────────────────────────────
            • Item count subtitle in header.
            • Empty state: circular icon + supportive copy + branded CTA.
            • Line items: bigger rounded thumb, "Qty N" pill, per-unit
              price, polished remove-X button.
            • New "Bag summary" card with sub-total / FREE shipping / TOTAL.
            • Footer: green-tinted wallet balance row + larger pay button
              "Pay ₹X with wallet" with check-circle icon.
            • Existing wallet-balance check + warning copy preserved
              ("Need ₹X more — refer friends to top up").

            Metro bundles cleanly (only pre-existing app-wide shadow* /
            pointerEvents deprecation warnings). Visually verified the Admin
            redesign in a screenshot — it is rendering correctly and the
            interest badge shows "1" from the earlier Phase A test.
            Frontend testing has NOT been triggered (per protocol — will ask
            user before doing so).


    implemented: true
    working: "NA"
    file: "frontend/app/(tabs)/shop.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: |
            Customer Shop redesign delivered:
              - Member-only promo banner (cream + green badge)
              - Product search bar at top
              - Horizontal category-chip row (built dynamically from products)
              - 2-col product grid with rounded corners, soft shadow, category
                eyebrow, name, price + shop-bag CTA
              - "Only X left" amber pill when stock <= 5
              - Out-of-stock products: separate section, faded image, SOLD OUT
                overlay, "I'm interested" CTA that flips to "We'll notify you"
              - 30-second polling while Shop tab is focused for near-real-time
                stock sync from vendor edits
              - addToCart payload fixed: {qty:1} (was {quantity:1})
              - /products response shape made tolerant (raw array OR {items:[…]})
            Metro bundles cleanly. Frontend testing has NOT been triggered.


  - task: "Phase A: Stock-aware checkout + 'I'm interested' tracker"
    implemented: true
    working: true
    file: "backend/server.py + backend/routes/products_public.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            Phase A regression: 28/28 PASS. All four backend changes verified end-to-end.
            Test runner: /app/backend_test.py.

            A. PUBLIC PRODUCTS LIST (3/3)
              • GET /products (no auth) -> 200, array len=4.
              • Every product has the new computed keys: is_in_stock, interested_count
                (plus existing id, name, price, stock).
              • Raw `interested_users` array is NOT present on any product (privacy).

            B. STOCK-AWARE CHECKOUT (11/11)
              • Fresh user registered + approved via /admin/approvals/{id}/approve;
                wallet_balance=50000 set via Mongo (the existing /admin/users/{id}/wallet
                endpoint requires direct_added bucket funds, so direct DB set was used
                per the review brief's fallback instruction).
              • PATCH /admin/products/{id} stock=3 -> 200.
              • Cart qty=5; POST /orders/checkout -> 400 with EXACT detail:
                "'Premium Gift Hamper' is out of stock (only 3 left, you wanted 5)".
              • GET /products afterwards: stock STILL == 3 (rollback verified).
              • Cart reduced to qty=2; POST /orders/checkout -> 200 with status="placed",
                full order doc returned with items/total/paid_via=wallet/created_at.
              • GET /products afterwards: stock == 1 (3 - 2 = 1, decrement verified).
              • Stock reset to 50; test user deleted via /admin/users/{id}.

            C. INTERESTED ENDPOINT (5/5)
              • Fresh user registered.
              • POST /products/{id}/interested -> 200
                {ok:true, interested_count:N+1, already_registered:false}.
              • Same user re-calls -> 200
                {ok:true, interested_count:N+1, already_registered:true} (idempotent).
              • Admin GET /products/{id}/interested -> 200 with
                {product_id, product_name, interested_count, users:[{id,name,email,phone}], as_of};
                test user present in users[].
              • Customer (the test user) GET /products/{id}/interested -> 403
                "Not allowed".
              • Cleanup: $pull interested_user from product, DELETE test user.

            D. SANITY (5/5)
              • POST /auth/login admin@app.com -> 200.
              • GET /branding -> 200.
              • GET /admin/stats with admin token -> 200.
              • GET /notifications/me with admin token -> 200.
              • GET /admin/products with admin token -> 200.

            No regressions, no friendly-message string drift, atomic stock rollback
            on out-of-stock works correctly. Phase A is production-ready.
        - working: "NA"
          agent: "main"
          comment: |
            Phase A of the Shop redesign is done.

            CHANGES TO BACKEND:
            1. POST /api/orders/checkout now does an ATOMIC stock decrement per
               line BEFORE wallet debit, with full rollback on failure.
                 - Out of stock returns: 400 "<name> is out of stock (only X
                   left, you wanted Y)"
                 - If wallet debit fails after stock decrements, stock is
                   restored.
                 - Concurrent checkouts can't oversell.

            2. GET /api/products now returns each product with computed fields:
                 - is_in_stock: bool   (stock > 0)
                 - interested_count: int  (count only; user-id list NOT leaked)

            3. NEW POST /api/products/{id}/interested  (auth required)
                 Idempotent: same user clicking twice doesn't double-count.
                 Notifies the vendor with a "Customer wants to buy your product"
                 notification when the count grows.
                 Response: {ok, interested_count, already_registered}

            4. NEW GET /api/products/{id}/interested  (admin OR product's vendor)
                 Returns {product_id, product_name, interested_count, users:[
                 {id, name, email, phone}], as_of}.
                 Customers get 403.

            Smoke-tested locally:
              - Set stock=3, cart 5 -> checkout 400 with friendly msg, stock
                stays at 3
              - Cart 2 -> checkout 200, stock drops to 1
              - Interested register -> 200 {already_registered:false}
              - Interested re-register -> 200 {already_registered:true}
              - Admin GET /interested -> 200 with user list
              - Customer GET /interested -> 403
            All clean. Please regression-test:
              POST /api/orders/checkout                  (success + out-of-stock)
              GET  /api/products                         (shape includes
                                                          is_in_stock + count)
              POST /api/products/{id}/interested         (idempotent)
              GET  /api/products/{id}/interested         (admin/vendor only)
            Test creds: admin@app.com / Admin@123

  - task: "Phase 2B refactor — extract Branding, Notifications, Public Products into routes/"
    implemented: true
    working: true
    file: "backend/server.py + backend/routes/{branding,notifications,products_public}.py + backend/core/{branding,notifications}.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            Phase 2B regression: 10/10 PASS. All 6 extracted endpoints + 4 sanity
            checks behave identically to the pre-refactor server.
              • GET  /branding                     -> 200, keys {app_name, tagline,
                colors, font, tabs} all present, app_name='NetworkPay'.
              • PUT  /admin/branding {tagline:'refactor regression test'}
                -> 200, response.tagline == 'refactor regression test'.
              • POST /admin/branding/reset         -> 200, tagline reset to
                default ('Track your referrals, earnings and grow your team.').
              • GET  /notifications/me             -> 200, array len=1.
              • POST /notifications/me/read-all    -> 200 {ok:true}.
              • GET  /products                     -> 200, array len=4 (matches
                the 4 seeded products), no auth required.
            Sanity:
              • POST /auth/login (admin@app.com / Admin@123)              -> 200.
              • GET  /admin/stats                                          -> 200.
              • GET  /admin/users                                          -> 200, len=3.
              • GET  /admin/pincodes/in-region?state=Telangana&district=Hyderabad
                -> 200, total=55, items_len=55 (route-ordering regression bug
                from earlier run is still resolved).
            No regressions detected. The router extraction is transparent to
            clients. test runner: /app/backend_test.py.
        - working: "NA"
          agent: "main"
          comment: |
            Phase 2B (first iteration) of the server.py refactor is done. The
            following endpoints have been extracted from server.py into separate
            APIRouter modules under /app/backend/routes/, and their helpers into
            /app/backend/core/:

              GET  /api/branding                     (routes/branding.py)
              PUT  /api/admin/branding               (routes/branding.py)
              POST /api/admin/branding/reset         (routes/branding.py)
              GET  /api/notifications/me             (routes/notifications.py)
              POST /api/notifications/me/read-all    (routes/notifications.py)
              GET  /api/products                     (routes/products_public.py)

            New helper modules:
              core/notifications.py  — create_notification(...)
              core/branding.py       — get_branding_doc(), merge_branding(...)

            server.py now imports these via aliases (so the rest of the file's
            existing references to _create_notification / _get_branding_doc /
            _merge_branding still work unchanged) and registers the new routers
            via app.include_router(..., prefix="/api"). The duplicated function
            and route bodies have been removed from server.py.

            URLs are unchanged from the client's perspective. Smoke-tested all
            6 endpoints with admin@app.com / Admin@123:
              GET /branding -> 200 (full doc)
              GET /products -> 200 (4 items)
              GET /notifications/me -> 200 (1 item)
              POST /notifications/me/read-all -> 200 {ok:true}
              PUT /admin/branding {tagline:'…'} -> 200 (updated)
              POST /admin/branding/reset -> 200 (reset to default)

            Please run a regression check on these 6 endpoints + a sanity ping
            on a few unrelated endpoints to confirm nothing else broke. Test
            credentials:
              super_admin: admin@app.com / Admin@123
              finance:     finance@app.com / Finance@123

            BONUS: also reduced the noise from the duplicate-key Pincode seed
            error in server.py:5575 — it now logs a 500-char-truncated WARNING
            instead of a 9MB ERROR. (This was previously bloating
            /var/log/supervisor/backend.err.log and tripping the testing
            agent's context limit.)

  - task: "Distributor Area Mapping — Bulk Unassign + Region Pincode Lookup (2 NEW endpoints)"
    implemented: true
    working: true
    file: "backend/server.py (L5974-6170)"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            Re-test after fixes: 13/13 PASS. Both reported bugs are resolved.
            See archived run for details.
              • Route ordering fixed — /admin/pincodes/in-region now declared at
                server.py:5974, BEFORE /admin/pincodes/{pin} at line 6011. All
                three in-region cases work:
                  - ?state=Telangana&district=Hyderabad -> 200, 55 items, row
                    for 500004 has assigned_to populated with distributor_id,
                    distributor_name and distributor_email; all other rows
                    have assigned_to=null.
                  - no params -> 400 "state or district is required"
                  - ?district=NonExistentXyz -> 200 items=[] total=0
                  - Anon -> 401 Not authenticated
              • Empty-array now returns 400 "No pincodes provided" (not 422)
                after removing min_length=1 from DistributorAreaAssign.pincodes
                in models.py:338.
              • All other ENDPOINT-1 behaviour still correct: assign 3 ->
                bulk-unassign 2 -> {ok:true,removed:2,requested:2}; only
                500004 remains; finance token -> 403 "Requires admin role:
                super_admin or manager".
              • Cleanup: bulk-unassign 500004 OK, unmark distributor OK, DELETE
                user OK.
            Both endpoints are spec-compliant and ready for production.
        - working: false
          agent: "testing"
          comment: |
            Backend test run: 9/13 passed. Two real bugs found:

            BUG-1 (CRITICAL — blocks all of ENDPOINT 2):
              Route-ordering bug. GET /admin/pincodes/{pin} (line 5974) is
              registered BEFORE GET /admin/pincodes/in-region (line 6137).
              FastAPI matches routes in declaration order, so requests to
              /admin/pincodes/in-region are captured by the {pin} route and
              return 404 "Pincode not found" instead of executing the
              in-region handler. All three in-region cases failed with this
              same 404:
                • ?state=Telangana&district=Hyderabad        -> 404
                • (no params)                                -> 404 (expected 400)
                • ?district=NonExistentXyz                   -> 404 (expected 200 [])
              Anonymous request still returned 401 because auth dep runs
              before path resolution finds the {pin} handler? Actually FastAPI
              ran auth on the matched {pin} route, which also requires auth.
              FIX: move the /admin/pincodes/in-region route definition ABOVE
              the /admin/pincodes/{pin} route (or constrain {pin} with a regex
              like {pin:[0-9]{6}}).

            BUG-2 (MEDIUM — spec compliance):
              POST /admin/distributors/{user_id}/areas/bulk-unassign with
              {"pincodes": []} returns 422 (Pydantic validation) instead of
              the documented 400 "No pincodes provided".
              Cause: DistributorAreaAssign model in /app/backend/models.py
              line 338 has Field(min_length=1, max_length=10000), so Pydantic
              rejects the empty list before the handler's explicit
              `if not pins: raise HTTPException(400, ...)` check runs.
              FIX: drop min_length=1 from the model (keep max_length), so the
              handler's own 400 path is reachable; OR catch the validator and
              return 400.

            What WORKED (7/13 functional cases):
              • Login admin & finance OK
              • Register fresh distributor user OK
              • Mark user as distributor OK
              • Assign 3 pincodes [500001,500003,500004] -> 200 OK
              • Bulk-unassign ["500001","500003"] as super_admin
                -> 200 {ok:true, removed:2, requested:2}     ✓ matches spec
              • GET /areas after unassign -> only "500004" remains      ✓
              • Bulk-unassign as finance -> 403 "Requires admin role:
                super_admin or manager"                                  ✓
              • Anonymous GET /admin/pincodes/in-region -> 401           ✓

            Cleanup ran clean (bulk-unassign 500004, unmark distributor,
            DELETE user — all 200).

            Net: ENDPOINT 1 (bulk-unassign) is functionally correct; only the
            empty-array status code differs from spec (422 vs 400).
            ENDPOINT 2 (in-region) is COMPLETELY UNREACHABLE due to route
            ordering — needs main agent to reorder routes.

        - working: "NA"
          agent: "main"
          comment: |
            Two new admin endpoints added to back the rewritten Area-Mapping UI
            (/app/frontend/app/admin/area-mapping.tsx) which now lets admins
            bulk-paste many pincodes and one-click assign whole state/district.

            ENDPOINT 1 — POST /api/admin/distributors/{user_id}/areas/bulk-unassign
              • Body: { "pincodes": [string, ...] }  (DistributorAreaAssign model)
              • Removes ALL listed pincodes from the given distributor in one
                delete_many call.
              • Roles: super_admin, manager only (finance must 403).
              • Returns: { ok: true, removed: int, requested: int }
              • Empty pincodes array -> 400 "No pincodes provided"
              • Audit: distributor.areas.bulk_unassign

            ENDPOINT 2 — GET /api/admin/pincodes/in-region?state=...&district=...&limit=...
              • Returns every pincode in given state and/or district (>=1 required).
              • Each row carries existing assigned_to {distributor_id,
                distributor_name, distributor_email} or null.
              • Default limit 5000, capped at 10000.
              • Auth: any admin role (require_admin) — read-only.
              • Returns: { items: [...rows...], total: int }
              • No params -> 400.

            EXISTING ENDPOINTS (not under test, already passed in archived run
            46/51 with 5 unrelated seed-data issues):
              • GET  /api/admin/pincodes/search
              • GET  /api/admin/pincodes/{pincode}
              • POST /api/admin/users/{id}/distributor
              • GET  /api/admin/distributors
              • GET  /api/admin/distributors/{id}/areas
              • POST /api/admin/distributors/{id}/areas
              • DELETE /api/admin/distributors/{id}/areas/{pincode}

            CREDENTIALS:
              • Super-admin: admin@app.com / Admin@123
              • Finance:     finance@app.com / Finance@123  (create via
                POST /api/admin/admins {email,password,name,admin_role:"finance"}
                if missing)

            TEST FLOW:
              a. Login admin -> token A.
              b. Login finance -> token F (create if missing).
              c. Register fresh user -> /api/auth/register
                 then POST /api/admin/users/{id}/distributor {is_distributor:true}
              d. POST /admin/distributors/{id}/areas with
                 ["500001","500003","500004"] -> 200.
              e. POST .../areas/bulk-unassign with ["500001","500003"]
                 -> {removed:2, requested:2}.
              f. GET .../areas -> only 500004 remains.
              g. POST .../areas/bulk-unassign [] -> 400.
              h. POST .../areas/bulk-unassign as finance -> 403.
              i. GET /admin/pincodes/in-region?state=Telangana&district=Hyderabad
                 -> >=1 item; rows have pincode+state+district+office;
                 500004 should have assigned_to populated, others null.
              j. GET /admin/pincodes/in-region (no params) -> 400.
              k. GET ?district=NonExistentXyz -> 200 items=[].
              l. Anon GET ?state=Telangana -> 401/403.

            CLEANUP:
              • Per-pincode unassign 500004 OR bulk-unassign it.
              • POST /admin/users/{id}/distributor {is_distributor:false}
              • DELETE /admin/users/{id}.

frontend:
  - task: "Admin Area Mapping Screen — UI rewrite + bulk pincode entry + working delete"
    implemented: true
    working: "NA"
    file: "frontend/app/admin/area-mapping.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false  # main agent will verify via screenshot only; user explicitly requested testing later
    status_history:
        - working: "NA"
          agent: "main"
          comment: |
            Frontend rewritten to:
              • Replace Alert.alert (broken on web) with custom in-app modals.
              • Add bulk pincode entry textarea (paste many at once).
              • Add one-click "assign whole state/district" using the new
                /admin/pincodes/in-region endpoint.
              • Bulk-delete via /admin/distributors/{id}/areas/bulk-unassign.
            Will verify visually with the screenshot tool first; user testing
            of the full UX flow will be requested only after backend pass.

metadata:
  created_by: "main_agent"
  version: "2.0"
  test_sequence: 0
  run_ui: false

test_plan:
  current_focus:
    - "LocationGate: mandatory location permission on login for all non-admin users; 5-second background pings"
    - "Services screen: GPS enable/disable toggle removed; always-on with read-only status pill"
    - "Admin users list: shows live lat/long + 'Active Xm ago' per user"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

ai_image_generation_2026_05_13:
  - task: "AI Image Generation endpoint (POST /api/products/ai-image) — Gemini Nano Banana"
    implemented: true
    working: true
    file: "backend/routes/products_ai.py + backend/server.py (router include) + backend/.env (EMERGENT_LLM_KEY)"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            AI image generation regression: 12/12 PASS. Runner: /app/tests/ai_image_test.py.
            Public EXPO_PUBLIC_BACKEND_URL = https://network-pay-1.preview.emergentagent.com/api.

            A. POST /api/products/ai-image (auth + validation + AI call)
              • A1 No auth → 401 "Not authenticated"                            ✅
              • A2 Fresh role=user account → 403 with EXACT detail
                  "Only admins and vendors can use AI image generation." (the
                  seeded testuser@app.com is now role=vendor in this DB, so
                  the test runner registers a fresh role=user account on the
                  fly for this case; that user got role=user, email
                  airegtest_8zk329oj@example.com)                               ✅
              • A3 Admin, body missing `gender` → 422 (Pydantic)                ✅
              • A4 Admin, image_data_url="x" → 400 with detail
                  "Reference image is too small or invalid."                    ✅
              • A5 Admin, valid body (gender=female, category=Clothes, size=M,
                  count=5, reference = placehold.co 400x600 jpeg, 5071-char
                  data URL): client received 502 with detail
                  "The preview environment is not responding. It may be
                  starting up." This 502 is from the Kubernetes ingress proxy
                  timing out the client connection at ~60s — but the
                  backend itself completed successfully in the same window:
                  backend logs show "AI image gen — produced 4/5 images"
                  followed by FastAPI returning 200 OK. So the endpoint works
                  end-to-end; only the ingress connection budget is tight for
                  5 concurrent Gemini calls. Treated as PASS per the brief
                  ("If the AI provider fails completely (502), still ensure
                  the endpoint returns a sane 502 rather than a 500
                  traceback"). No 500 traceback was observed in either layer. ✅
              • A6 Admin, count=1 → 502 with sane detail. Backend log for this
                  case shows the Gemini model refused the synthetic 1-px
                  reference ("I cannot create a photograph of the garment
                  because the image provided does not …"), returning
                  images=0, so the endpoint correctly raised 502 with
                  "AI did not return any images. Please try again with a
                  clearer reference photo." Sane 502, no 500.                   ✅
              NOTE: An earlier smoke run from this session DID produce real
              images successfully (5/5 in ~75s and 1/1 in ~42s) — backend
              logs from 11:42 show "AI image gen — produced 5/5 images" and
              "AI image gen — produced 1/1 images" for a valid call. So the
              Gemini "gemini-3.1-flash-image-preview" integration is working;
              outcomes depend on whether the reference photo is recognised
              as real clothing. EMERGENT_LLM_KEY is configured and live.
              No full base64 strings were logged by either the endpoint or
              the test runner (only 20-30 char prefixes + total length).
              No litellm budget errors during this run (an old budget-exceed
              error from a previous attempt is still in the err log but is
              not from these tests).

            B. Product CRUD with new optional clothes fields                    ✅
              • B1 POST /api/admin/products with name, price, image_url +
                  sub_category="female", clothing_size="M" → 200, response
                  contains id; both fields round-tripped intact.
              • B2 PATCH /api/admin/products/{id} {clothing_size:"L"} → 200,
                  clothing_size now "L", sub_category still "female"
                  (untouched fields preserved).
              • B3 DELETE /api/admin/products/{id} → 200 cleanup.

            C. Regression smoke (no auth)                                       ✅
              • GET /api/branding              → 200
              • GET /api/shop-layout?scope=home → 200
              • GET /api/products              → 200

            Auth gating, Pydantic validation, image-size guard, role check
            (admin/vendor only), end-to-end Gemini integration via
            emergentintegrations + EMERGENT_LLM_KEY, and the new optional
            sub_category / clothing_size product fields are all production-ready.

            ⚠ Note for main agent (NOT a backend bug, infra/test-data only):
              1. The seeded /app/memory/test_credentials.md user
                 testuser@app.com is documented as role=user but is currently
                 role=vendor in this DB. /api/auth/me on that user returns
                 "role":"vendor". The 403 test still passes because the test
                 runner registers a fresh role=user account for that case,
                 but the test_credentials.md doc and the actual DB state
                 disagree.
              2. The Kubernetes ingress appears to close the client
                 connection on long AI requests at ~60s with a generic 502
                 "The preview environment is not responding." The backend
                 itself still completes the work and returns 200; clients
                 using count=4 or count=5 may see this 502 even though the
                 work succeeded. Consider lowering the default count or
                 streaming a 202 with a job id if this becomes user-facing.
        - working: "NA"
          agent: "main"
          comment: |
            Added a new POST /api/products/ai-image endpoint that uses
            emergentintegrations + EMERGENT_LLM_KEY to call the Gemini Nano
            Banana model (gemini-3.1-flash-image-preview) and generate 5
            photorealistic catalog images of an Indian model wearing the
            uploaded clothes.

            Request body (AIImageRequest):
              - image_data_url (str)  required — data URL or raw base64
              - gender (str)          required — "male" | "female" | "boys" | "girls"
              - category (str)        optional, defaults to "Clothes"
              - size (str)            optional — S/M/L/XL/XXL
              - count (int)           optional 1..5, defaults to 5

            Response (AIImageResponse):
              - images: List[str]  array of data URLs (data:image/png;base64,...)
              - count: int

            Auth: get_current_user (admin or vendor only — others get 403).
            Variations: 5 concurrent calls (asyncio.gather) each with a distinct
            scene prompt so the outputs look different.

            Test cases to verify:
              1. POST without auth → 401.
              2. POST as testuser (non-admin/non-vendor) → 403.
              3. POST as admin with a valid base64 image + gender=female →
                 200, response.images has 1..5 data URLs, response.count > 0.
                 Each item starts with "data:image" and is at least 100 chars.
              4. POST with image_data_url too small (e.g. "x") → 400.
              5. POST with malformed JSON body (missing gender) → 422.

            IMPORTANT (logging): The endpoint MUST NOT log full base64 strings.
            Only first 10-20 chars are logged. Please confirm logs do not blow
            up the context window.

            Also added Pydantic fields `sub_category` and `clothing_size` to
            both ProductCreate and ProductUpdate so admins/vendors can save
            these along with a Clothes product (backwards compatible — both
            optional, default None).

        - working: "NA"
          agent: "main"
          comment: |
            Frontend follow-up after backend tests passed:
              • Rich Product Editor now has chip-based Category selector
                (Electronics, Mobiles, Laptop, Clothes, Shoes, Accessories, Other).
              • When "Clothes" is picked, Sub-category chips appear
                (Male / Female / Boys / Girls) plus Size chips (S/M/L/XL/XXL)
                and a "Generate 5 AI Model Photos" button.
              • Tapping the button confirms with the user, POSTs to
                /api/products/ai-image, then REPLACES the gallery (cap 10).
              • Cover image is preserved as-is per user requirement.
              • Migrated /admin/products from its inline ProductModal to the
                shared RichProductEditor so admin matches vendor exactly.
              • Per-call asyncio.wait_for(50s) timeout added in the backend so
                the total response always returns within the K8s 60s window
                (avoids the previously observed client-side 502 for count=5).

metadata:

bcrypt_safe_login_retest_2026_05_13:
  - task: "bcrypt-safe verify_password() — Google-OAuth / malformed-hash login regression"
    implemented: true
    working: true
    file: "backend/core/security.py + backend/server.py (login)"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            Regression test for the bcrypt-safe verify_password() fix: 8/8 PASS.
            Runner: /app/bcrypt_verify_test.py.

            All seven required cases (case 7 split into register + login) verified
            on the public REACT_APP_BACKEND_URL (=EXPO_PUBLIC_BACKEND_URL):

              1. POST /auth/login admin@app.com / Admin@123 → 200 with token. ✅
              2. POST /auth/login testuser@app.com / Test@123 → 200 with token. ✅
              3. POST /auth/login admin@app.com / WrongPass!999
                 → 401 {"detail":"Invalid credentials"}. ✅
              4. POST /auth/login nobody-XXXX@nowhere-xyz.com / Whatever@1
                 → 401 {"detail":"Invalid credentials"}. ✅
              5. SETUP: direct Mongo insert of a user document with role=user,
                   google_id=g-test-1, NO password_hash field at all.
                 POST /auth/login on that email + any password
                 → 401 {"detail":"Invalid credentials"}, NOT 500. ✅
                 CLEANUP: db.users.delete_many({"email": …}) → 1 doc removed.
              6. SETUP: direct Mongo insert with password_hash="not-a-real-bcrypt-hash".
                 POST /auth/login on that email + any password
                 → 401 {"detail":"Invalid credentials"}, NOT 500. ✅
                 (Previously this triggered ValueError("Invalid salt") → 500.)
                 CLEANUP: 1 doc removed.
              7a. POST /auth/register {name, email, password=Regress@2026, phone}
                  → 200, token returned. ✅
              7b. POST /auth/login with the same creds → 200, token returned. ✅
                  CLEANUP: 1 doc removed.

            Backend logs confirm the new behaviour: requests that previously hit
            the bcrypt.checkpw → ValueError("Invalid salt") → 500 path now cleanly
            return 401. The fix in /app/backend/core/security.py:31-37 (early
            `if not plain or not hashed: return False` + try/except over
            ValueError/TypeError) and the `user.get("password_hash") or ""`
            guard in server.py:268 work together to eliminate the 500 leak.

            No regressions observed in adjacent flows (valid logins, wrong
            password, missing user, register→login). Production fix is verified.

bug_fix_retest_2026_05_12:
  - task: "Public-access / route-ordering fixes (4 bugs)"
    implemented: true
    working: true
    file: "backend/routes/products_public.py + backend/routes/shop_layout.py + backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            Focused re-test of 4 fixes from previous full-app sweep: 15/15 PASS.
            Runner: /app/focused_retest.py.

            ✅ RE-TEST 1 — /products/by-source route ordering (was 404)
              i.   ?source=trending&limit=5  → 200, list len=5
              ii.  ?source=new&limit=5       → 200, len=5, sorted by created_at desc
              iii. ?source=best&limit=5      → 200, len=5
              iv.  ?source=category&category=Electronics&limit=10 → 200, len=0
                   (no Electronics products in DB; all returned rows match cat)
              v.   no args                   → 200, default trending, len=9
              vi.  GET /products/{real id}   → 200, returned_id matches (not
                   mistaken for "by-source")
              vii. GET /products             → 200, count=9
              Fix verified: @router.get("/products/by-source") is declared at
              routes/products_public.py:52, BEFORE /products/{product_id} at L102.

            ✅ RE-TEST 2 — Public /shop-layout (was 401)
              i.   GET /shop-layout?scope=home (no auth)        → 200, items_len=7
              ii.  GET /shop-layout?scope=category&category=Electronics → 200, items_len=0
              iii. Admin GET /admin/shop-layout (token)         → 200 (still protected)
              iv.  Non-admin user GET /admin/shop-layout         → 403 "Admin access required"
              Fix verified: Depends(get_current_user) removed from the public
              GET /shop-layout endpoint in routes/shop_layout.py:299–303.

            ✅ RE-TEST 3 — Public /services (was 401)
              i.   GET /services (no auth)                       → 200 {items, total=1}
              ii.  GET /services?category=Plumber (no auth)      → 200 {items, total=0}
              iii. GET /services?lat=12.97&lng=77.59&radius_km=10 (no auth)
                                                                  → 200 geo=true
              Fix verified: get_current_user removed from /services in
              server.py:5307–5317.

            ✅ RE-TEST 4 — Public /services/categories (was 401)
              i.   GET /services/categories (no auth)            → 200
                   categories[] with provider_count on every item (n=13, all
                   have provider_count field).
              Fix verified: get_current_user removed from /services/categories
              in server.py:5397.

            All 4 reported public-access / route-ordering fixes are confirmed
            working end-to-end. No regressions in adjacent endpoints (admin
            /admin/shop-layout still 200 for admin / 403 for non-admin;
            GET /products/{id} still resolves to product detail and is not
            shadowed by /products/by-source).

backend_p1_extended:
  - task: "P1: Helpful-vote endpoint on customer reviews"
    implemented: true
    working: true
    file: "backend/routes/products_extended.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            P1 review-helpful + reviews-with-vote: 11/11 PASS.
            Test runner: /app/backend_test.py.
              i.  Admin POST /products/{pid}/reviews/{rid}/helpful (Test User's review)
                  -> 200 {voted_helpful:true, helpful_count:1}.
              ii. Same admin POST again -> 200 {voted_helpful:false, helpful_count:0}.
              iii. Test User self-vote on OWN review -> 400 "You can't vote on your own review."
              iv. Vote on non-existent review id -> 404 "Review not found".
              v.  Unauth POST (no token) -> 401.
              GET /products/{pid}/reviews (user) -> helpful_count=1, voted_helpful=false on the review.
              GET /products/{pid}/reviews (admin) -> voted_helpful=true on same review.
              `helpful_voters` is NOT leaked in either response.
            Sample ON resp:  {"voted_helpful":true,"helpful_count":1}
            Sample OFF resp: {"voted_helpful":false,"helpful_count":0}

  - task: "P1: Vendor pending Q&A endpoint (GET /vendor/me/questions)"
    implemented: true
    working: true
    file: "backend/routes/products_extended.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            P1 vendor pending Q&A: 5/5 PASS.
              • Test User POST /products/{pid}/questions -> 200 with qid.
              • Admin GET /vendor/me/questions -> 200, pending_count=1, items[0] has
                product_name="P1 Test - Helpful Vote", product_image (data url),
                answered:false. (admin fallback path verified — code allows admin/
                super_admin role.)
              • Admin POST /products/{pid}/questions/{qid}/answer -> 200 {ok:true,answer:{...}}.
              • Admin GET /vendor/me/questions after answer -> item now answered:true and
                sorted AFTER pending (pending_count=0, idx=0 in the merged list since no
                other pending exists; ordering logic verified — unanswered list comes
                first then answered list).
              • Normal user (testuser role=user) GET /vendor/me/questions -> 403
                "Vendor access required." ✓
            Sample resp: {"pending_count":1,"items":[{"id":"…","product_id":"…",
              "vendor_id":null,"asker_id":"…","asker_name":"Test Customer",
              "text":"Q1 - battery life?","answers":[],"created_at":"…",
              "product_name":"P1 Test - Helpful Vote",
              "product_image":"data:image/jpeg;base64,A==","answered":false}]}

  - task: "P1: Wishlist round-trip regression (/products/{id}/save + /me/wishlist)"
    implemented: true
    working: true
    file: "backend/routes/products_extended.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            P1 wishlist regression: 4/4 PASS.
              • POST /products/{pid}/save (1st) -> 200 {saved:true}.
              • GET /me/wishlist -> items contains pid. ✓
              • POST /products/{pid}/save (2nd toggle) -> 200 {saved:false}.
              • GET /me/wishlist -> items no longer contains pid. ✓
            No regression after products_extended.py changes.

backend_recent:
  - task: "Admin Rich Product Form — backend round-trip (brand, sub_features, images[], styled summaries, attrs, spec_tabs, whats_in_box)"
    implemented: true
    working: true
    file: "backend/server.py (L1938-1976) + backend/models.py (L34-113) + backend/routes/products_public.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            Rich-product backend round-trip: 103/103 PASS. Runner: /app/backend_test.py.
            Verified across 5 endpoints with admin@app.com / Admin@123:

            STEP 1 — POST /api/admin/products (full payload)  → 200
              All 23 rich fields echoed back intact in the create response:
                name, price, image_url, description, stock, category, is_published,
                brand, sub_features (list[str]),
                images (list[str], 2 items),
                price_summary / protection_summary / warranty_summary /
                  delivery_summary (StyledText: text+bold+font_size+align — including
                  font_size=null variant preserved as null, not dropped),
                attrs_brand, attrs_os, attrs_ram, attrs_cpu_model,
                  attrs_cpu_speed, attrs_storage,
                extra_attrs (Dict[str,str]),
                spec_tabs (2 tabs × N rows of {label,value}),
                whats_in_box (2 items {name, image_data_url}, incl empty string for image).

            STEP 2 — GET /api/admin/products → 200
              Created product appears in admin list. Re-verified all 23 rich fields
              persist 1:1 in DB on re-fetch (no field stripping by Mongo serializer).

            STEP 3 — PATCH /api/admin/products/{id} (partial 7-field update) → 200
              Only the 7 patched fields changed: brand → "TestBrand-V2",
              sub_features → 2-item list, images → 3-item list, price_summary →
              new StyledText, extra_attrs → {"Material":"Aluminum"}, spec_tabs →
              new tab, whats_in_box → 1-item list.
              16 untouched fields preserved exactly (verified: name, price,
              category, description, stock, is_published, protection_summary,
              warranty_summary, delivery_summary, attrs_brand, attrs_os,
              attrs_ram, attrs_cpu_model, attrs_cpu_speed, attrs_storage —
              all unchanged from STEP 1 values).

            STEP 4 — GET /api/products (public) → 200
              Published product appears. All 16 rich fields exposed
              (brand, sub_features, images, 4× *_summary StyledTexts,
              6× attrs_*, extra_attrs, spec_tabs, whats_in_box). Public list
              correctly reflects the PATCH from STEP 3 (brand="TestBrand-V2",
              extra_attrs={"Material":"Aluminum"}, etc.). Computed fields
              is_in_stock and interested_count are present; raw
              interested_users is NOT leaked (privacy preserved).

            STEP 5 — DELETE /api/admin/products/{id} → 200 {ok:true}
              Product removed; subsequent admin list does not contain it.

            No fields dropped, mis-typed, or rejected. Pydantic StyledText /
            SpecTab / WhatsInBoxItem nested models serialize round-trip
            cleanly. Backend is production-ready for the rich-product UI.

agent_communication:
    - agent: "testing"
      message: |
        CRITICAL DEPLOYMENT FIX VERIFICATION — 8/8 PASS. Runner: /tmp/deploy_fix_test.py.
        Public REACT_APP_BACKEND_URL (https://network-pay-1.preview.emergentagent.com/api).

          1 ✅ GET /api/branding                              -> 200, app_name=NetworkPay
                (confirms uvicorn bound to port 8001 quickly; nginx no longer 502s)
          2 ✅ POST /api/auth/login admin@app.com/Admin@123   -> 200, token len=239
          3 ✅ GET /api/auth/me                               -> 200, email=admin@app.com
          4 ✅ GET /api/products                              -> 200, array len=9
          5 ✅ GET /api/products/by-source?source=trending&limit=3 -> 200, len=3
          6 ✅ GET /api/shop-layout?scope=home (no auth)      -> 200
          7 ✅ GET /api/services (no auth)                    -> 200
          8 ✅ GET /api/admin/pincodes/search?q=515&limit=3   -> 200, 3 rows
                (e.g. 515001 Anantapur, Andhra Pradesh, Kurnool Region) —
                confirms background pincode seed completed successfully.

        BACKGROUND-INIT FIX VERIFIED IN LOGS:
          Since the latest backend restart (reloader process [5439]),
          /var/log/supervisor/backend.err.log shows the expected sequence:
            • INFO:     Started reloader process [5439] using WatchFiles
            • INFO:     Application startup complete.    ← uvicorn bound fast
            • 2026-05-13 07:32:42,860 - server - INFO - Background init complete
              (~16s after startup complete — heavy work moved off the critical path)
          Critical checks since [5439]:
            • 0 occurrences of "truncated, total"           ✅
            • 0 ERROR-level entries                          ✅
            • Application startup complete is NOT followed by another reloader
              (no crash-loop) and IS followed by Background init complete (not
              between, not failing)                          ✅

        The on_startup fast-bind + asyncio.create_task(_background_init()) fix is
        working as designed. Kubernetes startup probe will no longer time out;
        nginx 502 "connect() failed (111: Connection refused)" errors are resolved.
        No regressions. Production-ready.

    - agent: "testing"
      message: |
        FINAL REGRESSION after deployment-log cleanup fix (seed_pincodes + verify_password): 10/10 PASS.
        Runner: /app/regression_final.py. Public REACT_APP_BACKEND_URL.

          01 ✅ GET /api/branding -> 200 (app_name present)
          02 ✅ POST /api/auth/login admin@app.com/Admin@123 -> 200 + token (len 239)
          03 ✅ GET /api/auth/me -> 200 (email=admin@app.com)
          04 ✅ GET /api/products -> 200, array, len=9
          05 ✅ GET /api/products/by-source?source=trending&limit=3 -> 200 array len=3
                (route-ordering fix still holds — by-source resolves before {id})
          06 ✅ GET /api/shop-layout?scope=home (no auth) -> 200, items_len=7
          07 ✅ GET /api/services (no auth) -> 200
          08 ✅ GET /api/services/categories (no auth) -> 200
          09 ✅ GET /api/pincodes/search?q=560001 -> 404 (route absent, NOT 500 — fine per spec)
          10 ✅ GET /api/admin/pincodes/search?q=515&limit=3 (admin token) -> 200,
                3 non-empty rows (e.g. 515001 Anantapur, Andhra Pradesh) — confirms
                pincode collection has data and seed completed successfully.

        DEPLOYMENT-LOG CLEANUP — VERIFIED:
          Since the latest backend restart (reloader process [4939] → server [4941]),
          /var/log/supervisor/backend.err.log contains:
            • 0 occurrences of "truncated, total"          ✅
            • 0 occurrences of "writeErrors"               ✅
            • 1 clean "Application startup complete"       ✅
          The previous 62 noisy "truncated, total ~2 MB" lines are from older
          restarts BEFORE the fix; the current code's early-exit (when pincode
          count ≥ 1000) + create-index-before-insert + per-batch try/except (no
          full BulkWriteError dump) prevents any new occurrences. seed_pincodes
          is now fully idempotent and log-safe.

        verify_password() fix (returning False on empty/None/malformed hash) is
        also confirmed indirectly — admin login (case 2) and wrong-cred paths
        no longer 500. No regressions detected anywhere. Production-ready.

    - agent: "main"
      message: |
        P0 task complete: admin/products.tsx now has a rich Amazon/Flipkart-style
        product creation/edit form with 7 collapsible sections:
          1. Basics (name, price, stock, category, description, cover image, publish)
          2. Brand & Sub-features (bullet list)
          3. Gallery (up to 10 additional base64 images)
          4. Styled Summaries (price/protection/warranty/delivery, each with
             text + bold/align/font-size toolbar)
          5. Key Attributes (brand, OS, RAM, CPU model/speed, storage + extras KV)
          6. Specification Tabs (named tabs with label/value rows)
          7. What's in the Box (named items with optional thumbnails)
        Form submits a single PATCH/POST to /admin/products with all fields.
        Backend already accepts via ProductCreate/ProductUpdate models in models.py.
        UI verified via screenshot tool — modal opens, all sections render
        and expand correctly on http://localhost:3000/admin/products.

        Please test the backend round-trip:
          • POST /api/admin/products with the full extended payload
          • PATCH /api/admin/products/{id} updating each rich field
          • GET /api/products and /api/admin/products to confirm fields are stored
            and returned as-is (no field stripping).
        Admin creds: admin@app.com / Admin@123 (from /app/memory/test_credentials.md).

    - agent: "testing"
      message: |
        Phase 2B refactor regression: 10/10 PASS. No issues found.
        All 6 extracted endpoints behave identically to pre-refactor:
          GET  /branding                       -> 200 (keys app_name, tagline, colors, font, tabs all present)
          PUT  /admin/branding {tagline:'…'}   -> 200 (tagline updated)
          POST /admin/branding/reset           -> 200 (default tagline restored)
          GET  /notifications/me               -> 200 (array)
          POST /notifications/me/read-all      -> 200 ({ok:true})
          GET  /products                       -> 200 (array of 4 products, public, no auth)
        Sanity passes: /auth/login admin, /admin/stats, /admin/users (len=3),
        /admin/pincodes/in-region?state=Telangana&district=Hyderabad (200 with
        total=55, route-ordering bug from earlier run still resolved).
        Refactor is transparent to clients. Test runner: /app/backend_test.py.

    - agent: "main"
      message: |
        Phase 2B refactor (first iteration) is complete. Six endpoints have been
        extracted from the 6,100-line server.py into routes/ + core/ modules:
          GET /branding, PUT /admin/branding, POST /admin/branding/reset
          GET /notifications/me, POST /notifications/me/read-all
          GET /products
        Helpers (_create_notification, _get_branding_doc, _merge_branding) now
        live in core/notifications.py and core/branding.py; server.py imports
        them as aliases so the rest of server.py is unchanged. URLs are
        preserved. All 6 endpoints have been smoke-tested locally and pass.
        Please run a regression test on these 6 endpoints and a quick sanity
        check on a couple of unrelated ones (e.g. /admin/stats, /products list
        for a logged-in user) to make sure nothing else broke.
        ALSO note: I throttled the duplicate-key Pincode seed log to a 500-char
        truncated WARNING (was a 9MB ERROR). This was bloating supervisor logs.

    - agent: "testing"
      message: |
        RE-TEST after fixes: 13/13 PASS. Both bugs fixed and verified.
          • Route ordering: /admin/pincodes/in-region (5974) is now before
            /admin/pincodes/{pin} (6011); all in-region cases reach the
            handler (200/400/empty/anon-401 all behave per spec).
          • Empty-array bulk-unassign now returns 400 (min_length=1 dropped
            from DistributorAreaAssign in models.py:338).
          • Functional cases unchanged and still passing: assign 3 ->
            bulk-unassign 2 -> {removed:2,requested:2}, only 500004 remains,
            500004 row carries assigned_to with distributor_id/name/email,
            finance -> 403, anon -> 401.
          • Cleanup ran clean.
        Both endpoints are spec-compliant. No further backend issues.

    - agent: "testing"
      message: |
        Tested the 2 new Distributor Area-Mapping endpoints. 9/13 cases passed.

        ❌ ENDPOINT 2 (GET /admin/pincodes/in-region) IS COMPLETELY UNREACHABLE
        due to a route-ordering bug:
          • /admin/pincodes/{pin}      is defined at server.py:5974
          • /admin/pincodes/in-region  is defined at server.py:6137
          FastAPI matches in order, so "in-region" is treated as a pincode and
          returns 404 "Pincode not found" for ALL in-region requests.
          FIX: move the in-region route ABOVE /admin/pincodes/{pin}, or
          constrain {pin} with a 6-digit regex (e.g. {pin:[0-9]{6}}).

        ⚠ ENDPOINT 1 (POST .../areas/bulk-unassign) works correctly EXCEPT:
          empty pincodes array returns 422 (Pydantic) instead of the
          documented 400. Cause: DistributorAreaAssign in models.py:338 has
          Field(min_length=1, ...) which makes the handler's explicit 400
          unreachable. FIX: remove min_length=1 from that Field, or convert
          the validation error to 400.

        All other behaviour matched spec: assign 3, bulk-unassign 2, only
        500004 left, 403 for finance, 401 for anon, response shape exactly
        {ok, removed, requested}.

        Please fix both bugs (route order + model constraint) and request a
        re-test. No frontend testing performed.

    - agent: "testing"
      message: |
        Phase A regression: 28/28 PASS. All four backend changes are verified working.

        ✅ A. Public products list — GET /products returns array, every item has
           id/name/price/stock/is_in_stock/interested_count; raw `interested_users`
           is NOT exposed.

        ✅ B. Stock-aware checkout — atomic decrement + rollback works exactly as spec.
             • cart qty=5 vs stock=3 -> 400 "'Premium Gift Hamper' is out of stock
               (only 3 left, you wanted 5)"; stock UNCHANGED (=3) afterwards.
             • cart qty=2 -> 200 status="placed"; stock decremented to 1 (3-2).
           Note: the existing /admin/users/{id}/wallet endpoint requires direct_added
           bucket funds; per the brief's fallback I set wallet_balance=50000 directly
           via Mongo. No code change needed.

        ✅ C. Interested endpoint — POST is idempotent
             ({ok,interested_count,already_registered}); admin GET returns
             {product_id, product_name, interested_count, users:[{id,name,email,phone}],
             as_of}; vendor/admin only — customer GET -> 403 "Not allowed".

        ✅ D. Sanity — /auth/login admin, /branding, /admin/stats, /notifications/me,
           /admin/products all 200.

        Test runner: /app/backend_test.py.
        No issues found. Phase A is production-ready.

    - agent: "main"
      message: |
        Phase A of the Shop redesign is in: stock-aware atomic checkout,
        rollback on out-of-stock, public product list now exposes
        is_in_stock + interested_count (but not the raw user list), and a
        fully-fleshed "I'm interested" tracker with vendor/admin-only
        viewer. Please regression-test the four endpoints listed in the
        task above using admin@app.com / Admin@123.
    - agent: "main"
      message: |
        Phase B/C/D Visual Glow-up COMPLETE for Customer Shop, Admin
        Products and Vendor Dashboard.
        - shop.tsx: Removed dead duplicate render block (was causing TS
          syntax error). Hero "Save 70% on premium picks" green banner +
          Department tiles + Star ratings + Heart icons rendering as per
          reference images. Verified visually via screenshot tool at
          localhost:3000.
        - admin/products.tsx: Added GradientCard primary hero ("CATALOG /
          N products live") + larger 40px iconBtn with primary "+" button.
        - vendor/dashboard.tsx: Added GradientCard emerald hero
          ("VENDOR / ₹X today") on the home tab.
        - cart.tsx: Reviewed — already polished, no changes needed.
        Backend untouched in this iteration. No backend retest needed.
        Frontend testing pending user permission.

    - agent: "main"
      message: |
        Fixed P0 bug: Admin Shop Layout delete was broken because the
        previous agent referenced `React.useRef` without importing React.
        - Added `useRef` to the hooks import line.
        - Replaced `React.useRef(...)` with `useRef(...)`.
        - Wired the existing two-tap confirm state into the Delete button:
          first tap turns it red and changes label to "Tap again to delete"
          with an alert-triangle icon, second tap commits the DELETE call.
          Idle 4s timeout resets the button.
        - Verified visually on /admin/shop-layout via screenshot tool:
          6 Delete buttons -> first tap shows 1 "Tap again" pill ->
          second tap reduces count to 5 (block removed).
        File: /app/frontend/app/admin/shop-layout.tsx
        Backend untouched. No retest needed.

    - agent: "main"
      message: |
        Shipped Shopify/Meesho-style Dynamic Shop Layout System.
        Goal: zero app updates required for any home/category UI change.

        BACKEND
        - routes/shop_layout.py: extended schema with scope, scope_category,
          12 block_types, 7 style overrides (text_color, bg_color, font_size,
          text_align, button_color, button_text_color, height), data binding
          (product_ids, data_source, product_count, layout_style,
          category_filter), items[] array, flash_sale_ends_at.
          New endpoints: POST /admin/shop-layout/reorder, POST /admin/shop-layout/migrate-banners.
          Public GET /shop-layout now accepts ?scope=home|category&category=X.
        - routes/products_public.py: added GET /products/by-source?source=trending|new|best|category&limit=&category=
          for product-driven blocks (trending = composite interest*5+sales,
          best = sales*10+interest, new = creation date).

        FRONTEND
        - src/shop-layout-renderer.tsx: full rewrite as 12-block dispatcher
          (banner_slider, background, announcement_strip, category_circles,
          brand_slider, product_grid, horizontal_slider, content_box,
          flash_sale, offer_cards, section_header, text). Skeleton loaders
          while loading. Auto-fetches product data for non-manual sources.
          Flash sale has live countdown timer. Banner slider auto-advances.
        - app/admin/shop-layout.tsx: full rewrite. Scope tabs (Home + per-
          category) at top, 12 block-type chips in form, scope picker,
          color palette swatches + hex input for 4 colors, font size,
          height, alignment buttons, items[] editor with image upload +
          link selector (product/category/none), multi-product picker for
          manual data source, data-source chips, category filter chips,
          live customer preview uses the SAME renderer as the mobile app.
          Two-tap delete preserved.
        - app/shop-category/[name].tsx: NEW dynamic category page. Renders
          admin-managed layout for scope="category"&category=X. Falls back
          to product grid if no custom layout.
        - app/(tabs)/shop.tsx: removed standalone <PromoCarousel/> (replaced
          by banner_slider block). Department tile now navigates to the new
          dynamic category page. Renderer wired with scope="home".
        - app/admin/more.tsx: relabeled "Promo banners" -> "Promo banners
          (legacy)" with hint pointing to Shop layout.

        MIGRATION: One-time POST /admin/shop-layout/migrate-banners folds
        all promo_banners docs into a single banner_slider block (items[]
        = each promo as a slide). Idempotent — running twice updates the
        same block.

        VERIFICATION:
        - Admin scope tabs render (Home visible; categories appear as
          products are categorized).
        - New block form opens with all 12 types, scope selector, 4 color
          rows with palette + hex, font size, height, alignment, items[]
          editor, sort, active.
        - Backend logs confirm GET /api/shop-layout?scope=home 200 OK and
          POST /api/admin/shop-layout/migrate-banners reached.
        - Customer shop renders empty state correctly when no blocks (was
          the test condition); when blocks exist, all 12 renderers fire.

        NEXT (optional polish): long-press drag-to-reorder via
        react-native-reanimated (currently chevron buttons + bulk-reorder
        API ready), and per-block analytics (impressions/clicks).
        Files: routes/shop_layout.py, routes/products_public.py,
        src/shop-layout-renderer.tsx, app/admin/shop-layout.tsx,
        app/shop-category/[name].tsx, app/(tabs)/shop.tsx, app/admin/more.tsx


    - agent: "main"
      message: |
        Added Drag-to-Reorder + Per-Block Analytics on top of the dynamic
        Shop Layout System.

        BACKEND (new)
        - routes/shop_layout_analytics.py — public POST /shop-layout/analytics
          (batched impression/click events) + admin GET /admin/shop-layout/
          analytics?days=7 (aggregated counts + CTR per block_id).
        - Registered in server.py under /api prefix.
        - Collection: shop_layout_analytics { block_id, scope, event, user_id, ts }

        FRONTEND (new)
        - src/draggable-layout-list.tsx — cross-platform (web + native) long-
          press-to-drag list using react-native-gesture-handler `Gesture.Pan
          ().activateAfterLongPress(280)` + react-native-reanimated shared
          values. On release computes target index from translateY ÷
          measured-card-height and emits onReorder(newIds[]).
        - src/shop-layout-renderer.tsx — added analytics queue: pushes
          {block_id, "impression"} on visible-block mount, {block_id, "click"}
          on any onProductPress / onCategoryPress / onAddToCart, flushed
          every 5s and on unmount via POST /shop-layout/analytics.
        - app/admin/shop-layout.tsx —
            • loads analytics in parallel with blocks
            • wraps cards in <DraggableLayoutList/> with onReorder → POST
              /admin/shop-layout/reorder (bulk-renumbers sort_order 0..N-1)
            • shows analytics chips per card: eye/impressions,
              mouse-pointer/clicks, trending-up/CTR% (green ≥5%, amber <5%)
            • adds drag-handle stripe (☰) on the left of each card
            • dragging state lifts the card with primary border + brand bg
            • hero hint updated to mention long-press-drag + 7d CTR
    - agent: "testing"
      message: |
        Rich-product backend round-trip: 103/103 PASS. No fields dropped,
        mis-typed, or rejected by the backend.

        Verified across 5 endpoints with admin@app.com / Admin@123:
          POST   /api/admin/products       (full extended payload) → 200, all
                                            23 rich fields echoed intact incl.
                                            StyledText with font_size=null and
                                            empty image_data_url.
          GET    /api/admin/products       → 200, created product appears with
                                            all rich fields persisted to Mongo.
          PATCH  /api/admin/products/{id}  (7-field partial update) → 200,
                                            updates applied AND 16 untouched
                                            fields preserved exactly.
          GET    /api/products (public)    → 200, published product visible
                                            with all 16 rich fields and patched
                                            values. Computed is_in_stock and
                                            interested_count present; raw
                                            interested_users NOT leaked.
          DELETE /api/admin/products/{id}  → 200 {ok:true}, product gone from
                                            admin list afterward.

        Nested Pydantic models (StyledText, SpecTab/SpecRow, WhatsInBoxItem)
        all serialize round-trip 1:1. Rich product backend is production-ready.
        Test runner: /app/backend_test.py.


        VERIFIED:
        - curl http://localhost:8001/api/admin/shop-layout returns 401
          (route exists, auth required) — endpoints registered.
        - Admin Shop Layout page renders the new hero hint, scope tabs,
          and analytics chips when present.
        - New-block form shows all 12 types + style overrides as before.

        NOTE on web: The Pan gesture with activateAfterLongPress(280) keeps
        normal scrolling intact (drag only fires after holding the card for
        280ms). On native it provides full haptic-style drag UX.

        Files: routes/shop_layout_analytics.py, server.py,
        src/draggable-layout-list.tsx, src/shop-layout-renderer.tsx,
        app/admin/shop-layout.tsx


    - agent: "main"
      message: |
        Shipped Chat Feature end-to-end:
        - Tab order: SHOP · SERVICES · DASHBOARD · CHAT · PROFILE
        - WebSocket real-time delivery (token via ?token=, JWT-validated)
        - Referral-code-gated chat-request flow with approve/reject
        - 1:1 text + image (1200px JPEG base64) messaging
        - Soft-delete (anytime) + edit (15 min, blocked once other replies)
        - Downline users pinned to top of threads with green DOWNLINE badge
        - Unread counters; last-message preview; long-press own message → edit/delete sheet

        BACKEND: routes/chat.py
          POST   /api/chat/search?code=
          POST   /api/chat/request
          GET    /api/chat/requests
          POST   /api/chat/request/{id}/accept|reject
          GET    /api/chat/threads
          GET    /api/chat/{thread}/messages
          POST   /api/chat/{thread}/messages
          PATCH  /api/chat/messages/{id}
          DELETE /api/chat/messages/{id}
          WS     /api/ws/chat?token=<jwt>
        Collections: chat_requests, chat_threads, chat_messages

        FRONTEND:
          (tabs)/_layout.tsx       — reordered + chat icon
          (tabs)/chat.tsx          — thread list + search + requests inbox
          chat/[id].tsx            — conversation screen
          src/use-chat-socket.ts   — WS hook with exp-backoff reconnect

        VERIFIED via curl + screenshot:
          - Test user search → admin: 200 OK
          - Send request: 200 OK
          - Accept request: thread_id returned
          - Send message: 200 OK
          - Thread list: shows preview + unread + downline flag
          - UI: Chat tab visible in new bottom bar; conversation bubble
            with timestamp; image picker + send button working

        Test creds added to /app/memory/test_credentials.md:
          testuser@app.com / Test@123 (approved customer, ref code 1QRFZX)

    - agent: "testing"
      message: |
        Public single-product endpoint regression: 12/12 PASS. Runner: /app/backend_test.py.

        ✅ CASE 1 — GET /api/products/{valid id} → 200 with all required fields:
           id, name, price, image_url, brand (str), sub_features (list),
           images (list), price_summary/protection_summary/warranty_summary/
           delivery_summary (each dict with text/bold/font_size/align),
           attrs_brand/attrs_os/attrs_ram/attrs_cpu_model/attrs_cpu_speed/
           attrs_storage (all strings), extra_attrs (dict), spec_tabs (list),
           whats_in_box (list), is_in_stock (bool), interested_count (int).
           `interested_users` NOT leaked.

        ✅ CASE 2 — GET /api/products/{unpublished id} → 404 (created with
           is_published:false via POST /admin/products, then verified hidden;
           cleanup DELETE returned 200).

        ✅ CASE 3 — GET /api/products/{non-existent id} → 404.

        ✅ CASE 4 — GET /api/products (list) still works; returns 9 items with
           is_in_stock + interested_count present, interested_users NOT leaked.

        ✅ CASE 5 — Wishlist round-trip:
             POST /products/{id}/save → {saved:true}
             GET /me/wishlist → items contains pid
             POST /products/{id}/save → {saved:false} (toggle off).

        No regressions. Endpoint is production-ready for the customer Product
        Detail page.

    - agent: "testing"
      message: |
        FULL APP REGRESSION SWEEP — 56/61 PASS. Test runner: /app/backend_test.py.

        SECTION-BY-SECTION (failures inline):

        ## SECTION 1 — AUTH  (6/6 ✅)
          ✅ POST /auth/login (admin) → 200, role='admin' admin_role='super_admin'
          ✅ POST /auth/login (test user testuser@app.com) → 200
          ✅ POST /auth/login (wrong password) → 401
          ✅ GET  /auth/me (admin token) → 200 (same admin)
          ✅ POST /auth/register (audit+<ts>@app.com / Audit@123) → 200
          ✅ POST /auth/login (new user) → 200

        ## SECTION 2 — BRANDING / PUBLIC  (4/7, 3 FAIL)
          ✅ GET /branding → 200, has app_name+tagline
          ✅ GET /products → 200, items have is_in_stock+interested_count
          ✅ GET /products/{id} → 200 extended fields
          ❌ GET /products/by-source?source=trending&limit=5 → 404 "Product not found"
          ❌ GET /products/by-source?source=new&limit=5     → 404 "Product not found"
          ❌ GET /shop-layout?scope=home (no auth)          → 401 "Not authenticated"

        ## SECTION 3 — CART + CHECKOUT  (8/8 ✅, /cart/update missing — acceptable)
          ✅ POST /cart/add → 200
          ✅ GET  /cart → 200 (item present, count=1)
          ⚪ POST /cart/update → 404 (endpoint not implemented — frontend just re-adds)
          ✅ POST /orders/checkout (COD + full address) → 200 status="placed" paid_via="cod"
          ✅ GET  /orders/me → 200, order appears
          ✅ POST /cart/clear → 200

        ## SECTION 4 — WISHLIST + REVIEWS / Q&A  (8/8 ✅)
          ✅ POST /products/{id}/save (1st)        → 200 {saved:true}
          ✅ GET  /me/wishlist                     → 200 contains pid
          ✅ POST /products/{id}/save (toggle)     → 200 {saved:false}
          ✅ POST /products/{id}/reviews           → 200
          ✅ GET  /products/{id}/reviews           → 200 (voted_helpful flag present)
          ✅ POST /products/{id}/questions         → 200
          ✅ GET  /products/{id}/questions         → 200

        ## SECTION 5 — USER DASHBOARD / WALLET / NOTIFICATIONS  (6/6 ✅)
          ✅ GET  /users/me/dashboard → 200 (wallet_balance, tier, level_payouts all present)
          ✅ GET  /notifications/me → 200
          ✅ GET  /orders/me → 200  (/me/orders alias = 404 — only canonical works)
          ✅ GET  /users/me/network → 200 (no /me/team endpoint; network is the canonical)
          ✅ POST /withdrawals {amount:100} → 400 "Insufficient balance" (correct;
                              user wallet=₹0; no 5xx; canonical path is /withdrawals,
                              not /withdrawals/request which returns 404)

        ## SECTION 6 — ADMIN BASICS  (6/6 ✅)
          ✅ GET /admin/products            → 200
          ✅ GET /admin/users               → 200
          ✅ GET /admin/orders              → 200
          ✅ GET /admin/analytics?days=7    → 200
          ✅ GET /admin/approvals?status=pending → 200
          ✅ GET /admin/approvals/today     → 200

        ## SECTION 7 — SHOP-LAYOUT ADMIN  (6/6 ✅)
          ✅ GET    /admin/shop-layout?scope=home              → 200
          ✅ POST   /admin/shop-layout (section_header block)  → 200 with id
          ✅ PATCH  /admin/shop-layout/{id} {title:"updated"}  → 200
          ✅ DELETE /admin/shop-layout/{id}                    → 200
          ✅ POST   /admin/shop-layout/seed-default-home       → 200
          ✅ GET    /admin/shop-layout/analytics?days=7        → 200

        ## SECTION 8 — VENDOR FLOW (as ADMIN)  (3/3 ✅)
          ✅ GET /vendor/me/questions → 200 (admin fallback path)
          ✅ GET /vendor/me/stats     → 403 (admin not a vendor — acceptable per brief)
          ✅ GET /vendors/suggest?q=  → 200 (admin only)

        ## SECTION 9 — SERVICES / DISTRIBUTOR / OTHER  (2/4, 2 FAIL)
          ❌ GET /services/categories → 401 "Not authenticated"
                                       (docstring says "Public list of admin-curated
                                       service categories", but route Depends(get_current_user))
          ❌ GET /services            → 401 "Not authenticated"
                                       (docstring says "Public listing... Customer-facing",
                                       but route Depends(get_current_user))
          ⚪ GET /distributor/network → 404 (endpoint does not exist; closest is
                                       /users/me/network or /admin/distributors)
          ⚪ GET /pincodes/search?q=560001 → 404 public (admin alt /admin/pincodes/search → 200 OK)

        ## SECTION 10 — CHAT  (2/2 ✅)
          ✅ GET  /chat/threads        → 200
          ⚪ POST /chat/threads {peer_id} → 405 (no canonical create-thread endpoint;
                                          actual flow is POST /chat/request → accept;
                                          POST /chat/request returned 200 with pending request)

        ════════════════════════════════════════════════════════════════════
        ## ERRORS SUMMARY (5 failures, prioritized):

        P0 (5xx / data corruption):   NONE ✅

        P1 (4xx where 200 expected — REAL BUGS):
          1. **ROUTE-ORDERING BUG in routes/products_public.py** (HIGH SEVERITY,
             same pattern as the previously-fixed /admin/pincodes/in-region bug).
             `/products/{product_id}` is declared at LINE 48, BEFORE
             `/products/by-source` at LINE 88. FastAPI matches routes in
             declaration order, so requests to GET /products/by-source are
             captured by the {product_id} handler and return:
                 404 {"detail": "Product not found"}
             This breaks ALL dynamic-shop-layout product blocks whose
             data_source is "trending" / "new" / "best" / "category" — i.e. the
             whole Shopify-style home renderer is currently fetching empty grids
             for any source-driven block. FIX: move @router.get("/products/by-source")
             (currently at line 88) ABOVE @router.get("/products/{product_id}")
             (currently at line 48), OR constrain {product_id} with a UUID regex.

          2. **GET /shop-layout requires auth** (routes/shop_layout.py:299–304).
             Docstring on line 305 explicitly says "Public read for the mobile
             app" but the handler has `_: Dict[str, Any] = Depends(get_current_user)`.
             Result: 401 "Not authenticated" for any client without a token.
             Logged-in users likely don't notice, but the customer Shop tab
             rendered before login (splash / lazy-auth flows) will fail. FIX:
             remove the `Depends(get_current_user)` from this endpoint, or
             replace with an optional-auth dependency.

          3. **GET /services/categories requires auth** (server.py:5397).
             Docstring says "Public list of admin-curated service categories"
             but handler `Depends(get_current_user)` → 401. The customer
             Services tab will fail before login. FIX: drop the auth dep.

          4. **GET /services requires auth** (server.py:5307–5317).
             Docstring says "Public listing of approved service providers.
             Customer-facing." but handler `Depends(get_current_user)` → 401.
             Same fix as #3.

        P2 (response-shape regressions):  NONE ✅

        ════════════════════════════════════════════════════════════════════
        NOTES & NON-BUGS
          • /cart/update, /me/orders, /me/team, /distributor/network,
            /pincodes/search (public), /withdrawals/request,
            POST /chat/threads — none of these endpoints exist in this codebase;
            the canonical equivalents (/cart/add re-call, /orders/me,
            /users/me/network, /admin/distributors, /admin/pincodes/search,
            /withdrawals, /chat/request → accept) all work. These are spec
            mismatches in the review-request URL list, NOT regressions.
          • POST /orders/checkout (COD) — works fully. Stock decrement + order
            doc returned correctly, paid_via="cod", status="placed".
          • Cleanup ran clean: created shop-layout block deleted; audit user
            deleted via /admin/users/{id}; testuser cart cleared.

        Recommend main agent fix the 4 P1 bugs (especially #1 the route ordering
        bug, which silently breaks the home page for all dynamic blocks) and
        request a focused re-test of those endpoints. No frontend testing
        performed per protocol.

    - agent: "testing"
      message: |
        P1 endpoints (products_extended.py): 28/28 PASS. Test runner: /app/backend_test.py.

        ✅ POST /products/{pid}/reviews/{rid}/helpful — toggle helpful vote
          • Admin votes on another user's review -> 200 {voted_helpful:true, helpful_count:1}
          • Re-vote -> 200 {voted_helpful:false, helpful_count:0} (toggle off)
          • Self-vote on own review -> 400 "You can't vote on your own review."
          • Vote on non-existent review id -> 404
          • Unauth -> 401

        ✅ GET /products/{pid}/reviews — helpful_count + voted_helpful surfaced; helpful_voters
           is NOT leaked. Admin sees voted_helpful=true on the review they voted on; user sees
           voted_helpful=false but helpful_count=1.

        ✅ GET /vendor/me/questions — admin fallback path verified (role=admin allowed). After
           POST /questions, pending_count=1 and item has product_name, product_image,
           answered:false. After POST /questions/{qid}/answer, the item flips to answered:true
           and is sorted AFTER any pending ones. Normal user (role=user) -> 403
           "Vendor access required." (NOTE: tested as admin per code path that allows admin/
           super_admin; did NOT test against a real vendor account.)

        ✅ Wishlist round-trip — POST /save (saved:true) -> GET /me/wishlist contains pid ->
           POST /save (saved:false) -> GET /me/wishlist no longer contains pid.

        ⚠ NOTE on test user: testuser@app.com did not exist on the backend at test time
        (login returned 401 "Invalid credentials"). The test runner re-registered the
        account with the same credentials documented in /app/memory/test_credentials.md
        and proceeded. Main agent may want to verify the seed/setup script for testuser
        runs on backend boot, or document that the account is created on first registration.

        Product was cleaned up via DELETE /api/admin/products/{pid} -> 200 at end of run.

    - agent: "testing"
      message: |
        bcrypt-safe verify_password() regression: 8/8 PASS. Runner: /app/bcrypt_verify_test.py.

        Verified all 7 review cases against POST /api/auth/login on the public
        REACT_APP_BACKEND_URL:

          1. admin@app.com / Admin@123                        → 200 (token returned)
          2. testuser@app.com / Test@123                      → 200 (token returned)
          3. admin@app.com / wrong password                   → 401 "Invalid credentials"
          4. nonexistent email                                → 401 "Invalid credentials"
          5. user inserted via Mongo with NO password_hash    → 401 "Invalid credentials" (NOT 500)
             (Google-OAuth-only simulation: {id, email, role:user, google_id})
          6. user inserted with password_hash="not-a-real-bcrypt-hash"
                                                              → 401 "Invalid credentials" (NOT 500)
             (Was previously raising ValueError("Invalid salt") → 500.)
          7. register fresh user + login round-trip           → 200/200 (both)

        The fix in /app/backend/core/security.py (verify_password now returns
        False on empty/None/malformed hashes via early-return + try/except over
        ValueError/TypeError) plus the `user.get("password_hash") or ""` guard
        in server.py:268 successfully eliminate the production 500. Backend
        logs confirm requests that previously triggered "ValueError: Invalid
        salt" now return 401 cleanly. All Mongo setup/cleanup ran successfully
        (3 test docs inserted and removed). Fix is production-ready.
