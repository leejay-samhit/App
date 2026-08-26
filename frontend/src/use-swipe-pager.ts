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
 * Thresholds: claim at |dx| > 24 while |dy| < 24, commit at |dx| > 60 OR a
 * fast flick (|vx| > 0.35) so short, quick swipes register like they do in
 * WhatsApp.
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
        cbRef.current.enabled && Math.abs(g.dx) > 24 && Math.abs(g.dy) < 24,
      onPanResponderRelease: (_e, g) => {
        if (!cbRef.current.enabled) return;
        const committed = Math.abs(g.dx) > 60 || Math.abs(g.vx) > 0.35;
        if (!committed) return;
        if (g.dx < 0) cbRef.current.onNext();
        else cbRef.current.onPrev();
      },
    }),
  ).current;

  return responder.panHandlers;
}
