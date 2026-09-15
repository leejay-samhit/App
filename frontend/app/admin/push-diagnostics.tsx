// Admin · Push notification diagnostics (Sep 2026).
// Shows the WHOLE pipeline with the relay's own answers — relay key state,
// device registrations, and every send attempt with its HTTP status and
// response body. Nothing here is inferred.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput,
  ActivityIndicator, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, spacing } from "../../src/theme";

type Diag = {
  key_configured: boolean;
  relay_base_url: string;
  channels: { orders: string; chat: string; note: string };
  totals: {
    attempts: number; accepted_by_relay: number; rejected: number;
    by_stage: Record<string, number>; by_result: Record<string, number>;
  };
  devices: { total: number; by_status: Record<string, number>; rows: any[] };
  relay_probe: { reachable?: boolean; http_status?: number; body?: string; error?: string };
  recent_sends: any[];
  verdict: string;
};

const VERDICT: Record<string, { title: string; body: string; ok: boolean }> = {
  relay_key_missing: {
    title: "Relay key not injected yet",
    body: "EMERGENT_PUSH_KEY is still 'placeholder' in this environment, so nothing has been handed to Firebase. It is filled in automatically when you Publish/Deploy — run this check again on the deployed build.",
    ok: false,
  },
  no_device_registered: {
    title: "No phone has registered",
    body: "The key is live but no device token has reached the relay. Open the installed APK/AAB build (Expo Go and the web preview cannot receive push), allow notifications, then retry.",
    ok: false,
  },
  relay_rejecting: {
    title: "The relay is rejecting sends",
    body: "Every attempt came back as an error. The exact status and response body are in the attempts list below — that is Firebase's/SuprSend's own answer, not our guess.",
    ok: false,
  },
  pipeline_healthy: {
    title: "Pipeline healthy",
    body: "Sends are being accepted by the relay. If a specific phone still shows nothing, check that phone's channel settings (Orders & delivery / Chat messages) and that the app was not force-stopped.",
    ok: true,
  },
  nothing_sent_yet: {
    title: "No sends recorded yet",
    body: "Trigger any notification (or use the test push below) and refresh.",
    ok: false,
  },
};

export default function PushDiagnosticsScreen() {
  const router = useRouter();
  const [diag, setDiag] = useState<Diag | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [email, setEmail] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<any>(null);
  const [userReport, setUserReport] = useState<any>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Diag>("/admin/push/diagnostics?limit=50");
      setDiag(data);
      setErr("");
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const sendTest = async () => {
    setTesting(true); setErr("");
    try {
      const { data } = await api.post("/push/test", {
        title: "Slangcart test",
        message: "If this is in your notification bar, push is fixed.",
        target_email: email.trim() || undefined,
      });
      setTestResult(data);
      await load();
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setTesting(false);
    }
  };

  const lookupUser = async () => {
    if (!email.trim()) { setErr("Type an email first."); return; }
    setErr("");
    try {
      const { data } = await api.get(`/admin/push/diagnostics/user?email=${encodeURIComponent(email.trim())}`);
      setUserReport(data);
    } catch (e) {
      setErr(formatApiError(e));
    }
  };

  const v = diag ? (VERDICT[diag.verdict] || VERDICT.nothing_sent_yet) : null;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="push-diag-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Push diagnostics</Text>
      </View>

      {loading ? (
        <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: spacing.screen, paddingBottom: 60 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
        >
          {v ? (
            <View style={[styles.verdict, v.ok ? styles.verdictOk : styles.verdictBad]}>
              <Feather name={v.ok ? "check-circle" : "alert-triangle"} size={18} color={v.ok ? "#166534" : "#92400E"} />
              <View style={{ flex: 1 }}>
                <Text style={[styles.verdictTitle, { color: v.ok ? "#166534" : "#92400E" }]}>{v.title}</Text>
                <Text style={styles.verdictBody}>{v.body}</Text>
              </View>
            </View>
          ) : null}

          <Block title="Pipeline">
            <Row label="Relay key injected" value={diag?.key_configured ? "Yes" : "No — placeholder"} />
            <Row label="Relay host reachable" value={diag?.relay_probe?.reachable ? `Yes (HTTP ${diag?.relay_probe?.http_status})` : `No — ${diag?.relay_probe?.error || "unknown"}`} />
            <Row label="Send attempts" value={String(diag?.totals?.attempts ?? 0)} />
            <Row label="Accepted by relay" value={String(diag?.totals?.accepted_by_relay ?? 0)} />
            <Row label="Rejected" value={String(diag?.totals?.rejected ?? 0)} />
            <Row label="Registered devices" value={String(diag?.devices?.total ?? 0)} />
            <Row label="Android channel (orders)" value={diag?.channels?.orders || "—"} />
            <Row label="Android channel (chat)" value={diag?.channels?.chat || "—"} />
            <Text style={styles.note}>{diag?.channels?.note}</Text>
          </Block>

          <Block title="Send a test push">
            <TextInput
              value={email}
              onChangeText={setEmail}
              placeholder="Target email (blank = yourself)"
              placeholderTextColor={colors.textMuted}
              autoCapitalize="none"
              keyboardType="email-address"
              style={styles.input}
              testID="push-diag-email"
            />
            <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
              <TouchableOpacity onPress={sendTest} disabled={testing} style={[styles.btn, { flex: 1 }]} testID="push-diag-send">
                {testing ? <ActivityIndicator size="small" color="#fff" /> : <Text style={styles.btnText}>Send test push</Text>}
              </TouchableOpacity>
              <TouchableOpacity onPress={lookupUser} style={[styles.btn, styles.btnGhost, { flex: 1 }]} testID="push-diag-lookup">
                <Text style={[styles.btnText, { color: colors.textMain }]}>Check this account</Text>
              </TouchableOpacity>
            </View>
            {err ? <Text style={styles.err}>{err}</Text> : null}
            {testResult ? (
              <View style={styles.resultBox}>
                <Row label="Result" value={testResult.ok ? "Accepted by relay" : `Not delivered (${testResult.relay})`} />
                <Row label="Relay HTTP status" value={String(testResult.relay_http_status ?? "—")} />
                <Row label="Relay response" value={String(testResult.relay_response || "—")} />
                <Row label="Channel used" value={String(testResult.channel_id || "—")} />
                <Row label="Sent to" value={String(testResult.sent_to_email || "—")} />
                <Row label="Devices on file" value={String((testResult.devices || []).length)} />
                <Text style={styles.note}>{testResult.hint}</Text>
              </View>
            ) : null}
          </Block>

          {userReport ? (
            <Block title={`Account · ${userReport.user?.email}`}>
              <Row label="In-app notifications stored" value={String(userReport.in_app_notifications)} />
              <Row label="Last registration" value={String(userReport.user?.push_registration?.status || "never")} />
              <Row label="Token fingerprint" value={String(userReport.user?.push_registration?.token_fingerprint || "—")} />
              <Row label="Build" value={String(userReport.user?.push_registration?.app_ownership || "—")} />
              <Row label="Permission" value={String(userReport.user?.push_registration?.permission_status || "—")} />
              <Text style={styles.subHead}>Devices</Text>
              {(userReport.devices || []).length === 0 ? (
                <Text style={styles.note}>No device has ever registered for this account.</Text>
              ) : userReport.devices.map((d: any) => (
                <View key={d.id} style={styles.mini}>
                  <Text style={styles.miniTitle}>{d.platform} · {d.device_name || "device"}</Text>
                  <Text style={styles.miniBody}>
                    {d.status} · upstream {String(d.upstream_status)} · {d.token_fingerprint}
                  </Text>
                  <Text style={styles.miniBody}>
                    build {d.app_ownership || "—"} · OS {d.os_version || "—"} · perms {d.permission_status || "—"} ·
                    {" "}{d.registrations} registration(s) · last {String(d.last_seen_at || "").slice(0, 19).replace("T", " ")}
                  </Text>
                </View>
              ))}
              <Text style={styles.subHead}>Last sends to this account</Text>
              {(userReport.recent_sends || []).slice(0, 10).map((s: any) => (
                <View key={s.id} style={styles.mini}>
                  <Text style={styles.miniTitle}>{s.title}</Text>
                  <Text style={styles.miniBody}>
                    {s.stage} · {s.result} · HTTP {String(s.http_status ?? "—")} · channel {s.channel_id || "—"} ·
                    {" "}{String(s.created_at || "").slice(0, 19).replace("T", " ")}
                  </Text>
                  {s.upstream_body ? <Text style={styles.miniBody}>{s.upstream_body}</Text> : null}
                </View>
              ))}
            </Block>
          ) : null}

          <Block title="Last 50 send attempts">
            {(diag?.recent_sends || []).length === 0 ? (
              <Text style={styles.note}>Nothing recorded yet.</Text>
            ) : diag!.recent_sends.map((s: any) => (
              <View key={s.id} style={styles.mini} testID={`push-attempt-${s.id}`}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <Feather
                    name={s.stage === "accepted" ? "check-circle" : s.stage === "rejected" ? "x-circle" : "minus-circle"}
                    size={12}
                    color={s.stage === "accepted" ? "#166534" : s.stage === "rejected" ? "#991B1B" : colors.textMuted}
                  />
                  <Text style={[styles.miniTitle, { flex: 1 }]} numberOfLines={1}>{s.title || "(no title)"}</Text>
                </View>
                <Text style={styles.miniBody}>
                  {s.stage} · {s.result} · HTTP {String(s.http_status ?? "—")} · {s.sent_recipients ?? s.requested_recipients} recipient(s) ·
                  {" "}channel {s.channel_id || "—"} · {s.category || "uncategorised"}
                </Text>
                <Text style={styles.miniBody}>{String(s.created_at || "").slice(0, 19).replace("T", " ")}</Text>
                {s.upstream_body ? <Text style={styles.miniBody} numberOfLines={3}>{s.upstream_body}</Text> : null}
              </View>
            ))}
          </Block>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.block}>
      <Text style={styles.blockTitle}>{title}</Text>
      {children}
    </View>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface,
  },
  iconBtn: { padding: 8, minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain, marginLeft: 4 },
  verdict: { flexDirection: "row", gap: 10, borderRadius: 14, padding: 14, alignItems: "flex-start" },
  verdictOk: { backgroundColor: "#DCFCE7" },
  verdictBad: { backgroundColor: "#FEF3C7" },
  verdictTitle: { fontSize: 14, fontWeight: "900" },
  verdictBody: { fontSize: 12, color: colors.textMain, marginTop: 4, lineHeight: 18 },
  block: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 14, padding: 16, marginTop: 12,
  },
  blockTitle: { fontSize: 14, fontWeight: "900", color: colors.textMain, marginBottom: 10 },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 3, gap: 12 },
  rowLabel: { fontSize: 12, color: colors.textMuted, flexShrink: 1 },
  rowValue: { fontSize: 12, fontWeight: "700", color: colors.textMain, maxWidth: "58%", textAlign: "right" },
  note: { fontSize: 11, color: colors.textMuted, marginTop: 8, lineHeight: 16 },
  subHead: {
    fontSize: 11, fontWeight: "900", color: colors.primary, marginTop: 12, marginBottom: 6,
    textTransform: "uppercase", letterSpacing: 0.6,
  },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12,
    minHeight: 46, color: colors.textMain, backgroundColor: colors.surface, fontSize: 13,
  },
  btn: {
    backgroundColor: colors.primary, borderRadius: 999, minHeight: 46, alignItems: "center",
    justifyContent: "center", paddingHorizontal: 14,
  },
  btnGhost: { backgroundColor: colors.surfaceMuted },
  btnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 13 },
  err: { color: colors.error, fontSize: 12, fontWeight: "700", marginTop: 10 },
  resultBox: {
    marginTop: 12, backgroundColor: colors.surfaceMuted, borderRadius: 12, padding: 12,
  },
  mini: {
    borderTopWidth: 1, borderTopColor: colors.border, paddingVertical: 8, gap: 2,
  },
  miniTitle: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  miniBody: { fontSize: 11, color: colors.textMuted, lineHeight: 16 },
});
