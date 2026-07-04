/**
 * Barcode scanner modal — used by the Add-Product form to capture
 * Serial numbers and IMEIs from the phone-box barcode without typing.
 *
 * Design decisions (August 2026):
 *   • Uses `expo-camera` (SDK 51+) which subsumes the deprecated
 *     `expo-barcode-scanner` package.
 *   • Requests camera permission ONLY when the user taps the "Scan"
 *     button — matches our contextual-permission contract.
 *   • Supports the barcode formats commonly used on phone boxes:
 *       - CODE-128 & CODE-39 for IMEIs (both are printed on Apple, Samsung,
 *         and most Android boxes).
 *       - EAN-13 / UPC-A for retail SKU stickers.
 *       - QR / DataMatrix for the "IMEI QR" many brands now include.
 *   • On web, `expo-camera` is not supported for barcode scanning — we
 *     render a friendly fallback explaining that the vendor should scan
 *     from the mobile app.
 *   • For IMEI targets we DO NOT validate Luhn here — the parent form
 *     already does that and shows the red/green hint. This keeps the
 *     scanner dumb / composable.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, Modal, TouchableOpacity, StyleSheet, ActivityIndicator, Platform, Linking } from "react-native";
import { Feather } from "@expo/vector-icons";
import { CameraView, useCameraPermissions } from "expo-camera";
import { colors, spacing } from "./theme";

export type ScannerTarget = "serial" | "imei_1" | "imei_2";

const TARGET_LABEL: Record<ScannerTarget, string> = {
  serial: "Serial number",
  imei_1: "IMEI-1",
  imei_2: "IMEI-2",
};

/**
 * Barcode scanner modal. Renders a live camera preview with a reticle;
 * fires `onScanned(value)` once with the raw barcode text and then closes.
 */
export function BarcodeScannerModal({
  visible,
  target,
  onClose,
  onScanned,
}: {
  visible: boolean;
  target: ScannerTarget;
  onClose: () => void;
  onScanned: (value: string) => void;
}) {
  const [permission, requestPermission] = useCameraPermissions();
  const [scanning, setScanning] = useState<boolean>(false);
  const [lastCode, setLastCode] = useState<string>("");
  const scannedRef = useRef(false);

  // Reset the "already scanned" guard whenever the modal opens.
  useEffect(() => {
    if (visible) {
      scannedRef.current = false;
      setLastCode("");
      setScanning(true);
    } else {
      setScanning(false);
    }
  }, [visible]);

  const handleBarcode = useCallback(
    (result: { type?: string; data?: string }) => {
      if (scannedRef.current) return;
      const value = (result?.data || "").trim();
      if (!value) return;
      // For IMEI targets, prefer strings that contain 15 consecutive digits.
      // Otherwise accept whatever the barcode carries verbatim.
      let normalised = value;
      if (target !== "serial") {
        const m = value.match(/\d{15}/);
        if (m) normalised = m[0];
        else {
          // Not a valid-looking IMEI — surface the raw value but don't lock the scanner
          setLastCode(value);
          return;
        }
      }
      scannedRef.current = true;
      onScanned(normalised);
    },
    [target, onScanned],
  );

  const onRequest = async () => {
    const res = await requestPermission();
    if (!res.granted && !res.canAskAgain) {
      // Deep-link to app settings so user can flip the toggle.
      Linking.openSettings();
    }
  };

  // ── UI states ─────────────────────────────────────────────
  const webNotSupported = Platform.OS === "web";
  const permStatus = permission?.status;

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} transparent={false}>
      <View style={styles.wrap}>
        {/* Header */}
        <View style={styles.header}>
          <TouchableOpacity onPress={onClose} style={styles.closeBtn} testID="scanner-close">
            <Feather name="x" size={22} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.title}>Scan {TARGET_LABEL[target]}</Text>
          <View style={{ width: 40 }} />
        </View>

        {webNotSupported ? (
          <View style={styles.msgBox}>
            <Feather name="smartphone" size={44} color="#fff" style={{ marginBottom: 12 }} />
            <Text style={styles.msgTitle}>Scanner only works on mobile</Text>
            <Text style={styles.msgSub}>
              Barcode scanning uses the device camera. Open Slangcart on your phone (Expo Go or the installed app) to scan {TARGET_LABEL[target].toLowerCase()}.
            </Text>
            <TouchableOpacity onPress={onClose} style={styles.primaryBtn}>
              <Text style={styles.primaryBtnText}>OK, got it</Text>
            </TouchableOpacity>
          </View>
        ) : !permission ? (
          <View style={styles.msgBox}>
            <ActivityIndicator size="large" color="#fff" />
            <Text style={styles.msgSub}>Loading camera…</Text>
          </View>
        ) : permStatus !== "granted" ? (
          <View style={styles.msgBox}>
            <Feather name="camera-off" size={44} color="#fff" style={{ marginBottom: 12 }} />
            <Text style={styles.msgTitle}>Camera access needed</Text>
            <Text style={styles.msgSub}>
              Slangcart needs your camera to read the {TARGET_LABEL[target].toLowerCase()} barcode from the phone box. We only use it during this scan.
            </Text>
            <TouchableOpacity onPress={onRequest} style={styles.primaryBtn} testID="scanner-permission">
              <Text style={styles.primaryBtnText}>
                {permission.canAskAgain ? "Allow camera" : "Open Settings"}
              </Text>
            </TouchableOpacity>
          </View>
        ) : (
          <View style={{ flex: 1 }}>
            <CameraView
              style={StyleSheet.absoluteFill}
              facing="back"
              barcodeScannerSettings={{
                barcodeTypes: ["ean13", "ean8", "upc_a", "upc_e", "code128", "code39", "code93", "codabar", "itf14", "qr", "datamatrix", "pdf417"],
              }}
              onBarcodeScanned={scanning ? handleBarcode : undefined}
            />
            {/* Reticle overlay */}
            <View pointerEvents="none" style={styles.reticleWrap}>
              <View style={styles.reticle}>
                <View style={[styles.corner, styles.tl]} />
                <View style={[styles.corner, styles.tr]} />
                <View style={[styles.corner, styles.bl]} />
                <View style={[styles.corner, styles.br]} />
              </View>
              <Text style={styles.tip}>
                Hold the barcode inside the box.  {target === "serial" ? "Any barcode format accepted." : "Looking for 15-digit IMEI."}
              </Text>
              {lastCode ? (
                <View style={styles.badCodeBox}>
                  <Feather name="alert-triangle" size={12} color="#FFB4B4" />
                  <Text style={styles.badCodeText}>Not an IMEI: {lastCode.slice(0, 24)}{lastCode.length > 24 ? "…" : ""}</Text>
                </View>
              ) : null}
            </View>
          </View>
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#000" },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.screen, paddingVertical: 12,
    paddingTop: Platform.OS === "ios" ? 52 : 20,
    backgroundColor: "rgba(0,0,0,0.65)",
    zIndex: 3,
  },
  closeBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(255,255,255,0.15)" },
  title: { color: "#fff", fontSize: 16, fontWeight: "800" },
  msgBox: {
    flex: 1, alignItems: "center", justifyContent: "center",
    paddingHorizontal: 32, gap: 8,
  },
  msgTitle: { color: "#fff", fontSize: 18, fontWeight: "800", textAlign: "center" },
  msgSub: { color: "#e6e6e6", fontSize: 13, textAlign: "center", lineHeight: 20 },
  primaryBtn: {
    marginTop: 16, paddingHorizontal: 24, paddingVertical: 12,
    backgroundColor: colors.primary, borderRadius: 999,
  },
  primaryBtnText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  reticleWrap: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center", padding: 24 },
  reticle: { width: 280, height: 180, borderRadius: 8 },
  corner: { position: "absolute", width: 32, height: 32, borderColor: "#7CFF7C" },
  tl: { top: 0, left: 0, borderTopWidth: 4, borderLeftWidth: 4, borderTopLeftRadius: 8 },
  tr: { top: 0, right: 0, borderTopWidth: 4, borderRightWidth: 4, borderTopRightRadius: 8 },
  bl: { bottom: 0, left: 0, borderBottomWidth: 4, borderLeftWidth: 4, borderBottomLeftRadius: 8 },
  br: { bottom: 0, right: 0, borderBottomWidth: 4, borderRightWidth: 4, borderBottomRightRadius: 8 },
  tip: { color: "#fff", fontSize: 12, marginTop: 24, textAlign: "center", fontWeight: "700", opacity: 0.9, backgroundColor: "rgba(0,0,0,0.5)", paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8 },
  badCodeBox: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6, backgroundColor: "rgba(179,38,30,0.85)" },
  badCodeText: { color: "#fff", fontSize: 11, fontWeight: "700" },
});
