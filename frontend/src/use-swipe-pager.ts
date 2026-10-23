/**
 * useSwipePager — one horizontal-swipe behaviour for the whole app.
 *
 * Jun 2026. Every place that has a row of tabs/sections (the bottom tab bar,
 * My Orders status filters, shop home categories, a shop category's
 * sub-sections) now flicks left/right with the SAME feel, so muscle memory
 * carries across screens.
 *
 * Why PanResponder and not react-native-gesture-handler?
 *   • It works identically on iOS, Android and the web preview.
 *   • Non-capturing `onMoveShouldSetPanResponder` means children that own the
 *     touch (vertical ScrollViews, horizontal chip strips, buttons) keep it —
 *     we only claim drags that are unambiguously horizontal.
 *
 * Thresholds (Jun 2026 — lightened per owner feedback "make the swipe
 * lighter"): claim at |dx| > 14 while |dy| < 14 and the drag is clearly more
 * horizontal than vertical, commit at |dx| > 40 OR a flick (|vx| > 0.22) so a
 * short, quick swipe registers like it does in WhatsApp.
 */
import { useRef } from "react";
import { PanResponder } from "react-native";

type Options = {
  /** Called on a left swipe (move forward in the list). */
  onNext: () => void;
  /** Called on a right swipe (move backward in the list). */
  onPrev: () => void;
  /** Set false to disable the gesture entirely (e.g. desktop web). */
  enabled?: boolean;
};

export function useSwipePager({ onNext, onPrev, enabled = true }: Options) {
  // Keep the latest callbacks without rebuilding the responder every render.
  const cbRef = useRef({ onNext, onPrev, enabled });
  cbRef.current = { onNext, onPrev, enabled };

  const responder = useRef(
    PanResponder.create({
      onMoveShouldSetPanResponder: (_e, g) =>
        cbRef.current.enabled &&
        Math.abs(g.dx) > 14 &&
        Math.abs(g.dy) < 14 &&
        Math.abs(g.dx) > Math.abs(g.dy) * 1.5,
      onPanResponderRelease: (_e, g) => {
        if (!cbRef.current.enabled) return;
        const committed = Math.abs(g.dx) > 40 || Math.abs(g.vx) > 0.22;
        if (!committed) return;
        if (g.dx < 0) cbRef.current.onNext();
        else cbRef.current.onPrev();
      },
    }),
  ).current;

  return responder.panHandlers;
}

/**
 * Jun 2026 — the same flick for an IN-SCREEN tab / filter strip (My Orders
 * status filters, Net Worth sections, admin Approvals, vendor Returns …).
 * Pass the tab keys in the order they are drawn plus the current value:
 *
 *   const swipe = useTabSwipe(ORDER, tab, setTab);
 *   <SafeAreaView {...swipe}>
 *
 * Swiping stops at the ends (no wrap-around), which is what users expect
 * from a filter row.
 */
export function useTabSwipe<T extends string>(
  order: readonly T[],
  current: T,
  setTab: (t: T) => void,
) {
  const ref = useRef({ order, current, setTab });
  ref.current = { order, current, setTab };
  const step = (dir: 1 | -1) => {
    const { order: o, current: c, setTab: set } = ref.current;
    const i = o.indexOf(c);
    if (i < 0) return;
    const next = o[i + dir];
    if (next !== undefined) set(next);
  };
  return useSwipePager({ onNext: () => step(1), onPrev: () => step(-1) });
}
