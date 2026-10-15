// AI Elements `suggestion` (registry.ai-sdk.dev). Suggestions stack vertically as full-width
// buttons instead of a horizontal scroll area, so long machine names and questions stay readable.

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ComponentProps } from "react";

export type SuggestionsProps = ComponentProps<"ul">;

/** List of Suggestion items. */
export const Suggestions = ({ className, ...props }: SuggestionsProps) => (
  <ul className={cn("m-0 mt-2 grid list-none gap-2 p-0", className)} {...props} />
);

export type SuggestionProps<T> = Omit<ComponentProps<typeof Button>, "onClick"> & {
  suggestion: T;
  onClick?: (suggestion: T) => void;
};

/** One option as an outline button in a list item; a tap passes its `suggestion` to `onClick`. */
export const Suggestion = <T,>({ suggestion, onClick, className, variant = "outline", children, ...props }: SuggestionProps<T>) => (
  <li>
    <Button
      className={cn("w-full justify-start text-left", className)}
      onClick={() => onClick?.(suggestion)}
      type="button"
      variant={variant}
      {...props}
    >
      {children}
    </Button>
  </li>
);
