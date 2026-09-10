/**
 * Scoped admin sub-roles (Sep 2026).
 *
 * A promoted Products / Shop Layout / Order / Vendor & Service manager is NOT
 * a super admin: their tab bar is just their own section + profile and the
 * backend blocks every other admin path (core/security.ADMIN_AREAS). Both the
 * admin tab layout and the post-login redirects read this list, so the two can
 * never drift.
 */
export const SCOPED_ADMIN_ROLES = [
  "products_manager",
  "layout_manager",
  "order_manager",
  "vendor_service_manager",
];

export function isScopedAdmin(user: any): boolean {
  return SCOPED_ADMIN_ROLES.includes(String(user?.admin_role || ""));
}

/** Where an admin should land after login. */
export function adminLanding(user: any): any {
  return isScopedAdmin(user) ? "/admin/manager-home" : "/admin/shop";
}
