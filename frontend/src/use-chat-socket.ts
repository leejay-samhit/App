// Real-time chat WebSocket hook. Connects to /api/ws/chat with the user's
// JWT in the ?token= query. Auto-reconnects with exponential backoff.
import { useEffect, useRef, useState } from "react";
import { getAuthToken } from "./api";

const BASE_URL = process.env.EXPO_PUBLIC_BACKEND_URL || "";

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
  | { type: "message.deleted"; thread_id: string; message_id: string };

export function useChatSocket(onEvent: (ev: ChatSocketEvent) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number>(0);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: any = null;

    const connect = async () => {
      if (cancelled) return;
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
        };
        ws.onmessage = (e) => {
          try {
            const data = typeof e.data === "string" ? JSON.parse(e.data) : e.data;
            if (data && data.type) onEventRef.current(data);
          } catch { /* ignore */ }
        };
        ws.onerror = () => { /* close handler will retry */ };
        ws.onclose = () => {
          setConnected(false);
          wsRef.current = null;
          if (cancelled) return;
          // Exponential backoff capped at 30s
          const delay = Math.min(30000, 1000 * Math.pow(2, reconnectRef.current));
          reconnectRef.current += 1;
          timer = setTimeout(connect, delay);
        };
      } catch {
        timer = setTimeout(connect, 3000);
      }
    };

    connect();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      try { wsRef.current?.close(); } catch { /* ignore */ }
    };
  }, []);

  return { connected };
}
