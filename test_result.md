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
  current_focus: []
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
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


