// Admin's "Wallet" bottom-tab now points to the SYSTEM WALLET / treasury
// view so admins see ONE consistent balance number — the overall admin
// available balance AFTER all user level payouts — instead of two
// conflicting numbers (personal wallet sum vs system wallet treasury).
//
// The treasury page (system-wallet.tsx) is the single source of truth for
// admin's bank balance tally:
//   Admin Wallet = direct_signup + fee_residual + cascade_overflow + GST
//                  + l1_funding_debit  (= net retained after user payouts)
import SystemWallet from "./system-wallet";
export default SystemWallet;
