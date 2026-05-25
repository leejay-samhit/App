// Admin mirror of /(tabs)/chat
//
// Re-exports the same chat list screen so admins can manage conversations
// (including team chats and incoming requests) WITHOUT leaving the admin
// Tabs navigator — the admin bottom bar (Home · Users · Shop · Payouts ·
// Wallet · More) stays visible.
//
// Registered as `href: null` in admin/_layout.tsx (reachable via router.push
// but hidden from the visible tab strip).
export { default } from "../(tabs)/chat";
