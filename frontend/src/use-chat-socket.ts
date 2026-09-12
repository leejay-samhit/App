// Real-time chat WebSocket hook. Connects to /api/ws/chat with the user's
// JWT in the ?token= query. Auto-reconnects with exponential backoff PLUS
// foreground/visibility-aware reconnect so a paused-then-resumed app
// reconnects immediately instead of waiting out the backoff.
import { useEffect, useRef, useState } from "react";
import { AppState, AppStateStatus, Platform } from "react-native";
import { getAuthToken } from "./api";

const BASE_URL = process.env.EXPO_PUBLIC_BACKEND_URL || "";

// Heartbeat: send a "ping" every 20s so corporate proxies / mobile carriers
// don't silently kill the socket after a minute of inactivity. The server
// echoes "pong" — see routes/chat.py:websocket_chat.
const HEARTBEAT_MS = 20_000;

function wsUrlFromHttp(token: string): string {
  const u = BASE_URL.replace(/^https?:\/\//, (m) => (m === "https://" ? "wss://" : "ws://"));
  return `${u.replace(/\/$/, "")}/api/ws/chat?token=${encodeURIComponent(token)}`;
}

export type ChatSocketEvent =
  | { type: "hello"; user_id: string }
  | { type: "request.new"; request: any; from: any }
  | { type: "request.accepted"; request_id: string; thread_id: string }
  | { type: "request.rejected"; request_id: string }
  | { type: "message.new"; thread_id: string; message: any }
  | { type: "message.edited"; thread_id: string; message: any }
  | { type: "message.deleted"; thread_id: string; message_id: string }
  | { type: "message.reacted"; thread_id: string; message_id: string; reactions: Record<string, string[]> }
  | { type: "message.delivered"; thread_id: string; by_user_id: string }
  | { type: "typing"; thread_id: string; user_id: string; at: string };

export function useChatSocket(onEvent: (ev: ChatSocketEvent) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number>(0);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const [connected, setConnected] = useState(false);
  // Which thread the user has OPEN. Sent to the server so it can skip the
  // phone push for a message the user is already reading (and, crucially,
  // still push when the app is merely connected in the background).
  const viewingRef = useRef<string | null>(null);

  const sendViewing = (threadId: string | null) => {
    viewingRef.current = threadId;
    try {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "viewing", thread_id: threadId }));
      }
    } catch { /* socket will re-announce on reconnect */ }
  };
  const sendViewingRef = useRef(sendViewing);
  sendViewingRef.current = sendViewing;

  useEffect(() => {
    let cancelled = false;
    let paused = false;
    let timer: any = null;
    let heartbeat: any = null;

    const stopHeartbeat = () => {
      if (heartbeat) { clearInterval(heartbeat); heartbeat = null; }
    };

    const startHeartbeat = () => {
      stopHeartbeat();
      heartbeat = setInterval(() => {
        try {
          const ws = wsRef.current;
          if (ws && ws.readyState === WebSocket.OPEN) ws.send("ping");
        } catch { /* ignore */ }
      }, HEARTBEAT_MS);
    };

    const connect = async () => {
      if (cancelled || paused) return;
      const token = await getAuthToken();
      if (!token) {
        timer = setTimeout(connect, 3000);
        return;
      }
      try {
        const ws = new WebSocket(wsUrlFromHttp(token));
        wsRef.current = ws;
        ws.onopen = () => {
          reconnectRef.current = 0;
          setConnected(true);
          startHeartbeat();
          // Re-announce the open thread after every reconnect.
          if (viewingRef.current) {
            try { ws.send(JSON.stringify({ type: "viewing", thread_id: viewingRef.current })); } catch { /* ignore */ }
          }
        };
        ws.onmessage = (e) => {
          // Text "pong" is the heartbeat reply — ignore.
          if (typeof e.data === "string" && e.data === "pong") return;
          try {
            const data = typeof e.data === "string" ? JSON.parse(e.data) : e.data;
            if (data && data.type) onEventRef.current(data);
          } catch { /* ignore non-JSON frames */ }
        };
        ws.onerror = () => { /* close handler will retry */ };
        ws.onclose = () => {
          setConnected(false);
          wsRef.current = null;
          stopHeartbeat();
          if (cancelled || paused) return;
          // Exponential backoff capped at 30s.
          const delay = Math.min(30_000, 1000 * Math.pow(2, reconnectRef.current));
          reconnectRef.current += 1;
          timer = setTimeout(connect, delay);
        };
      } catch {
        timer = setTimeout(connect, 3000);
      }
    };

    // Nov 2026 (battery) — the socket is a FOREGROUND thing. Holding it open
    // in the background meant a keep-alive frame every 20 s plus reconnect
    // storms every time the carrier dropped the idle socket, which kept the
    // radio awake all day. Offline delivery is the push relay's job, so the
    // socket is closed on background and re-opened instantly on foreground.
    const onAppState = (state: AppStateStatus) => {
      if (cancelled) return;
      if (state !== "active") {
        paused = true;
        if (timer) { clearTimeout(timer); timer = null; }
        stopHeartbeat();
        try { wsRef.current?.close(); } catch { /* ignore */ }
        wsRef.current = null;
        setConnected(false);
        return;
      }
      paused = false;
      const ws = wsRef.current;
      if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
        // Skip the backoff — user is looking at the app right now.
        if (timer) { clearTimeout(timer); timer = null; }
        reconnectRef.current = 0;
        connect();
      }
    };
    const appStateSub = AppState.addEventListener("change", onAppState);

    // On web, also listen to visibility so reopening the tab reconnects fast.
    let visListener: (() => void) | null = null;
    if (Platform.OS === "web" && typeof document !== "undefined") {
      visListener = () => {
        onAppState(document.visibilityState === "visible" ? "active" : "background");
      };
      document.addEventListener("visibilitychange", visListener);
    }

    connect();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      stopHeartbeat();
      try { appStateSub.remove(); } catch { /* ignore */ }
      if (visListener && typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", visListener);
      }
      try { wsRef.current?.close(); } catch { /* ignore */ }
    };
  }, []);

  return { connected, setViewingThread: (threadId: string | null) => sendViewingRef.current(threadId) };
}
