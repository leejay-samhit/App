/**
 * JS surface of the local `sim-binding` Android module.
 *
 * The native module only exists in a real Android build. On web, on iOS and
 * inside Expo Go it is simply absent — every call then resolves to
 * DEVICE_UNSUPPORTED instead of throwing, so no screen can crash and nothing
 * is ever reported as verified by accident.
 */
import { requireOptionalNativeModule, EventSubscription } from "expo-modules-core";
import { Platform } from "react-native";

export type SimState =
  | "SIM_PRESENT"
  | "SIM_ABSENT"
  | "SIM_STATE_UNKNOWN"
  | "PERMISSION_DENIED"
  | "DEVICE_UNSUPPORTED"
  | "REVALIDATION_REQUIRED";

export type SimReading = {
  state: SimState;
  permissionGranted: boolean;
  slotCount: number;
  hasEsim: boolean;
  isRoaming: boolean;
  mcc: string;
  mnc: string;
  apiLevel: number;
  detail: string;
};

type NativeSimBinding = {
  isSupported: () => boolean;
  hasPermission: () => boolean;
  getSimStatus: () => Promise<SimReading>;
  addListener: (event: "onSubscriptionsChanged", cb: (r: SimReading) => void) => EventSubscription;
};

const native = requireOptionalNativeModule<NativeSimBinding>("SimBinding");

export const isNativeAvailable = (): boolean => Platform.OS === "android" && !!native;

const UNSUPPORTED: SimReading = {
  state: "DEVICE_UNSUPPORTED",
  permissionGranted: false,
  slotCount: 0,
  hasEsim: false,
  isRoaming: false,
  mcc: "",
  mnc: "",
  apiLevel: 0,
  detail: Platform.OS === "android" ? "native_module_missing" : `platform_${Platform.OS}`,
};

export async function readSim(): Promise<SimReading> {
  if (!isNativeAvailable()) return UNSUPPORTED;
  try {
    return await native!.getSimStatus();
  } catch (e: any) {
    return { ...UNSUPPORTED, state: "SIM_STATE_UNKNOWN", detail: String(e?.message || e).slice(0, 80) };
  }
}

export function hasSimPermission(): boolean {
  if (!isNativeAvailable()) return false;
  try {
    return native!.hasPermission();
  } catch {
    return false;
  }
}

export function onSimChanged(cb: (r: SimReading) => void): { remove: () => void } {
  if (!isNativeAvailable()) return { remove: () => {} };
  try {
    const sub = native!.addListener("onSubscriptionsChanged", cb);
    return { remove: () => sub.remove() };
  } catch {
    return { remove: () => {} };
  }
}
