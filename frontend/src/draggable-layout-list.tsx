// DraggableLayoutList — long-press drag-to-reorder list backed by
// react-native-gesture-handler + react-native-reanimated. Works on both
// native & Expo web. On release, computes the new order and emits
// `onReorder(newIds[])`. The admin caller then POSTs to
// /admin/shop-layout/reorder.
import React, { useCallback, useRef, useState } from "react";
import { View, StyleSheet, LayoutChangeEvent, Platform } from "react-native";
import { Gesture, GestureDetector, GestureHandlerRootView } from "react-native-gesture-handler";
import Animated, { useSharedValue, useAnimatedStyle, withSpring, runOnJS, withTiming } from "react-native-reanimated";

type Props<T extends { id: string }> = {
  items: T[];
  renderItem: (item: T, isDragging: boolean) => React.ReactNode;
  onReorder: (newIds: string[]) => void;
  // optional: a function returning an extra grab handle inside the item
  // (when not provided, long-press anywhere on the card triggers drag).
};

export function DraggableLayoutList<T extends { id: string }>({ items, renderItem, onReorder }: Props<T>) {
  const [order, setOrder] = useState<T[]>(items);
  const [dragId, setDragId] = useState<string | null>(null);
  const heightsRef = useRef<Record<string, number>>({});
  // Keep order synced when parent items change (e.g. after reload)
  React.useEffect(() => { setOrder(items); }, [items]);

  const measure = useCallback((id: string, e: LayoutChangeEvent) => {
    heightsRef.current[id] = e.nativeEvent.layout.height;
  }, []);

  // Commit a new order and notify parent.
  const commitOrder = useCallback((fromId: string, toIndex: number) => {
    setOrder((prev) => {
      const fromIdx = prev.findIndex((p) => p.id === fromId);
      if (fromIdx === -1) return prev;
      const next = [...prev];
      const [moved] = next.splice(fromIdx, 1);
      next.splice(Math.max(0, Math.min(next.length, toIndex)), 0, moved);
      // Defer parent call so animation can complete first
      setTimeout(() => onReorder(next.map((x) => x.id)), 50);
      return next;
    });
  }, [onReorder]);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <View>
        {order.map((item, index) => (
          <DraggableRow
            key={item.id}
            item={item}
            index={index}
            isDragging={dragId === item.id}
            onMeasure={measure}
            onDragStart={() => setDragId(item.id)}
            onDragEnd={(deltaY) => {
              setDragId(null);
              const h = heightsRef.current[item.id] || 80;
              const steps = Math.round(deltaY / h);
              if (steps !== 0) commitOrder(item.id, index + steps);
            }}
          >
            {renderItem(item, dragId === item.id)}
          </DraggableRow>
        ))}
      </View>
    </GestureHandlerRootView>
  );
}

function DraggableRow({ item, index, isDragging, onMeasure, onDragStart, onDragEnd, children }: any) {
  const translateY = useSharedValue(0);
  const scale = useSharedValue(1);
  const zIndex = useSharedValue(0);

  const gesture = Gesture.Pan()
    .activateAfterLongPress(280)
    .onStart(() => {
      scale.value = withSpring(1.04, { damping: 14 });
      zIndex.value = 100;
      runOnJS(onDragStart)();
    })
    .onUpdate((e) => {
      translateY.value = e.translationY;
    })
    .onEnd(() => {
      const delta = translateY.value;
      translateY.value = withTiming(0, { duration: 160 });
      scale.value = withSpring(1, { damping: 14 });
      zIndex.value = 0;
      runOnJS(onDragEnd)(delta);
    });

  const animStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: translateY.value }, { scale: scale.value }],
    zIndex: zIndex.value,
    ...(Platform.OS === "web" ? ({ position: "relative" as any }) : {}),
  }));

  return (
    <GestureDetector gesture={gesture}>
      <Animated.View
        onLayout={(e) => onMeasure(item.id, e)}
        style={[animStyle, isDragging && styles.lifted]}
      >
        {children}
      </Animated.View>
    </GestureDetector>
  );
}

const styles = StyleSheet.create({
  lifted: { opacity: 0.95 },
});
