/**
 * Chat-side personalization hook.
 *
 * Single React context that owns:
 *   - Wallpaper preferences (default + per-thread overrides + preset palette)
 *   - Chat-lock state (has_pin, lock_chat_tab, locked_thread_ids, use_biometric)
 *   - An in-memory "recently-unlocked" set so the user doesn't have to re-enter
 *     the PIN every time they reopen a locked thread within the same session.
 *
 * Backend wire-up: GET /api/chat/settings on auth + after every successful
 * lock/wallpaper mutation. Mutations are exposed as methods that POST/PATCH
 * and refresh the local state.
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, ReactNode } from "react";
import { api } from "./api";
import { useAuth } from "./auth";

export type Wallpaper = { kind: "preset" | "color" | "image"; value: string };

export type ChatSettings = {
  default_wallpaper: Wallpaper | null;
  thread_wallpapers: Record<string, Wallpaper | null>;
  has_pin: boolean;
  use_biometric: boolean;
  lock_chat_tab: boolean;
  locked_thread_ids: string[];
  presets: Record<string, string>;
};

type Ctx = {
  settings: ChatSettings | null;
  loading: boolean;
  reload: () => Promise<void>;
  // Wallpaper
  setDefaultWallpaper: (wp: Wallpaper | null) => Promise<void>;
  setThreadWallpaper: (threadId: string, wp: Wallpaper | null) => Promise<void>;
  wallpaperFor: (threadId: string) => Wallpaper | null;
  // Lock
  isThreadLocked: (threadId: string) => boolean;
  isTabLocked: () => boolean;
  markUnlocked: (key: "tab" | string) => void;
  isUnlocked: (key: "tab" | string) => boolean;
  clearUnlocks: () => void;
};

const DEFAULT_PRESETS: Record<string, string> = {
  default:    "#F2F1EC",
  "green-soft": "#E8F1EA",
  sky:        "#E3F2FD",
  sand:       "#FFF4DC",
  rose:       "#FCE4EC",
  slate:      "#1F2A24",
  midnight:   "#0B1411",
  doodle:     "#F7F2E8",
};

const EMPTY: ChatSettings = {
  default_wallpaper: null,
  thread_wallpapers: {},
  has_pin: false,
  use_biometric: false,
  lock_chat_tab: false,
  locked_thread_ids: [],
  presets: DEFAULT_PRESETS,
};

const ChatSettingsCtx = createContext<Ctx | null>(null);

export function ChatSettingsProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [settings, setSettings] = useState<ChatSettings | null>(null);
  const [loading, setLoading] = useState(false);
  // In-memory unlock set — forgotten on app restart so the user must
  // re-authenticate after a cold launch.
  const unlockedRef = useRef<Set<string>>(new Set());

  const reload = useCallback(async () => {
    if (!user?.id) {
      setSettings(null);
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.get<ChatSettings>("/chat/settings");
      setSettings({
        default_wallpaper:  data.default_wallpaper ?? null,
        thread_wallpapers:  data.thread_wallpapers ?? {},
        has_pin:            !!data.has_pin,
        use_biometric:      !!data.use_biometric,
        lock_chat_tab:      !!data.lock_chat_tab,
        locked_thread_ids:  Array.isArray(data.locked_thread_ids) ? data.locked_thread_ids : [],
        presets:            data.presets || DEFAULT_PRESETS,
      });
    } catch {
      setSettings(EMPTY);
    } finally {
      setLoading(false);
    }
  }, [user?.id]);

  // Refetch when the authenticated user changes (login / logout).
  useEffect(() => { reload(); }, [reload]);

  const setDefaultWallpaper = useCallback(async (wp: Wallpaper | null) => {
    const body = wp ? { default: wp } : { clear_default: true };
    const { data } = await api.patch<ChatSettings>("/chat/settings/wallpaper", body);
    setSettings({ ...EMPTY, ...data });
  }, []);

  const setThreadWallpaper = useCallback(async (threadId: string, wp: Wallpaper | null) => {
    const { data } = await api.patch<ChatSettings>("/chat/settings/wallpaper", {
      thread_wallpapers: { [threadId]: wp },
    });
    setSettings({ ...EMPTY, ...data });
  }, []);

  const wallpaperFor = useCallback((threadId: string): Wallpaper | null => {
    if (!settings) return null;
    const override = settings.thread_wallpapers?.[threadId];
    if (override) return override;
    return settings.default_wallpaper || null;
  }, [settings]);

  const isThreadLocked = useCallback((threadId: string) => {
    return !!settings?.has_pin && !!settings.locked_thread_ids?.includes(threadId);
  }, [settings]);

  const isTabLocked = useCallback(() => {
    return !!settings?.has_pin && !!settings.lock_chat_tab;
  }, [settings]);

  const markUnlocked = useCallback((key: "tab" | string) => {
    unlockedRef.current.add(key);
  }, []);
  const isUnlocked = useCallback((key: "tab" | string) => unlockedRef.current.has(key), []);
  const clearUnlocks = useCallback(() => { unlockedRef.current = new Set(); }, []);

  const value = useMemo<Ctx>(() => ({
    settings, loading, reload,
    setDefaultWallpaper, setThreadWallpaper, wallpaperFor,
    isThreadLocked, isTabLocked, markUnlocked, isUnlocked, clearUnlocks,
  }), [settings, loading, reload, setDefaultWallpaper, setThreadWallpaper, wallpaperFor, isThreadLocked, isTabLocked, markUnlocked, isUnlocked, clearUnlocks]);

  return <ChatSettingsCtx.Provider value={value}>{children}</ChatSettingsCtx.Provider>;
}

export function useChatSettings(): Ctx {
  const ctx = useContext(ChatSettingsCtx);
  if (!ctx) throw new Error("useChatSettings must be inside <ChatSettingsProvider>");
  return ctx;
}

// Resolve a Wallpaper object to the actual View style. The chat screen + the
// preview tiles in /chat/settings both call this so they always look
// identical.
export function wallpaperStyle(wp: Wallpaper | null, presets: Record<string, string>) {
  if (!wp) return { backgroundColor: presets["default"] || "#F2F1EC" };
  if (wp.kind === "preset") return { backgroundColor: presets[wp.value] || presets["default"] || "#F2F1EC" };
  if (wp.kind === "color")  return { backgroundColor: wp.value };
  // image — callers should layer an <Image source={{uri: wp.value}}/> below;
  // here we just provide a neutral background under it.
  return { backgroundColor: "#000" };
}
