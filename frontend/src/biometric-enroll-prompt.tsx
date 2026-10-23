/**
 * First-login fingerprint enrolment prompt.
 *
 * Jun 2026 owner request: "After the first login ask EVERY user to set up
 * fingerprint login, so from next time they sign in with their fingerprint."
 *
 * Rules kept deliberately gentle:
 *   • Asked ONCE per account per device (the answer is remembered by user id).
 *   • Never shown when the phone has no biometric enrolled, on web, or when
 *     the user already has fingerprint login switched on.
 *   • "Not now" is always available — biometrics never block anyone, the
 *     email + password path stays exactly as it was.
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Modal, TouchableOpacity, ActivityIndicator,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useAuth } from "./auth";
import { colors, radii } from "./theme";
import { notify } from "./notify";

const ASKED_KEY = (uid: string) => `biometric_asked_v1:${uid}`;

export function BiometricEnrollPrompt() {
  const { user, biometricAvailable, biometricReady, enableBiometric } = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const uid = user?.id;
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!uid || !biometricAvailable || biometricReady) return;
      const asked = await AsyncStorage.getItem(ASKED_KEY(uid));
      if (!cancelled && asked !== "1") setOpen(true);
    })();
    return () => { cancelled = true; };
  }, [uid, biometricAvailable, biometricReady]);

  const remember = async () => {
    if (uid) await AsyncStorage.setItem(ASKED_KEY(uid), "1").catch(() => {});
  };

  const onEnable = async () => {
    setBusy(true);
    try {
      await enableBiometric();
      await remember();
      setOpen(false);
      notify("Fingerprint login is on", "Next time, just touch the sensor to sign in.");
    } catch (e: any) {
      notify("Couldn't turn it on", e?.message || "Please try again from Profile.");
    } finally {
      setBusy(false);
    }
  };

  const onSkip = async () => {
    await remember();
    setOpen(false);
  };

  if (!open) return null;
  return (
    <Modal visible transparent animationType="fade" onRequestClose={onSkip}>
      <View style={s.backdrop}>
        <View style={s.card} testID="biometric-enroll-prompt">
          <View style={s.iconCircle}>
            <Feather name="unlock" size={26} color={colors.primary} />
          </View>
          <Text style={s.title}>Sign in with your fingerprint?</Text>
          <Text style={s.body}>
            Set it up once and you can open your account with a touch — no typing your
            email and password again on this phone.
          </Text>
          <TouchableOpacity
            onPress={onEnable}
            disabled={busy}
            style={[s.primary, busy && { opacity: 0.6 }]}
            testID="biometric-enroll-yes"
          >
            {busy ? <ActivityIndicator color={colors.primaryFg} /> : (
              <>
                <Feather name="check-circle" size={16} color={colors.primaryFg} />
                <Text style={s.primaryText}>Turn on fingerprint login</Text>
              </>
            )}
          </TouchableOpacity>
          <TouchableOpacity onPress={onSkip} style={s.ghost} testID="biometric-enroll-later">
            <Text style={s.ghostText}>Not now</Text>
          </TouchableOpacity>
          <Text style={s.foot}>
            You can change this any time in Profile → Security.
          </Text>
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  backdrop: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.45)",
    alignItems: "center", justifyContent: "center", padding: 24,
  },
  card: {
    width: "100%", maxWidth: 380, backgroundColor: colors.surface,
    borderRadius: radii.card, padding: 22, alignItems: "center",
    borderWidth: 1, borderColor: colors.border,
  },
  iconCircle: {
    width: 56, height: 56, borderRadius: 28, backgroundColor: colors.brand100,
    alignItems: "center", justifyContent: "center", marginBottom: 14,
  },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain, textAlign: "center" },
  body: {
    fontSize: 13, color: colors.textMuted, fontWeight: "600",
    textAlign: "center", marginTop: 8, lineHeight: 19,
  },
  primary: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 14,
    width: "100%", marginTop: 18, minHeight: 48,
  },
  primaryText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  ghost: { paddingVertical: 12, minHeight: 44, justifyContent: "center" },
  ghostText: { color: colors.textMuted, fontWeight: "700", fontSize: 13.5 },
  foot: { fontSize: 11, color: colors.textMuted, textAlign: "center" },
});
