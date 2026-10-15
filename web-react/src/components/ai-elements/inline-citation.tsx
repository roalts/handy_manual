// AI Elements `inline-citation` (registry.ai-sdk.dev): InlineCitation, InlineCitationText and a
// tappable trigger. The hover card and carousel are removed: hover doesn't exist on a phone, so a
// citation number is a link that opens the source sheet.

import { cn } from "@/lib/utils";
import type { ComponentProps } from "react";

export type InlineCitationProps = ComponentProps<"span">;

/** Inline wrapper for a cited sentence and its citation controls. */
export const InlineCitation = ({ className, ...props }: InlineCitationProps) => (
  <span className={cn("inline", className)} {...props} />
);

export type InlineCitationTextProps = ComponentProps<"span">;

/** The sentence text itself. */
export const InlineCitationText = ({ className, ...props }: InlineCitationTextProps) => (
  <span className={cn("sentence-text", className)} {...props} />
);

export type InlineCitationChipsProps = ComponentProps<"span">;

/** Citation numbers after the text, wrapping as a group. */
export const InlineCitationChips = ({ className, ...props }: InlineCitationChipsProps) => (
  <span className={cn("chips ms-1 inline-flex flex-wrap gap-1 align-middle", className)} {...props} />
);

export type InlineCitationQuoteProps = ComponentProps<"blockquote">;

/** A quoted excerpt from a source. */
export const InlineCitationQuote = ({ className, ...props }: InlineCitationQuoteProps) => (
  <blockquote className={cn("border-l-2 border-line pl-3 text-muted-foreground italic", className)} {...props} />
);
