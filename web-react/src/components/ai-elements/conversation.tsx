// AI Elements `conversation` (registry.ai-sdk.dev), layout only. StickToBottom is removed: a new
// answer is scrolled to its question and read from its first line, so the page scrolls normally.

import { cn } from "@/lib/utils";
import type { ComponentProps, ReactNode } from "react";

export type ConversationProps = ComponentProps<"div">;

/** The thread container, exposed to assistive technology as a log. */
export const Conversation = ({ className, ...props }: ConversationProps) => (
  <div className={cn("relative flex-1", className)} role="log" {...props} />
);

export type ConversationContentProps = ComponentProps<"div">;

/** Stacks the messages vertically. */
export const ConversationContent = ({ className, ...props }: ConversationContentProps) => (
  <div className={cn("flex flex-col gap-4 pb-3", className)} {...props} />
);

export type ConversationEmptyStateProps = ComponentProps<"section"> & {
  title?: string;
  description?: string;
  icon?: ReactNode;
};

/** Shown before the first message: optional icon, a title, an optional description, then children. */
export const ConversationEmptyState = ({
  className,
  title = "No messages yet",
  description,
  icon,
  children,
  ...props
}: ConversationEmptyStateProps) => (
  <section className={cn("flex flex-col gap-3 py-2", className)} {...props}>
    {icon && <div className="text-muted-foreground">{icon}</div>}
    <h2>{title}</h2>
    {description && <p>{description}</p>}
    {children}
  </section>
);
