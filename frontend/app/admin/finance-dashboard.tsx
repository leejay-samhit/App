/**
 * DEPRECATED — Finance Dashboard was merged into /admin/system-wallet on
 * 2026-05-30 so the admin has ONE unified Treasury page (every rupee in
 * one place, no duplication). This file now just forwards old links /
 * bookmarks to the canonical screen.
 *
 * DO NOT add new content here — extend /admin/system-wallet.tsx instead.
 */
import { Redirect } from "expo-router";

export default function FinanceDashboardRedirect() {
  return <Redirect href="/admin/system-wallet" />;
}
