/**
 * Shared index for the animation primitives.
 *
 * Standardises `import { FadeSlideIn, Skeleton, ANIM } from "src/anim"`
 * everywhere so screens don't need to remember the exact file paths.
 */
export { FadeSlideIn, FadeIn, ANIM } from "./fade-slide-in";
export { Skeleton, ProductCardSkeleton, ListRowSkeleton, StatCardSkeleton } from "./skeleton";
