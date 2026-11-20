import { Platform, Alert } from "react-native";
// Use legacy API for cacheDirectory/writeAsStringAsync/EncodingType — still supported in v55.
import * as FileSystem from "expo-file-system/legacy";
import * as Sharing from "expo-sharing";
import { getAuthToken, api } from "./api";

const BASE_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

/**
 * Nov 2026 — pack the backup ON THE SERVER, then download the finished file.
 *
 * Packing a whole-app backup can take many minutes on a large Atlas database;
 * holding the screen open while it streams means a minimized app pauses the
 * download. This helper instead:
 *   1. starts a server-side pack job (POST /admin/backup/file/prepare),
 *   2. polls it until the file is ready (calling `onProgress` along the way),
 *   3. downloads the packed file in seconds.
 * The server keeps packing even if the app is closed — reopening the app and
 * tapping again starts a fresh pack if the old one expired.
 */
export async function downloadPackedBackup(opts: {
  scope: "app" | "account";
  userId?: string;
  filename: string;
  onProgress?: (msg: string) => void;
  /** Called once with the job id so the screen can offer a Cancel button. */
  onJobStarted?: (jobId: string) => void;
}): Promise<{ ok: boolean; path?: string; bytes?: number; warnings?: string[] }> {
  const { scope, userId, filename, onProgress, onJobStarted } = opts;
  const { data: job } = await api.post<any>("/admin/backup/file/prepare", {
    scope,
    user_id: scope === "account" ? userId : undefined,
  });
  onJobStarted?.(job.job_id);
  let status: any = null;
  let idle = 0;
  for (let tries = 0; tries < 1800; tries++) { // up to ~60 min of polling
    await new Promise((r) => setTimeout(r, 2000));
    try {
      const { data } = await api.get<any>(`/admin/backup/file/jobs/${job.job_id}`);
      status = data;
      const mb = (Number(data.bytes_written || 0) / 1024 / 1024).toFixed(1);
      const docs = Number(data.docs_written || 0).toLocaleString("en-IN");
      const where = data.current_collection ? ` · ${data.current_collection}` : "";
      onProgress?.(
        `Packing on the server… ${data.collections_done || 0}/${data.collections_total || "?"} tables` +
          `${where} · ${docs} records · ${mb} MB`,
      );
      if (data.status === "ready" || data.status === "failed" || data.status === "cancelled") break;
      idle = 0;
    } catch {
      // transient network blip while polling — keep waiting, but don't poll
      // a vanished job forever.
      if (++idle > 30) break;
    }
  }
  if (!status || status.status !== "ready") {
    if (status?.status === "cancelled") throw new Error("Backup cancelled.");
    throw new Error(
      status?.error
        ? `${status.error}${status.failed_on ? ` (while packing ${status.failed_on})` : ""}`
        : "The server could not finish the pack. Please try again.",
    );
  }
  onProgress?.("Downloading the packed file…");
  const res = await downloadServerFile({
    path: `/admin/backup/file/jobs/${job.job_id}/download`,
    filename,
  });
  return { ...res, warnings: status.warnings || [] };
}

/** Stop a pack that is taking too long and free the space it used. */
export async function cancelPackedBackup(jobId: string): Promise<void> {
  await api.post(`/admin/backup/file/jobs/${jobId}/cancel`, {});
}

/**
 * Save a LARGE server-generated file (e.g. the full-app backup) without ever
 * holding it in JS memory.
 *
 * The old path fetched every page of every collection, stitched a ~120 MB
 * string in JS and handed it to FileSystem.writeAsStringAsync — which threw
 * `java.lang.OutOfMemoryError: Failed to allocate a 126097912 byte
 * allocation` on Android. Native now streams the response straight to disk
 * via downloadAsync; web lets the browser own the download.
 *
 * `path` is an /api-relative path, e.g. "/admin/backup/file".
 */
export async function downloadServerFile(opts: {
  path: string;
  filename: string;
  mimeType?: string;
}): Promise<{ ok: boolean; path?: string; bytes?: number }> {
  const { path, filename, mimeType = "application/json" } = opts;
  const token = await getAuthToken();
  const url = `${BASE_URL}/api${path}`;
  const headers = token ? { Authorization: `Bearer ${token}` } : undefined;

  if (Platform.OS === "web") {
    try {
      const resp = await fetch(url, { headers });
      if (!resp.ok) throw new Error(`Server returned ${resp.status}`);
      const blob = await resp.blob();
      // @ts-ignore — window/document exist on web only
      const href = window.URL.createObjectURL(blob);
      // @ts-ignore
      const a = document.createElement("a");
      a.href = href; a.download = filename; a.style.display = "none";
      // @ts-ignore
      document.body.appendChild(a); a.click();
      // @ts-ignore
      document.body.removeChild(a);
      // @ts-ignore
      setTimeout(() => { try { window.URL.revokeObjectURL(href); } catch {} }, 1500);
      return { ok: true, bytes: blob.size };
    } catch (e: any) {
      Alert.alert("Download failed", e?.message || "Could not download the file.");
      return { ok: false };
    }
  }

  try {
    const dir = (FileSystem as any).cacheDirectory || (FileSystem as any).documentDirectory;
    if (!dir) throw new Error("No writable directory available");
    const dest = `${dir}${filename}`;
    const res = await FileSystem.downloadAsync(url, dest, { headers });
    if (res.status !== 200) throw new Error(`Server returned ${res.status}`);
    const info: any = await FileSystem.getInfoAsync(dest, { size: true } as any);
    if (await Sharing.isAvailableAsync()) {
      await Sharing.shareAsync(dest, { mimeType, dialogTitle: filename });
    } else {
      Alert.alert("Saved", `File saved to: ${dest}`);
    }
    return { ok: true, path: dest, bytes: info?.size };
  } catch (e: any) {
    Alert.alert("Save failed", e?.message || "Could not save the file.");
    return { ok: false };
  }
}

/**
 * Save a text payload (CSV / JSON / etc.) to the device. On web it triggers a
 * browser download via a blob + anchor click. On native (iOS/Android) it
 * writes to the cache directory and presents the share sheet so the user can
 * save it to Files / Drive / etc.
 */
export async function downloadText(opts: {
  filename: string;
  content: string;
  mimeType?: string;
}): Promise<{ ok: boolean; method: "browser" | "share"; path?: string }> {
  const { filename, content, mimeType = "text/csv" } = opts;

  if (Platform.OS === "web") {
    try {
      // Use the global Blob + URL APIs — these exist in the web preview Metro renders.
      const blob = new Blob([content], { type: `${mimeType};charset=utf-8;` });
      // @ts-ignore — window/document are available on web only
      const url = window.URL.createObjectURL(blob);
      // @ts-ignore
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.style.display = "none";
      // @ts-ignore
      document.body.appendChild(a);
      a.click();
      // @ts-ignore
      document.body.removeChild(a);
      // Revoke after a tick so Safari/iOS Safari has time to use it.
      setTimeout(() => {
        try {
          // @ts-ignore
          window.URL.revokeObjectURL(url);
        } catch {}
      }, 1500);
      return { ok: true, method: "browser" };
    } catch (e: any) {
      Alert.alert("Download failed", e?.message || "Could not start the file download.");
      return { ok: false, method: "browser" };
    }
  }

  // Native: write to cache then open share sheet.
  try {
    const dir = (FileSystem as any).cacheDirectory || (FileSystem as any).documentDirectory;
    if (!dir) throw new Error("No writable directory available");
    const path = `${dir}${filename}`;
    await FileSystem.writeAsStringAsync(path, content, {
      encoding: FileSystem.EncodingType.UTF8,
    });
    const sharingAvailable = await Sharing.isAvailableAsync();
    if (sharingAvailable) {
      await Sharing.shareAsync(path, { mimeType, dialogTitle: filename });
    } else {
      Alert.alert("Saved", `File saved to: ${path}`);
    }
    return { ok: true, method: "share", path };
  } catch (e: any) {
    Alert.alert("Save failed", e?.message || "Could not save the export.");
    return { ok: false, method: "share" };
  }
}
