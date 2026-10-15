// AI Elements `message` (registry.ai-sdk.dev): Message and MessageContent only. The Streamdown
// markdown renderer (MessageResponse), branches, attachments and tooltips are removed: answer and
// source text is only ever rendered as React text children (FR-002: withheld values never displayed).

import { cn } from "@/lib/utils";
import type { HTMLAttributes } from "react";

export type MessageProps = HTMLAttributes<HTMLDivElement> & {
  from: "user" | "assistant";
};

/** One side of the conversation; `from` aligns it and styles its MessageContent. */
export const Message = ({ className, from, ...props }: MessageProps) => (
  <div
    className={cn(
      "group flex w-full flex-col gap-2",
      from === "user" ? "is-user items-end" : "is-assistant",
      className,
    )}
    data-from={from}
    {...props}
  />
);

export type MessageContentProps = HTMLAttributes<HTMLDivElement>;

/** A bubble for the user's message; full width, unboxed, for the assistant's. */
export const MessageContent = ({ children, className, ...props }: MessageContentProps) => (
  <div
    className={cn(
      "flex min-w-0 max-w-full flex-col",
      "group-[.is-user]:max-w-[85%] group-[.is-user]:rounded-[20px_20px_6px_20px] group-[.is-user]:bg-secondary group-[.is-user]:px-4 group-[.is-user]:py-2.5",
      "group-[.is-assistant]:w-full",
      className,
    )}
    {...props}
  >
    {children}
  </div>
);
