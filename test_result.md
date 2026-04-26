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
  - task: "Emergent Google Auth: POST /api/auth/google/exchange + GET /api/auth/google/callback"
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
    - "Emergent Google Auth: POST /api/auth/google/exchange + GET /api/auth/google/callback"
    - "Existing JWT Auth + Admin + E-commerce regression suite"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
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