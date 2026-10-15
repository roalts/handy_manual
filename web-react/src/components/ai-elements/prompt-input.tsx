// AI Elements `prompt-input` (registry.ai-sdk.dev): the form, textarea and submit button, restyled
// as one Graphite pill. Attachments, speech input, model selects, command menus, hover cards and
// the input-group wrapper are removed. The textarea's keyboard rule is kept as published: Enter
// sends, Shift+Enter adds a line, and nothing is sent while an input method is composing.

import { cn } from "@/lib/utils";
import { ArrowUp, Loader2Icon } from "lucide-react";
import { type ComponentProps, type FormEvent, type KeyboardEventHandler, useState } from "react";

export type PromptInputProps = Omit<ComponentProps<"form">, "onSubmit"> & {
  onSubmit: (text: string, event: FormEvent<HTMLFormElement>) => void;
};

/** The composer form. Calls `onSubmit` with the text of the field named "question"; never reloads the page. */
export const PromptInput = ({ className, onSubmit, children, ...props }: PromptInputProps) => (
  <form
    className={cn("flex w-full items-end gap-1.5 rounded-[26px] bg-paper-soft focus-within:outline-3 focus-within:outline-offset-2 focus-within:outline-[var(--focus)]", className)}
    onSubmit={(event) => {
      event.preventDefault();
      const text = new FormData(event.currentTarget).get("question");
      onSubmit(typeof text === "string" ? text : "", event);
    }}
    {...props}
  >
    {children}
  </form>
);

export type PromptInputTextareaProps = ComponentProps<"textarea">;

/** Growing textarea named "question". Enter does nothing while the submit button is disabled. */
export const PromptInputTextarea = ({ className, onKeyDown, ...props }: PromptInputTextareaProps) => {
  const [isComposing, setIsComposing] = useState(false);

  const handleKeyDown: KeyboardEventHandler<HTMLTextAreaElement> = (e) => {
    onKeyDown?.(e);
    if (e.defaultPrevented || e.key !== "Enter") return;
    if (isComposing || e.nativeEvent.isComposing || e.shiftKey) return;
    e.preventDefault();
    const form = e.currentTarget.form;
    const submit = form?.querySelector<HTMLButtonElement>('button[type="submit"]');
    if (submit?.disabled) return;
    form?.requestSubmit();
  };

  return (
    <textarea
      className={cn(
        "field-sizing-content max-h-[40vh] min-h-12 flex-1 resize-none border-0 bg-transparent py-3 pr-1 pl-4 text-[17px] text-ink outline-none placeholder:text-ink-soft placeholder:opacity-100",
        className,
      )}
      name="question"
      onCompositionEnd={() => setIsComposing(false)}
      onCompositionStart={() => setIsComposing(true)}
      onKeyDown={handleKeyDown}
      {...props}
    />
  );
};

export type PromptInputSubmitProps = ComponentProps<"button"> & {
  pending?: boolean;
};

/** Round send button; without children it shows an arrow, or a spinner while `pending`. */
export const PromptInputSubmit = ({ className, pending, children, ...props }: PromptInputSubmitProps) => (
  <button
    className={cn(
      "m-0.5 inline-flex size-tap flex-none cursor-pointer items-center justify-center rounded-full bg-brand text-[var(--brand-ink)] disabled:cursor-not-allowed disabled:opacity-55",
      className,
    )}
    type="submit"
    {...props}
  >
    {children ?? (pending ? <Loader2Icon aria-hidden className="size-5 animate-spin" /> : <ArrowUp aria-hidden className="size-5" />)}
  </button>
);
