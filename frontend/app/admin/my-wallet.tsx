// Admin's PERSONAL wallet (not treasury).
//
// The admin's bottom-bar "Wallet" tab intentionally points to the system
// Treasury view (one consolidated balance across the platform).  This
// re-exported screen is for the admin's OWN earnings — admin user is also
// a regular sponsor (admin#0001) and accrues L1–L10 commissions like any
// user.  From this screen they can request a personal withdrawal via the
// same POST /api/withdrawals endpoint users use; the request lands in the
// admin's approval queue (or auto-approves depending on policy).
//
// Reached via Admin → More → "My wallet (personal)".
export { default } from "../(tabs)/wallet";
