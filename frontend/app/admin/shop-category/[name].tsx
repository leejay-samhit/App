// Admin mirror of /(tabs)/shop-category/[name]
//
// When an admin browses the shop (via admin/shop.tsx) and taps a category
// pill / banner, ShopHome now routes to /admin/shop-category/<name> (instead
// of /shop-category/<name>) so the user stays inside the admin Tabs
// navigator and keeps the admin bottom-bar (Home · Users · Shop · Payouts ·
// Wallet · More).  This file is just a re-export of the customer screen so
// behaviour stays identical — only the surrounding layout differs.
//
// Registered as `href: null` in admin/_layout.tsx (hidden from the tab strip
// but reachable via router.push).
export { default } from "../../(tabs)/shop-category/[name]";
