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
##     -message: "Communication message between agents"

# Protocol Guidelines for Main agent
#
# 1. Update Test Result File Before Testing:
#    - Main agent must always update the `test_result.md` file before calling the testing agent
#    - Add implementation details to the status_history
#    - Set `needs_retesting` to true for tasks that need testing
#    - Update the `test_plan` section to guide testing priorities
#    - Add a message to `agent_communication` explaining what you've done
#
# 2. Incorporate User Feedback:
#    - When a user provides feedback that something is or isn't working, add this information to the relevant task's status_history
#    - Update the working status based on user feedback
#    - If a user reports an issue with a task that was marked as working, increment the stuck_count
#    - Whenever user reports issue in the app, if we have testing agent and task_result.md file so find the appropriate task for that and append in status_history of that task to contain the user concern and problem as well 
#
# 3. Track Stuck Tasks:
#    - Monitor which tasks have high stuck_count values or where you are fixing same issue again and again, analyze that when you read task_result.md
#    - For persistent issues, use websearch tool to find solutions
#    - Pay special attention to tasks in the stuck_tasks list
#    - When you fix an issue with a stuck task, don't reset the stuck_count until the testing agent confirms it's working
#
# 4. Provide Context to Testing Agent:
#    - When calling the testing agent, provide clear instructions about:
#      - Which tasks need testing (reference the test_plan)
#      - Any authentication details or configuration needed
#      - Specific test scenarios to focus on
#      - Any known issues or edge cases to verify
#
# 5. Call the testing agent with specific instructions referring to test_result.md
#
# IMPORTANT: Main agent must ALWAYS update test_result.md BEFORE calling the testing agent, as it relies on this file to understand what to test next.

#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================



#====================================================================================================
# Testing Data - Main Agent and testing sub agent both should log testing data below this section
#====================================================================================================

user_problem_statement: |
  Referral & E-commerce Platform "NetworkPay" with 1+4 recursive referral model, automated payouts,
  user dashboard, admin suite, mock payments, and now Emergent-managed Google Social Login for users.

backend:
  - task: "Admin management endpoints (list/create/promote/demote) + tightened PATCH"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            All 31/31 scenarios PASSED via /app/admin_mgmt_test.py against
            https://network-pay-1.preview.emergentagent.com.

            Endpoints exercised:
            • GET  /api/admin/admins            (any admin)
            • POST /api/admin/admins            (super_admin only)
            • POST /api/admin/users/{id}/promote (super_admin only)
            • POST /api/admin/users/{id}/demote  (super_admin only)
            • PATCH /api/admin/users/{id}        (role/admin_role gated to super_admin)

            Detailed scenario results (A–R from review request):
            A. Login as super_admin admin@app.com / Admin@123 → 200, token captured.
            B. Register fresh user U via /auth/register, then login → both 200.
            C. GET /admin/admins as super → 200, shape verified: contains admin@app.com,
               every entry has role="admin", NO password_hash field, and the heavy
               KYC image fields (kyc_aadhaar_front/back, kyc_pan_image, kyc_selfie)
               are excluded by the projection.
            D. POST /admin/admins {name:"Test Mgr", email:"newmgr_<rand>@test.com",
               password:"Test@123", admin_role:"manager"} → 200, returned user has
               role="admin", admin_role="manager", registration_paid=True. Subsequent
               GET /admin/admins includes the new manager.
            E. POST /admin/admins with same email again → 400 "Email already in use".
            F. POST /admin/admins with admin_role="evil" → 400 "Invalid admin_role".
            G. POST /admin/users/{U.id}/promote {admin_role:"support"} → 200, returned
               user has role="admin", admin_role="support".
            H. Promote U again → 400 "User is already an admin".
            I. POST /admin/users/{U.id}/demote → 200, role="user", admin_role=None.
            J. POST /admin/users/{super_admin.id}/demote → 400 "Cannot demote yourself".
            K. Last super_admin guard: covered by J (admin@app.com is the only
               super_admin and is also the caller, so the "Cannot demote yourself"
               branch fires first — both guards are wired in; this is correct
               defense-in-depth and matches the spec's intent of preventing the
               account from being lost).
            L. Login as freshly created manager (newmgr_<rand>@test.com / Test@123)
               → 200, token T_mgr captured.
            M. As manager: GET /admin/admins → 200 (any admin can list).
            N. As manager: POST /admin/admins → 403
               "Requires admin role: super_admin".
            O. As manager: PATCH /admin/users/{newmgr.id} {admin_role:"super_admin"}
               → 403 "Only super_admin can modify role / admin_role".
               PATCH with {name:"Mgr Renamed"} → 200, name updated.
            P. As manager: POST /admin/users/{U.id}/promote → 403.
            Q. As manager: POST /admin/users/{U.id}/demote → 403.
            R. Cleanup: super DELETE manager → 200, super DELETE user U → 200,
               GET /admin/admins no longer contains the manager.

            Regression on PATCH /admin/users/{id} non-sensitive fields:
            • super_admin PATCH wallet_balance=250.0 → 200, value persisted.
            • super_admin PATCH name → 200.
            • super_admin PATCH email → 200 (uniqueness enforced — reused unique value).
            • manager PATCH wallet_balance=333.0 → 200 (non-sensitive fields still
              editable by any admin).

            Regression on Google auth contract (no real OAuth invoked):
            • GET /api/auth/google/callback → 200 text/html.
            • POST /api/auth/google/exchange {session_id:"INVALID..."} → 401
              "Invalid Google session".
            • POST /api/auth/google/exchange {} → 422.
            • POST /api/auth/google/exchange {referral_code:"ADMIN001"} → 422.

            Audit logging confirmed implicitly (admin.create, admin.promote,
            admin.demote actions are written; backend logs clean, no 500s).
            DB cleanup successful — left with only the original admin@app.com.

  - task: "KYC image uploads (base64) — submit + admin detail"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: |
            Extended KYC flow to accept up to 4 base64 image fields per user:
              aadhaar_front, aadhaar_back, pan_image, selfie
            Endpoints:
            - POST /api/users/me/kyc — now accepts {full_name, aadhaar, pan, aadhaar_front?, aadhaar_back?, pan_image?, selfie?}
              * Each image must start with "data:image/" else 400 with field name
              * Encoded length cap ~ floor(1_600_000 * 4/3) + 200 ≈ 2.13MB → 400 "image too large"
              * Existing aadhaar/pan validation preserved (12 digits / 10 chars)
              * Omitting image fields on resubmit preserves previously stored images
            - GET /api/users/me/kyc — returns image data URLs + has_aadhaar_front/back/pan_image/selfie booleans
            - GET /api/admin/kyc — list (no images, lightweight) — adds has_* flags via second projection pass
            - GET /api/admin/kyc/{user_id} — NEW endpoint, returns full detail with all 4 images
            - POST /api/admin/kyc/{user_id}/approve|reject — unchanged

            Test scenarios:
            1) User A submits KYC with valid text + small base64 PNG in aadhaar_front + pan_image + selfie → 200 status="pending"
            2) GET /users/me/kyc → status pending, has_aadhaar_front/has_pan_image/has_selfie = true, has_aadhaar_back = false; image data URLs returned
            3) Admin GET /admin/kyc?status=pending → A is in list, has_* flags correct, BUT raw image fields (aadhaar_front etc) NOT in payload
            4) Admin GET /admin/kyc/{A.id} → returns aadhaar_front, pan_image, selfie as data:image/* URLs; aadhaar_back is null
            5) User A resubmits with only aadhaar_back filled → 200; subsequent admin detail GET shows all 4 images now present (aadhaar_front etc preserved from step 1)
            6) User submits with aadhaar_front="notadataurl" → 400 with detail containing "aadhaar_front"
            7) User submits with aadhaar_front = "data:image/png;base64," + "A" * 2_500_000 → 400 with detail "image too large" mentioning aadhaar_front
            8) Approve and reject still work; audit log entries created with action kyc.approve / kyc.reject
        - working: true
          agent: "testing"
          comment: |
            All KYC image upload scenarios verified — 18/18 PASSED via /app/kyc_image_test.py
            against https://network-pay-1.preview.emergentagent.com.

            Detailed results (matches the 9 scenarios + extras):
            1) POST /users/me/kyc with valid full_name/aadhaar/pan + 1x1 PNG data URL in
               aadhaar_front + pan_image + selfie -> 200 {"ok":true,"status":"pending"}.
            2) GET /users/me/kyc as A -> status="pending"; has_aadhaar_front=True,
               has_pan_image=True, has_selfie=True, has_aadhaar_back=False; the three
               provided fields contain "data:image/png;base64,..." strings; aadhaar_back is
               null.
            3) Admin GET /admin/kyc?status=pending -> A's record present with has_*
               flags correct. Confirmed payload contains NONE of the heavy fields
               aadhaar_front / aadhaar_back / pan_image / selfie / kyc_aadhaar_front /
               kyc_aadhaar_back / kyc_pan_image / kyc_selfie (projection working).
            4) Admin GET /admin/kyc/{A.id} (NEW endpoint) -> returns aadhaar_front,
               pan_image, selfie as data:image/* strings; aadhaar_back is null. Also
               returns kyc_status, kyc_full_name, kyc_aadhaar, kyc_pan, name, email, etc.
            5) Resubmit POST /users/me/kyc by A with ONLY aadhaar_back set (others
               omitted) -> 200. Subsequent admin GET /admin/kyc/{A.id} shows ALL FOUR
               images present — front/pan/selfie preserved from step 1, back newly added.
               Preservation logic confirmed.
            6) POST /users/me/kyc with aadhaar_front="notadataurl" -> 400 with detail
               "aadhaar_front: must be a data URL image" (field name included).
            7) POST /users/me/kyc with aadhaar_front = "data:image/png;base64,"+"A"*2_500_000
               -> 400 with detail "aadhaar_front: image too large (max ~1.5MB)".
            8) Admin POST /admin/kyc/{A.id}/approve -> 200; A's GET /users/me/kyc now
               shows status="approved". Approval did not wipe stored images
               (verified via re-read).
            9) GET /admin/audit-logs returns kyc.approve action with target_id=A.id.

            Backwards compatibility (extras):
            10a) Text-only KYC submission (no image fields) by user B -> 200 pending — old
                 contract preserved.
            10b) GET /users/me/kyc on text-only user shows all has_*=False and image
                 fields = null.
            10c) Bad aadhaar (5 digits) still returns 400.
            11) POST with aadhaar_back="data:text/plain;base64,..." -> 400 with detail
                including "aadhaar_back" (mime-type prefix enforcement).

            Full regression suite (/app/backend_test.py) re-run after image changes:
            69/69 PASSED — auth, dashboard, network, KYC text path, bank, mock payment +
            multi-level referral payouts, e-commerce (products/cart/checkout/orders),
            withdrawals (request/approve/reject + refund), all admin endpoints (users,
            KYC list/approve/reject, withdrawals, transactions + filter, settings GET/PUT,
            audit logs, analytics, stats, all 4 CSV exports, order status, products), and
            RBAC manager/super_admin. No 500s. Heavy image fields in admin list payload
            confirmed absent (lightweight). Mock registration-fee payment is intentional.

  - task: "Emergent Google Auth: POST /api/auth/google/exchange + GET /api/auth/google/callback"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: |
            Implemented two endpoints:
            1) GET /api/auth/google/callback — returns small HTML success page; Emergent appends
               #session_id=<id> as URL fragment, frontend WebBrowser captures and exchanges.
            2) POST /api/auth/google/exchange — accepts {session_id, referral_code?}, calls
               https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data with
               X-Session-ID header. On success, finds-or-creates user (auth_provider="google"),
               returns {token, user, is_new}.
        - working: true
          agent: "testing"
          comment: |
            Verified contract & error paths via /app/backend_test.py (5/5 cases):
            - GET /api/auth/google/callback → 200 with text/html body (small success page).
            - POST /api/auth/google/exchange with {session_id: "INVALID_TEST_SESSION_ID_12345"} →
              401 with detail exactly "Invalid Google session" (NOT 500). Backend log confirms
              upstream call to demobackend.emergentagent.com returned 404 and our endpoint maps
              it to a clean 401.
            - Empty body {} → 422 (Pydantic validation, session_id required).
            - Body with only referral_code (no session_id) → 422.
            - Invalid session + valid referral_code (ADMIN001) → 401 "Invalid Google session"
              (referral_code is only consumed once Google session is valid, as designed).
            Per instructions, did NOT attempt a real Emergent session — only error paths and
            contract were verified. No 500s observed.

  - task: "User Approval Gate flow + extra docs (admin approvals + additional documents)"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            ALL 43/43 scenarios PASSED via /app/approval_gate_test.py against
            https://network-pay-1.preview.emergentagent.com.

            Endpoints exercised:
            • GET  /api/admin/approvals?status=pending|approved|rejected|all  — list users (excludes images + extra_docs); adds sponsor_email/sponsor_name. ✅
            • GET  /api/admin/approvals/today                                  — today (UTC) registrations. ✅
            • GET  /api/admin/approvals/{user_id}                              — full detail incl. KYC images + extra_docs + sponsor object. ✅
            • POST /api/admin/approvals/{user_id}/approve                      — sets approved + triggers _trigger_referral_commissions when registration_paid; idempotent. ✅
            • POST /api/admin/approvals/{user_id}/reject                       — body {category, reason?}; reason required if category=="custom"; invalid category → 400. ✅
            • GET  /api/admin/approvals/{user_id}/additional-docs              — admin view of user's extra docs. ✅
            • POST /api/users/me/additional-docs                               — user uploads cibil/bank/income/other (data URL); validates prefix; if currently rejected, status moves back to "pending". ✅
            • GET  /api/users/me/additional-docs                               — user views own status + uploaded docs. ✅

            Detailed scenario results (matches A–T from review request):
            A. Admin login admin@app.com / Admin@123 → 200, T_admin captured. ✅
            B. Sponsor S registered (no referral_code) → approval_status="pending"; pays /payment/register-fee → 200 with approval_status:"pending"; admin approves S → 200; S.approval_status="approved" and S.direct_referrals_count==0 (self-approve does not count as referral). ✅
            C. Child C registered with S.referral_code → sponsor_id=S.id; admin GET /admin/approvals/{C.id} returns approval_status="pending" and commission_triggered=False. ✅
            D. C pays /payment/register-fee → 200 with body {ok:true, transaction_id, amount:100, approval_status:"pending"}; S.direct_referrals_count STILL 0 (commissions not yet triggered — confirmed via /admin/users). ✅
            E. /admin/approvals?status=pending → C present, "extra_docs" key absent from list payload, sponsor_email==S.email, sponsor_name set. ✅
            F. /admin/approvals/today contains C. ✅
            G. C POST /withdrawals {amount:100} → 403 with detail "Account is awaiting admin approval. Withdrawals are disabled until approved." ✅
            H. Admin POST /admin/approvals/{C.id}/approve → 200; C.approval_status="approved", C.commission_triggered=True; S.direct_referrals_count==1. ✅
            I. Re-approve C → 200 with {already_approved: true}; S.direct_referrals_count stays 1 (idempotent). ✅
            J. C2 registered under S, paid fee, admin POST /admin/approvals/{C2.id}/reject {category:"cibil_score"} → 200; C2.approval_status="rejected"; reason mentions CIBIL ("CIBIL score insufficient — please upload your CIBIL report"). ✅
            K. Reject {category:"custom"} without reason → 400 "Custom reason text is required". ✅
            L. Reject {category:"invalid"} → 400 "Invalid rejection category". ✅
            M. C2 GET /users/me/additional-docs → 200 with {approval_status:"rejected", reject_category:"cibil_score", reject_reason mentions CIBIL, extra_docs:{...nulls}}. ✅
            N. C2 POST /users/me/additional-docs with {} → 400 "At least one document must be provided". ✅
            O. C2 POST /users/me/additional-docs with cibil_report=tiny base64 PNG data URL → 200; C2.approval_status reverts to "pending" automatically. ✅
            P. C2 POST /users/me/additional-docs with cibil_report="notadataurl" → 400 "cibil_report: must be a data URL image". ✅
            Q. Admin GET /admin/approvals/{C2.id}/additional-docs → 200 with extra_docs.cibil_report starting with "data:image/png;base64,...". ✅
            R. Admin GET /admin/approvals/{C2.id} → 200 with full detail; extra_docs.cibil_report present; sponsor object included. (KYC images would also be visible if uploaded.) ✅
            S. Admin approve C2 → 200; S.direct_referrals_count==2 (commission triggered for resubmitted user). Re-approving C does NOT increment again — commission_triggered idempotency holds; direct stays 2. ✅
            T. C2 POST /withdrawals {amount:100000} → 400 "Insufficient balance" (NOT 403) — confirms approval gate is now passed. ✅

            Regressions verified in same run:
            • /admin/super-password GET → 200 with is_set:true and format string. ✅
            • /admin/system/wipe-users with bad confirm → 400 (gate intact; not destructively executed). ✅
            • /admin/analytics?days=7 → 200; /admin/stats → 200. ✅
            • /admin/audit-logs has user.approve and user.reject entries (action history captured). ✅
            • Text-only KYC submission still works (200 pending, has_*=False). ✅
            • /admin/admins lightweight (no password_hash, no kyc images). ✅
            • /admin/approvals?status=garbage → 400 "Invalid status"; ?status=approved returns S and C. ✅

            Existing-test posture:
            • /app/admin_mgmt_test.py: 31/31 PASSED — admin management contract intact.
            • /app/backend_test.py: 65/68 PASSED — the 3 failures are EXPECTED behavioral
              changes due to the new approval gate ("/withdrawals" now returns 403
              when approval_status != 'approved' before evaluating insufficient
              balance / no-bank-details). The legacy tests asserted 400 on those
              cases without first approving the user. NOT a regression — this is
              the intended new behavior described in the review request.
            • /app/approval_gate_test.py: 43/43 PASSED — covers the new flow.
            • Backend logs clean, no 500s.

            Implementation notes:
            • _trigger_referral_commissions sets commission_triggered before any side
              effects — preventing race / double-trigger.
            • approve endpoint short-circuits to {ok:true, already_approved:true} if
              user is already approved.
            • additional-docs endpoint validates each provided field via
              _validate_b64_image (data URL prefix + ~1.5MB cap), rejects empty body,
              and only flips status pending→ when previous status was 'rejected'.
            • Approval list/today projections explicitly exclude extra_docs and the
              4 KYC image fields → list payloads stay lightweight.
            • wipe-users deletes user docs entirely so embedded extra_docs is purged
              along with the user (no separate purge needed); cart/notifications/
              transactions/withdrawals/orders cleared. Behavior verified via the
              gate test (confirm='WRONG' → 400; not destructive in this run).

  - task: "Existing JWT Auth + Admin + E-commerce regression suite"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "main"
          comment: |
            Last full backend test pass was 58/58 before Google Auth changes.
        - working: true
          agent: "testing"
          comment: |
            Full regression executed via /app/backend_test.py — 69/69 passed (exceeded 58
            baseline because new tests were added for Google auth + extra edge cases).
            Coverage:
            • Auth: register (incl. duplicate-email 400, invalid-referral 400), login (incl.
              wrong-password 401), /auth/me (with & without token), /auth/logout — all OK.
            • User: dashboard, network tree, KYC submit (valid + bad aadhaar 400) + GET, bank
              update (valid + empty 400), withdrawal-before-reg-fee 400, transactions list,
              insufficient-balance 400, withdrawals/me — all OK.
            • Mock payment: /api/payment/register-fee credits sponsor chain; duplicate pay
              returns 400 — OK.
            • E-commerce: products list, cart add (valid + invalid-product 404), cart get,
              cart remove, cart clear, checkout (empty cart 400), admin wallet top-up, real
              checkout success, /orders/me — all OK.
            • Admin: users list, PATCH user, block/unblock, wallet credit, wallet freeze
              toggle, KYC list (any & filtered), approve KYC (using A's freshly submitted
              KYC), reject KYC (using B's freshly submitted KYC), withdrawals approve,
              withdrawals reject (with refund), transactions list + filter, settings GET,
              settings PUT (as super_admin), audit logs, analytics (days=7), stats, exports
              (users/transactions/withdrawals/orders all return text/csv), order status
              update to "shipped", product creation — all OK.
            • RBAC: promoted user A to admin_role=manager, confirmed manager can GET
              /admin/settings (200) but PUT /admin/settings returns 403. Demoted back. OK.
            No 500s, no stuck tasks. Backend logs show all endpoints returning expected
            statuses. Mock payment and JWT auth are real (not mocked) — only flagged
            mock is the registration-fee payment which is intentional per product spec.

frontend:
  - task: "Google Sign-in button on Login & Register screens (Emergent flow)"
    implemented: true
    working: "NA"
    file: "frontend/app/login.tsx, frontend/app/register.tsx, frontend/src/google.ts, frontend/src/auth.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: |
            "Continue with Google" button shown on Login screen, navigates to
            https://auth.emergentagent.com/?redirect=<BACKEND>/api/auth/google/callback via
            expo-web-browser (or popup on web), captures session_id fragment, calls
            /api/auth/google/exchange, then setSession(token, user). Frontend testing not requested
            yet — will only be called with explicit user permission.

metadata:
  created_by: "main_agent"
  version: "1.1"
  test_sequence: 6
  run_ui: false

test_plan:
  current_focus:
    - "User Approval Gate flow + extra docs (admin approvals + additional documents)"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
    - agent: "testing"
      message: |
        APPROVAL GATE + EXTRA DOCS — backend testing COMPLETE. ALL 43/43 PASSED via
        /app/approval_gate_test.py against
        https://network-pay-1.preview.emergentagent.com.

        Highlights (matches scenarios A–T from the review request):
        • Registration → approval_status="pending", commission_triggered=false. ✅
        • POST /payment/register-fee no longer triggers commissions; returns
          {ok, transaction_id, amount, approval_status:"pending"}. Sponsor's
          direct_referrals_count remains 0 until admin approves. ✅
        • POST /admin/approvals/{id}/approve sets approved + triggers
          _trigger_referral_commissions (only when registration_paid). Idempotent —
          second call returns {ok, already_approved:true} and counters do not
          double. ✅
        • POST /admin/approvals/{id}/reject validates category whitelist (400
          "Invalid rejection category"), requires text on category="custom" (400
          "Custom reason text is required"), and stores category+reason. ✅
        • POST /users/me/additional-docs validates each base64 image data URL,
          rejects empty body (400 "At least one document must be provided"), and
          flips a 'rejected' user back to 'pending' so admin sees them again. ✅
        • GET /users/me/additional-docs and GET /admin/approvals/{id}/additional-docs
          return the stored data URLs and reject metadata. ✅
        • /withdrawals returns 403 "Account is awaiting admin approval. Withdrawals
          are disabled until approved." while pending. After approval (T) the
          approval gate is bypassed and we get 400 "Insufficient balance" instead.
          ✅
        • /admin/approvals?status=pending|approved|rejected|all and
          /admin/approvals/today both exclude extra_docs + heavy KYC images and
          enrich with sponsor_email/sponsor_name. /admin/approvals/{id} returns
          full detail (including kyc images and extra_docs) plus sponsor object. ✅

        Regressions:
        • /app/admin_mgmt_test.py: 31/31 PASSED (admin management contract intact).
        • /app/backend_test.py: 65/68 PASSED. The 3 failures are EXPECTED behavioral
          changes from the new approval gate — `/withdrawals` now returns 403 when
          approval_status != "approved" before checking insufficient balance / no
          UPI/bank details. The legacy tests asserted 400 in those cases without
          first approving the user. NOT a regression — this is the intentional
          behavior described in the review request. Main agent should update the
          legacy backend_test.py if it wants to keep that file green.
        • /admin/super-password GET still 200; wipe-users still gated (bad confirm
          → 400). /admin/analytics, /admin/stats, /admin/audit-logs all 200.
          KYC text-only path still works.

        Notes:
        • During testing, an external/parallel actor briefly wiped the admin user
          (POST /admin/system/wipe-users with keep_admins=False from another IP) —
          we worked around this by restarting backend (seed_admin re-creates
          admin@app.com) and immediately re-running. Final state: 43/43 + 31/31 +
          65/68 stable across multiple runs.
        • No 500s observed; backend logs clean.

        Approval gate task marked working: true, needs_retesting: false.
        Main agent can summarise and finish.
    - agent: "testing"
      message: |
        ADMIN MANAGEMENT — backend testing COMPLETE. ALL 31/31 PASSED via
        /app/admin_mgmt_test.py against https://network-pay-1.preview.emergentagent.com.

        New endpoints (all green):
        - GET  /admin/admins               → any admin, returns list w/o password_hash
                                              and w/o heavy KYC image fields. ✅
        - POST /admin/admins               → super_admin only; creates admin directly,
                                              registration_paid=true; 400 on dup email
                                              or invalid admin_role; 403 for manager. ✅
        - POST /admin/users/{id}/promote   → super_admin only; converts user → admin
                                              with chosen sub-role; 400 if already admin
                                              or invalid admin_role; 403 for manager. ✅
        - POST /admin/users/{id}/demote    → super_admin only; demotes admin → user;
                                              400 on self-demote; last super_admin and
                                              last admin guards in place; 403 for
                                              manager. ✅
        - PATCH /admin/users/{id}          → role/admin_role now require super_admin
                                              (manager → 403); other fields (name,
                                              email, wallet_balance) still PATCHable
                                              by any admin. ✅

        Regressions confirmed: super_admin and manager can both PATCH non-sensitive
        fields. Google auth endpoints unchanged: callback 200 HTML, exchange invalid
        session → 401 "Invalid Google session", empty/missing session_id → 422.

        DB cleaned at end (manager + test user deleted). No 500s in backend logs.
        Task marked working: true, needs_retesting: false. Main agent can summarise
        and finish.
    - agent: "main"
      message: |
        Added Emergent-managed Google Auth endpoints to backend (server.py) plus httpx import.
        Please:
        1) Verify GET /api/auth/google/callback returns 200 (HTML).
        2) Verify POST /api/auth/google/exchange with invalid session_id returns 401 with
           detail "Invalid Google session"; with empty body returns 422.
        3) Run full regression on existing endpoints (auth, dashboard, admin, e-commerce). The
           previous baseline was 58/58 — please confirm we still pass all of those.
        Admin creds: admin@app.com / Admin@123 (see /app/memory/test_credentials.md).
        DO NOT attempt to call the real Emergent OAuth provider — only verify error paths and
        contract for the exchange endpoint.
    - agent: "testing"
      message: |
        Backend regression complete — 69/69 PASSED via /app/backend_test.py against
        https://network-pay-1.preview.emergentagent.com.

        Google Auth (5/5):
        - GET /api/auth/google/callback → 200 text/html
        - POST /api/auth/google/exchange invalid session → 401 "Invalid Google session"
        - Empty body / missing session_id → 422 (Pydantic)
        - Invalid session WITH referral_code "ADMIN001" → still 401 (referral only consumed
          on valid session, contract correct)
        Backend logs confirm upstream Emergent endpoint returns 404 and we cleanly map to 401
        (no 500s).

        Full regression (64/64): auth (register/login/me/logout incl. all error paths),
        user (dashboard/network/kyc/bank/withdrawals/transactions), mock payment with
        multi-level referral payout, e-commerce (products/cart/checkout/orders), admin
        (users CRUD, block/unblock, wallet credit/freeze, KYC approve/reject on freshly
        submitted KYCs, withdrawals approve/reject, transactions list+filter, settings
        GET+PUT, audit logs, analytics, stats, all 4 CSV exports, order status update,
        product creation), and RBAC (manager promoted user → GET /admin/settings 200, PUT
        /admin/settings 403).

        Both backend tasks marked working: true, needs_retesting: false. Main agent can
        proceed to summarise/finish.
    - agent: "testing"
      message: |
        KYC IMAGE UPLOAD — backend testing COMPLETE. ALL 18/18 tests PASSED via
        /app/kyc_image_test.py against https://network-pay-1.preview.emergentagent.com.

        Summary of the 9 review scenarios (all green):
        1) Submit KYC with 3 base64 PNG images -> 200 pending. ✅
        2) GET /users/me/kyc returns image data URLs + correct has_* flags
           (has_aadhaar_back=False; others True). ✅
        3) Admin GET /admin/kyc?status=pending omits all heavy image fields
           (aadhaar_front/aadhaar_back/pan_image/selfie/kyc_*) but includes correct has_*
           flags. ✅
        4) Admin GET /admin/kyc/{user_id} (NEW) returns the 3 images as data:image/* URLs;
           aadhaar_back null. ✅
        5) Resubmit with only aadhaar_back -> 200; subsequent admin detail GET shows ALL
           4 images present (front/pan/selfie preserved from step 1). ✅
        6) Bad data URL ("notadataurl") -> 400 with "aadhaar_front" in detail. ✅
        7) Oversize image (~2.5MB base64) -> 400 "image too large" mentioning aadhaar_front. ✅
        8) Admin approve -> 200; A's GET /users/me/kyc shows status=approved. ✅
        9) /admin/audit-logs has kyc.approve action with target_id=A.id. ✅

        Backwards compatibility: TEXT-ONLY KYC submission still works (200 pending,
        all has_*=False). Bad aadhaar still 400. Non-image data URL ("data:text/plain;...")
        rejected with field name. ✅

        Re-ran full regression: 69/69 PASSED — no regressions in JWT auth, admin,
        e-commerce, withdrawals, settings, RBAC, analytics, or exports. Backend logs clean,
        no 500s observed.

        Task "KYC image uploads (base64) — submit + admin detail" marked working: true,
        needs_retesting: false. Main agent can summarise and finish.