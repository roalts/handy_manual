// AI Elements `confirmation` (registry.ai-sdk.dev), without the AI SDK tool-approval states: here
// it is the body of the "Send to MaintPro/Servio?" dialog (FR-006: explicit confirmation).

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ComponentProps } from "react";

export type ConfirmationProps = ComponentProps<typeof Alert>;

/** Borderless soft-filled box holding the confirmation text. */
export const Confirmation = ({ className, ...props }: ConfirmationProps) => (
  <Alert className={cn("flex flex-col gap-2 border-0 bg-paper-soft", className)} {...props} />
);

/** What will happen; wraps instead of being cut to one line like an AlertTitle. */
export const ConfirmationTitle = ({ className, ...props }: ComponentProps<typeof AlertTitle>) => (
  <AlertTitle className={cn("line-clamp-none", className)} {...props} />
);

/** The details being confirmed, in full-contrast text. */
export const ConfirmationRequest = ({ className, ...props }: ComponentProps<typeof AlertDescription>) => (
  <AlertDescription className={cn("text-foreground", className)} {...props} />
);

/** Row of equal-width action buttons that wraps when they don't fit. */
export const ConfirmationActions = ({ className, ...props }: ComponentProps<"div">) => (
  <div className={cn("flex flex-wrap items-center gap-2 [&>*]:flex-1 [&>*]:whitespace-nowrap", className)} {...props} />
);

/** A Button that never submits a surrounding form. */
export const ConfirmationAction = (props: ComponentProps<typeof Button>) => <Button type="button" {...props} />;
