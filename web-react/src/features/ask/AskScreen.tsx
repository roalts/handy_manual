// The thread: each turn is the question as a bubble and the answer under it. Turns stay in memory
// until "New question", sign-out or reload; only the last one is sent as `previous`.

import { ArrowRight, TriangleAlert } from "lucide-react";
import { type RefObject, useEffect, useRef, useState } from "react";
import { Conversation, ConversationContent } from "@/components/ai-elements/conversation";
import { Message, MessageContent } from "@/components/ai-elements/message";
import { PromptInput, PromptInputSubmit, PromptInputTextarea } from "@/components/ai-elements/prompt-input";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { Mark } from "@/components/Mark";
import { Button } from "@/components/ui/button";
import type { ClarifyOption, Turn, WorkOrderSuggestion } from "@/lib/types";
import { previousTurn } from "@/lib/text";
import { storedQuestion } from "@/app/question";
import { AnswerView } from "@/features/answer/AnswerView";
import type { AskError, Pending } from "./useAsk";

const SLOW_HINT_MS = 6000;

const EXAMPLES = [
  "Casing bolt torque for FRS-P-0031 after a seal change",
  "E-31 on TAC-C-0143, how do I reset it?",
  "Warranty on the BX-20 conveyor",
  "Casing torque on the HCP-350 at Fresno",
  "Rated head of the HCP-200",
  "Which oil for the VRS-75 RTM-C-0121?",
];

interface Props {
  firstName: string;
  turns: Turn[];
  pending: Pending | null;
  error: AskError | null;
  canRetry: boolean;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  onSubmit: (question: string) => void;
  onRetry: () => void;
  onCancel: () => void;
  onNewQuestion: () => void;
  onClarify: (option: ClarifyOption) => void;
  /** Every change to the composer's text, typed or filled from an example. */
  onComposerInput: (text: string) => void;
  onDraft: (suggestion: WorkOrderSuggestion, answerId: string) => void;
}

/** The thread, the pending or failed turn, example questions while it is empty, and the composer dock. */
export function AskScreen({ firstName, turns, pending, error, canRetry, textareaRef, onSubmit, onRetry, onCancel, onNewQuestion, onClarify, onComposerInput, onDraft }: Props) {
  const current = turns[turns.length - 1] ?? null;
  const followUp = previousTurn(current) !== null;
  const settled = !pending && !error;

  const fillExample = (q: string) => {
    onComposerInput(q);
    const ta = textareaRef.current;
    if (ta) {
      ta.value = q;
      ta.focus();
    }
  };

  return (
    <section aria-label="Ask" className="ask flex min-h-[calc(100dvh-56px)] flex-col">
      <div className="result flex-1 pt-2" id="result">
        <Conversation>
          <ConversationContent className="gap-8">
            {turns.map((t, i) => {
              const last = i === turns.length - 1;
              return (
                <section className="turn scroll-mt-16" key={i}>
                  <Asked question={t.request.question} />
                  <Message className="mt-4" from="assistant">
                    <MessageContent>
                      <AssistantHead />
                      <AnswerView
                        headingId={last && settled ? "answer-heading" : `answer-heading-${i + 1}`}
                        latest={last && settled}
                        onClarify={onClarify}
                        onDraft={onDraft}
                        question={t.request.question}
                        resp={t.response}
                      />
                    </MessageContent>
                  </Message>
                </section>
              );
            })}
            {pending && <PendingTurn onCancel={onCancel} pending={pending} />}
            {!pending && error && <ErrorBlock canRetry={canRetry} error={error} onRetry={onRetry} />}
            {!turns.length && !pending && !error && <EmptyState firstName={firstName} onPick={fillExample} />}
          </ConversationContent>
        </Conversation>
      </div>

      <div className="dock sticky bottom-0 z-[4] -mx-4 bg-background px-3 pt-2 pb-[max(10px,env(safe-area-inset-bottom))]">
        {followUp && (
          <p className="follow-up m-0 mb-1 flex items-center justify-between gap-2 pl-1 text-[14px] text-ink-soft">
            <span>Follow-up to the answer above</span>
            <Button className="text-link" id="new-question" onClick={onNewQuestion} size="sm" type="button" variant="ghost">
              New question
            </Button>
          </p>
        )}
        <PromptInput className="composer" onSubmit={(text) => onSubmit(text)}>
          <label className="sr-only" htmlFor="question">{followUp ? "Your follow-up question" : "Your question"}</label>
          <PromptInputTextarea
            defaultValue={storedQuestion()}
            id="question"
            maxLength={2000}
            onInput={(e) => onComposerInput(e.currentTarget.value)}
            placeholder={followUp ? "Ask a follow-up" : "Ask the Handy Manual"}
            ref={textareaRef}
            required
            rows={1}
          />
          <PromptInputSubmit aria-label={pending ? "Sending" : "Ask"} className="send" disabled={Boolean(pending)} pending={Boolean(pending)} />
        </PromptInput>
        <p className="dock-hint mt-1.5 mb-0 text-center text-[14px] text-ink-soft">Answers come only from the documents you can see.</p>
      </div>
    </section>
  );
}

/** The user's question as a bubble. */
function Asked({ question }: { question: string }) {
  return (
    <Message from="user">
      <MessageContent>
        <p className="asked m-0 font-medium"><span className="asked-label sr-only">You asked: </span>{question}</p>
      </MessageContent>
    </Message>
  );
}

/** Mark and name above each answer; hidden from screen readers. */
function AssistantHead() {
  return (
    <p aria-hidden className="m-0 mb-2.5 flex items-center gap-2 text-[15px] font-semibold text-ink-soft">
      <Mark className="mark size-[22px]" />Handy Manual
    </p>
  );
}

/** Greeting and example questions before the first question; picking one fills the composer, it doesn't send. */
function EmptyState({ firstName, onPick }: { firstName: string; onPick: (q: string) => void }) {
  return (
    <section aria-labelledby="empty-title" className="empty pt-4">
      <Mark className="mark brand-mark mb-3.5 size-11" />
      <h2 className="m-0 text-[27px] leading-tight tracking-[-0.02em]" id="empty-title">
        {firstName ? `Hi ${firstName}, what are you working on?` : "What are you working on?"}
      </h2>
      <p className="mt-2 text-ink-soft">
        Ask about a machine, a fault code or a part. Name the machine by the asset ID on its nameplate. Every answer shows its sources.
      </p>
      <ul aria-label="Example questions" className="examples m-0 mt-5 list-none p-0">
        {EXAMPLES.map((q) => (
          <li className="border-t border-line first:border-t-0" key={q}>
            <button className="example flex min-h-tap w-full cursor-pointer items-center justify-between gap-3 bg-transparent py-3 text-left text-[16px] text-ink" onClick={() => onPick(q)} type="button">
              <span>{q}</span><ArrowRight aria-hidden className="icon text-ink-soft" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The question being answered, scrolled into view, with Cancel; a slow-signal hint after 6 s from the send. */
function PendingTurn({ pending, onCancel }: { pending: Pending; onCancel: () => void }) {
  const [slow, setSlow] = useState(false);
  const turn = useRef<HTMLElement>(null);
  useEffect(() => {
    turn.current?.scrollIntoView({ block: "start" });
  }, []);
  useEffect(() => {
    const wait = SLOW_HINT_MS - (Date.now() - pending.startedAt);
    const t = window.setTimeout(() => setSlow(true), Math.max(0, wait));
    return () => window.clearTimeout(t);
  }, [pending.startedAt]);
  return (
    <section className="turn scroll-mt-16" ref={turn}>
      <Asked question={pending.request.question} />
      <Message className="mt-4" from="assistant">
        <MessageContent>
          <AssistantHead />
          <div aria-live="polite" className="card pending" role="status">
            <h2 className="m-0 text-[17px] font-semibold" tabIndex={-1}><Shimmer as="span">Finding an answer…</Shimmer></h2>
            {slow && <p className="hint slow-hint">Still working. A weak signal can slow this down; your question is kept.</p>}
            <Button className="mt-2" onClick={onCancel} size="sm" type="button" variant="secondary">Cancel</Button>
          </div>
        </MessageContent>
      </Message>
    </section>
  );
}

/** Why the last ask failed, focused when shown; "Try again" only when the error allows a retry. */
function ErrorBlock({ error, canRetry, onRetry }: { error: AskError; canRetry: boolean; onRetry: () => void }) {
  return (
    <section className="card error" role="alert">
      <h2 className="block-title text-[17px]" ref={(el) => el?.focus()} tabIndex={-1}><TriangleAlert aria-hidden className="icon" />{error.title}</h2>
      <p className="mt-1">{error.text}</p>
      {error.question && (
        <p className="asked text-[15px] text-ink-soft">
          <span className="asked-label font-semibold text-ink">Your question:</span> {error.question}
        </p>
      )}
      {canRetry && error.retry && <Button onClick={onRetry} type="button">Try again</Button>}
    </section>
  );
}
