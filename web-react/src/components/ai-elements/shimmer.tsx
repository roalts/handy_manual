// AI Elements `shimmer` (registry.ai-sdk.dev) with a CSS animation in place of the `motion`
// library, which would cost more of the first-load budget than the rest of the ask screen.
// Stops under prefers-reduced-motion (see `.shimmer` in index.css).

import { cn } from "@/lib/utils";
import type { ElementType } from "react";

export type ShimmerProps = {
  children: string;
  as?: ElementType;
  className?: string;
};

/** Text with a moving highlight while something loads; renders as a paragraph unless `as` says otherwise. */
export const Shimmer = ({ children, as: Component = "p", className }: ShimmerProps) => (
  <Component className={cn("shimmer inline-block", className)}>{children}</Component>
);
