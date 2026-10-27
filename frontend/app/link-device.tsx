// Link this browser to a verified phone (Oct 2026).
//
// A browser has no SIM, so it borrows a verified phone's status:
//   • On web/desktop this screen shows a QR + code that expires in 3 minutes.
//   • On the verified phone, the same screen opens the camera to scan it (or
//     the code can be typed in).
// The code is single-use, same-account only, and the resulting link lasts 24
// hours. Everything is decided by the server.
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  TextInput, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useRouter } from "expo-router";
import QRCode from "react-native-qrcode-svg";
import { CameraView, useCameraPermissions } from "expo-camera";
import { api, formatApiError } from "../src/api";
import { colors, spacing, radii } from "../src/theme";
import { useSimVerification } from "../src/sim-verification";
import { useAuth } from "../src/auth";

export default function LinkDeviceScreen() {
  const router = useRouter();
  const { status, refresh } = useSimVerification();
  const { user } = useAuth();
  const isWeb = Platform.OS === "web";

  // Browser side — mint a code to display.
  const [code, setCode] = useState("");
  const [expiresIn, setExpiresIn] = useState(0);
  const [minting, setMinting] = useState(false);
  const [linked, setLinked] = useState(false);
  const [error, setError] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Phone side — scan or type the code.
  const [permission, requestPermission] = useCameraPermissions();
  const [scanning, setScanning] = useState(false);
  const [typed, setTyped] = useState("");
  const [claiming, setClaiming] = useState(false);
  const [claimMsg, setClaimMsg] = useState("");

  const mint = useCallback(async () => {
    setMinting(true);
    setError("");
    try {
      const { data } = await api.post<{ code: string; ttl_seconds: number }>(
        "/sim-binding/device-link/start",
        {},
      );
      setCode(data.code);
      setExpiresIn(data.ttl_seconds);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setMinting(false);
    }
  }, []);

  // Countdown + poll THIS code for the phone's approval.
  //
  // Polling the account's status here was wrong: a user whose phone had
  // already passed looked "linked" seconds after the code appeared, without
  // any phone ever scanning it. The question is whether THIS code was
  // claimed, so that is what we ask.
  useEffect(() => {
    if (!code) return;
    const tick = setInterval(() => setExpiresIn((s) => (s > 0 ? s - 1 : 0)), 1000);
    pollRef.current = setInterval(async () => {
      try {
        const { data } = await api.get<{ claimed: boolean; expired: boolean }>(
          `/sim-binding/device-link/${code}`,
        );
        if (data.claimed) {
          setLinked(true);
          await refresh();
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch {
        /* keep polling until the countdown runs out */
      }
    }, 3000);
    return () => {
      clearInterval(tick);
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [code, refresh]);

  const claim = async (value: string) => {
    const c = value.trim();
    if (!c) return;
    setClaiming(true);
    setClaimMsg("");
    try {
      await api.post("/sim-binding/device-link/claim", { code: c });
      setClaimMsg("Linked. Your computer can chat for the next 24 hours.");
      setScanning(false);
    } catch (e) {
      setClaimMsg(formatApiError(e));
    } finally {
      setClaiming(false);
    }
  };

  const startScan = async () => {
    if (!permission?.granted) {
      const res = await requestPermission();
      if (!res.granted) {
        setClaimMsg("Camera access is needed to scan the code. You can type it instead.");
        return;
      }
    }
    setScanning(true);
  };

  if (!user?.id) {
    return (
      <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
        <Stack.Screen options={{ title: "Link device", headerShown: false }} />
        <View style={styles.header}>
          <Text style={styles.headerTitle}>Link device</Text>
        </View>
        <View style={styles.body}>
          <Text style={styles.lead}>Sign in first, then you can link this browser to your verified phone.</Text>
          <TouchableOpacity style={styles.primaryBtn} onPress={() => router.replace("/login" as any)}>
            <Text style={styles.primaryText}>Sign in</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <Stack.Screen options={{ title: "Link device", headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} hitSlop={12} testID="link-device-back">
          <Feather name="arrow-left" size={22} color={colors.primaryFg} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Link device</Text>
      </View>

      <ScrollView contentContainerStyle={styles.body}>
        {isWeb ? (
          <>
            <Text style={styles.lead}>
              Chat needs a verified phone. Show this code to your Slangcart app → Verify SIM → Link a verified phone →
              Scan.
            </Text>
            {linked ? (
              <View style={[styles.card, { borderColor: colors.success }]}>
                <Feather name="check-circle" size={28} color={colors.success} />
                <Text style={styles.cardTitle}>This browser is linked</Text>
                <Text style={styles.cardBody}>You can go back to your chats.</Text>
              </View>
            ) : code ? (
              <View style={styles.card}>
                <View style={styles.qrWrap}>
                  <QRCode value={code} size={192} backgroundColor="#FFFFFF" color="#000000" />
                </View>
                <Text style={styles.codeText} selectable>
                  {code}
                </Text>
                <Text style={styles.cardBody}>
                  {expiresIn > 0 ? `Expires in ${expiresIn}s` : "Expired — generate a new code."}
                </Text>
                <TouchableOpacity style={styles.secondaryBtn} onPress={mint} testID="link-device-new-code">
                  <Text style={styles.secondaryText}>New code</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <TouchableOpacity style={styles.primaryBtn} onPress={mint} disabled={minting} testID="link-device-show-code">
                {minting ? (
                  <ActivityIndicator color={colors.primaryFg} />
                ) : (
                  <Text style={styles.primaryText}>Show link code</Text>
                )}
              </TouchableOpacity>
            )}
            {!!error && <Text style={styles.err}>{error}</Text>}
          </>
        ) : (
          <>
            <Text style={styles.lead}>
              Scan the code shown on your computer to let it chat using this phone&apos;s verified status.
            </Text>
            {!status?.meets_requirement && (
              <View style={styles.warnBox}>
                <Text style={styles.cardBody}>
                  Verify this phone&apos;s SIM first — then you can approve your computer.
                </Text>
                <TouchableOpacity style={styles.secondaryBtn} onPress={() => router.push("/verify-sim")} testID="link-device-go-verify">
                  <Text style={styles.secondaryText}>Verify SIM</Text>
                </TouchableOpacity>
              </View>
            )}
            {scanning ? (
              <View style={styles.scanWrap}>
                <CameraView
                  style={StyleSheet.absoluteFill}
                  barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
                  onBarcodeScanned={({ data }) => {
                    if (!claiming) claim(String(data || ""));
                  }}
                />
              </View>
            ) : (
              <TouchableOpacity
                style={styles.primaryBtn}
                onPress={startScan}
                disabled={!status?.meets_requirement}
                testID="link-device-scan-button"
              >
                <Text style={styles.primaryText}>Scan the code</Text>
              </TouchableOpacity>
            )}

            <Text style={styles.orText}>or type the code shown on your computer</Text>
            <TextInput
              style={styles.input}
              value={typed}
              onChangeText={setTyped}
              placeholder="Paste link code"
              testID="link-device-code-input"
              placeholderTextColor={colors.textMuted}
              autoCapitalize="none"
              autoCorrect={false}
            />
            <TouchableOpacity
              style={styles.secondaryBtn}
              onPress={() => claim(typed)}
              testID="link-device-claim-button"
              disabled={claiming || !status?.meets_requirement}
            >
              {claiming ? (
                <ActivityIndicator color={colors.primary} />
              ) : (
                <Text style={styles.secondaryText}>Approve this code</Text>
              )}
            </TouchableOpacity>
            {!!claimMsg && <Text style={styles.msg}>{claimMsg}</Text>}
          </>
        )}

        <Text style={styles.privacy}>
          Link codes are single use, expire in 3 minutes and only work within your own account. The link itself lasts
          24 hours, after which the browser asks again.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    backgroundColor: colors.primary,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.screen,
    paddingVertical: spacing.md,
    gap: spacing.md,
  },
  backBtn: { width: 44, height: 44, alignItems: "flex-start", justifyContent: "center" },
  headerTitle: { color: colors.primaryFg, fontSize: 18, fontWeight: "700" },
  body: { padding: spacing.screen, gap: spacing.md, paddingBottom: spacing.xl },
  lead: { fontSize: 15, color: colors.textMain, lineHeight: 22 },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
    alignItems: "center",
  },
  qrWrap: { backgroundColor: "#FFFFFF", padding: spacing.md, borderRadius: radii.input },
  codeText: { fontSize: 13, color: colors.textMuted, textAlign: "center" },
  cardTitle: { fontSize: 16, fontWeight: "700", color: colors.textMain },
  cardBody: { fontSize: 14, color: colors.textMain, lineHeight: 20, textAlign: "center" },
  warnBox: {
    backgroundColor: colors.surfaceMuted,
    borderRadius: radii.input,
    padding: spacing.md,
    gap: spacing.sm,
  },
  scanWrap: { height: 280, borderRadius: radii.card, overflow: "hidden", backgroundColor: "#000000" },
  orText: { fontSize: 13, color: colors.textMuted, textAlign: "center" },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.input,
    minHeight: 48,
    paddingHorizontal: spacing.md,
    color: colors.textMain,
  },
  primaryBtn: {
    backgroundColor: colors.primary,
    borderRadius: radii.button,
    minHeight: 48,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryText: { color: colors.primaryFg, fontSize: 16, fontWeight: "700" },
  secondaryBtn: {
    minHeight: 48,
    borderRadius: radii.button,
    borderWidth: 1,
    borderColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.md,
  },
  secondaryText: { color: colors.primary, fontSize: 15, fontWeight: "600" },
  msg: { fontSize: 14, color: colors.textMain, lineHeight: 20 },
  err: { fontSize: 14, color: colors.error },
  privacy: { fontSize: 12, color: colors.textMuted, lineHeight: 18, marginTop: spacing.sm },
});
