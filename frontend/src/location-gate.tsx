/**
 * LocationGate (v2 — non-blocking)
 *
 * Previous behaviour: a full-screen "Turn on location" wall that blocked
 * every non-admin route until permission was granted. User feedback:
 * "after payment success showing turn on location message please change
 * it open all the options just show up the pop up small message".
 *
 * New behaviour: NEVER blocks the UI. Just kicks off the background
 * useLocationTracking hook (silent permission-aware) and renders children
 * immediately. The small one-time banner is rendered by <LocationBanner/>
 * INSIDE the Shop home (see /src/location-banner.tsx) so it stays out of
 * the way of post-payment / login / KYC flows.
 *
 * Admin users are excluded as before.
 */
import React from "react";
import { useAuth } from "./auth";
import { useLocationTracking } from "./use-location-tracking";

export function LocationGate({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const role = (user?.role || "").toLowerCase();
  // Per spec: all users EXCEPT admin can have background tracking. We
  // still kick off the hook unconditionally for non-admins — the hook
  // itself short-circuits if permission isn't granted.
  const enabled = !!user && role !== "admin";
  useLocationTracking(enabled);
  return <>{children}</>;
}
