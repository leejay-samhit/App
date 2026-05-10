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
    - "Distributor Area Mapping — Bulk Unassign + Region Pincode Lookup (2 NEW endpoints)"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
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

    - agent: "main"
      message: |
        Please test ONLY the two new endpoints listed in the current_focus task
        above (POST .../areas/bulk-unassign and GET .../pincodes/in-region).
        The earlier 7 distributor endpoints already passed in an archived run
        (46/51 with 5 unrelated seed-data issues) and don't need re-testing.
        Use existing admin@app.com / Admin@123 + finance@app.com / Finance@123
        credentials. Create finance via POST /api/admin/admins if missing.
        Cleanup any test users created.
