// AI Elements `sources` (registry.ai-sdk.dev). Open by default and links stay in the app (the
// published version opens new tabs); the trigger keeps a 44 px tap target.

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { ChevronDownIcon } from "lucide-react";
import type { ComponentProps } from "react";

export type SourcesProps = ComponentProps<typeof Collapsible>;

/** Collapsible source list, open unless `defaultOpen` is false. */
export const Sources = ({ className, defaultOpen = true, ...props }: SourcesProps) => (
  <Collapsible className={cn("sources mt-5 border-t-2 border-line pt-2", className)} defaultOpen={defaultOpen} {...props} />
);

export type SourcesTriggerProps = ComponentProps<typeof CollapsibleTrigger> & { count: number };

/** Full-width toggle; without children it reads "Sources (count)". The chevron flips when open. */
export const SourcesTrigger = ({ className, count, children, ...props }: SourcesTriggerProps) => (
  <CollapsibleTrigger
    className={cn("group/sources flex min-h-tap w-full cursor-pointer items-center justify-between gap-2 text-left", className)}
    {...props}
  >
    {children ?? <h3 className="m-0">Sources ({count})</h3>}
    <ChevronDownIcon aria-hidden className="size-5 transition-transform group-data-[state=open]/sources:rotate-180" />
  </CollapsibleTrigger>
);

export type SourcesContentProps = ComponentProps<typeof CollapsibleContent>;

/** The collapsible body holding the Source links. */
export const SourcesContent = ({ className, ...props }: SourcesContentProps) => (
  <CollapsibleContent className={cn("outline-none", className)} {...props} />
);

export type SourceProps = ComponentProps<"a">;

/** One source as a plain link with a tap-sized row. */
export const Source = ({ className, ...props }: SourceProps) => (
  <a className={cn("source-link flex min-h-tap flex-col justify-center no-underline", className)} {...props} />
);
