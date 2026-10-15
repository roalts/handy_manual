// Handy Manual mobile client: sign-in, ask, answer, source sheet, work-order draft sheet.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { SquarePen } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "@/app/toast";
import { Mark } from "@/components/Mark";
import { createDraft, isApiError, signIn, signOut } from "@/lib/api";
import { goBack, navigate, replace, useRoute } from "@/lib/router";
import { clarifyRequest, previousTurn } from "@/lib/text";
import type { AskRequest, ClarifyOption, Identity, WorkOrderDraft, WorkOrderSuggestion } from "@/lib/types";
import { SourceGroupContext, type GroupItem } from "@/features/answer/sourceGroup";
import { AskScreen } from "@/features/ask/AskScreen";
import { useAsk, type AskOutcome } from "@/features/ask/useAsk";
import type { PendingDraft } from "@/features/draft/DraftSheet";
import { SignIn } from "@/features/signin/SignIn";
import { UserMenu } from "@/features/signin/UserMenu";
import { useAnnounce } from "./announce";
import { useDevUsers, useGroups, useSession } from "./directory";
import { keys, onSessionExpired } from "./query";
import { storedQuestion, storeQuestion } from "./question";

const SourceSheet = lazy(() => import("@/features/source/SourceSheet"));
const DraftSheet = lazy(() => import("@/features/draft/DraftSheet"));
const Toaster = lazy(() => import("@/components/ui/sonner").then((m) => ({ default: m.Toaster })));

/**
 * The whole client: the sign-in screen when signed out, else the ask screen with the source or
 * draft sheet over it as the route says. Owns the composer text and the ask thread.
 */
export function App() {
  const route = useRoute();
  const qc = useQueryClient();
  const announce = useAnnounce();
  const session = useSession();
  const identity = session.data ?? null;
  const devUsers = useDevUsers();
  useGroups(Boolean(identity));

  const [signInMessage, setSignInMessage] = useState<string | null>(null);
  const [newDraft, setNewDraft] = useState<PendingDraft | null>(null);
  const [sourceGroup, setSourceGroup] = useState<GroupItem[]>([]);
  const textarea = useRef<HTMLTextAreaElement>(null);
  // What the composer holds, kept here too because an expired session unmounts it mid-request.
  const composerText = useRef(storedQuestion());
  const inFlight = useRef(false);

  const onAnswered = useCallback(() => {
    requestAnimationFrame(() => {
      const heading = document.getElementById("answer-heading");
      const turn = heading?.closest(".turn");
      if (turn) turn.scrollIntoView({ block: "start" });
      else window.scrollTo(0, 0);
      heading?.focus({ preventScroll: true });
      announce(`${heading?.textContent ?? "Answer"} ready.`);
    });
  }, [announce]);
  const asking = useAsk(onAnswered);
  const { reset: resetAsk } = asking;

  useEffect(() => onSessionExpired(() => {
    qc.setQueryData(keys.session, null);
    resetAsk();
    setNewDraft(null);
    setSignInMessage("Your session expired. Sign in again; your question is kept.");
  }), [qc, resetAsk]);

  const signedIn = Boolean(identity);
  const sessionKnown = session.isSuccess || session.isError;

  useEffect(() => {
    if (!sessionKnown) return;
    if (!signedIn && route.name !== "signin") replace("#/signin");
    else if (signedIn && route.name === "signin") replace("#/ask");
  }, [sessionKnown, signedIn, route.name]);
  const shownSignInMessage = signInMessage ?? (session.isError ? "No connection. Sign-in needs a connection." : null);

  const signInMutation = useMutation({
    mutationFn: signIn,
    onSuccess: (who: Identity) => {
      setSignInMessage(null);
      qc.setQueryData(keys.session, who);
      announce(`Signed in as ${who.name}.`);
      navigate("#/ask");
    },
    onError: (err) => setSignInMessage(isApiError(err) && err.status === 0 ? "No connection. Try again." : "That user can't sign in."),
  });

  const doSignOut = async () => {
    try {
      await signOut();
    } catch {
      // Signing out locally still clears everything below.
    }
    resetAsk();
    setNewDraft(null);
    setSourceGroup([]);
    setComposer("");
    storeQuestion("");
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== keys.devUsers[0] });
    qc.setQueryData(keys.session, null);
    navigate("#/signin");
  };

  const setComposer = (text: string) => {
    composerText.current = text;
    if (textarea.current) textarea.current.value = text;
  };

  const onComposerInput = (text: string) => {
    composerText.current = text;
    if (!inFlight.current) storeQuestion(text);
  };

  /**
   * A question sent from the composer leaves it at once but stays in sessionStorage until it is
   * answered, so a reload mid-request still has it. If it isn't answered it goes back into the
   * composer, unless the user has typed something new meanwhile; that text is never overwritten.
   */
  const sendAsk = async (request: AskRequest) => {
    if (inFlight.current) return;
    const typed = composerText.current.trim() === request.question;
    inFlight.current = true;
    if (typed) {
      storeQuestion(request.question);
      setComposer("");
    }
    let outcome: AskOutcome;
    try {
      outcome = await asking.send(request);
    } finally {
      inFlight.current = false;
    }
    if (outcome === "reset" || outcome === "busy") return;
    const now = composerText.current;
    if (outcome === "answered" || !typed || now.trim()) {
      storeQuestion(now);
      return;
    }
    storeQuestion(request.question);
    setComposer(request.question);
  };

  const submitQuestion = (raw: string) => {
    const question = raw.trim();
    if (!question) return textarea.current?.focus();
    const previous = previousTurn(asking.current);
    void sendAsk(previous ? { question, previous } : { question });
  };

  const newQuestion = () => {
    asking.clear();
    window.scrollTo(0, 0);
    announce("New question. The previous answer is cleared.");
    textarea.current?.focus();
  };

  const onClarify = (option: ClarifyOption) => {
    if (asking.current) void sendAsk(clarifyRequest(asking.current, option));
  };

  const draftFromAnswer = useMutation({
    mutationFn: createDraft,
    onSuccess: (d: WorkOrderDraft) => {
      qc.setQueryData(keys.draft(d.draft_id), d);
      navigate(`#/work-orders/${encodeURIComponent(d.draft_id)}`);
    },
    onError: (err) => {
      if (isApiError(err) && err.status === 401) return;
      toast(isApiError(err) && err.status === 0
        ? "Couldn't reach the server. No draft was created. Try again."
        : "The draft couldn't be created. Try again.");
    },
  });

  const onDraft = (suggestion: WorkOrderSuggestion, answerId: string) => {
    if (!suggestion.asset_id) {
      setNewDraft({ answerId, suggestion });
      navigate("#/work-orders/new");
      return;
    }
    draftFromAnswer.mutate({ answer_id: answerId, suggestion });
  };

  const onDraftCreated = (d: WorkOrderDraft) => {
    setNewDraft(null);
    qc.setQueryData(keys.draft(d.draft_id), d);
    announce("Draft created.");
    replace(`#/work-orders/${encodeURIComponent(d.draft_id)}`);
  };

  useEffect(() => {
    if (route.name === "signin") document.title = "Sign in · Handy Manual";
    else if (route.name === "ask") document.title = "Ask · Handy Manual";
  }, [route.name]);

  useEffect(() => {
    if (route.name === "new-draft" && !newDraft && signedIn) replace("#/ask");
  }, [route.name, newDraft, signedIn]);

  const retry = (request: AskRequest | null) => request && void sendAsk(request);

  let body;
  if (!sessionKnown) body = <p className="hint" role="status">Loading…</p>;
  else if (!identity || route.name === "signin") {
    body = (
      <SignIn busy={signInMutation.isPending} message={shownSignInMessage} onSignIn={(id) => id && signInMutation.mutate(id)} users={devUsers.data} />
    );
  } else {
    body = (
      <>
        <AskScreen
          canRetry={Boolean(asking.lastRequest)}
          error={asking.error}
          firstName={identity.name.split(" ")[0] ?? ""}
          onCancel={asking.cancel}
          onClarify={onClarify}
          onComposerInput={onComposerInput}
          onDraft={onDraft}
          onNewQuestion={newQuestion}
          onRetry={() => retry(asking.lastRequest)}
          onSubmit={submitQuestion}
          pending={asking.pending}
          textareaRef={textarea}
          turns={asking.turns}
        />
        <Suspense fallback={null}>
          {route.name === "source" && (
            <SourceSheet
              focus={route.focus}
              group={sourceGroup.some((g) => g.passageId === route.id) ? sourceGroup : []}
              onClose={goBack}
              passageId={route.id}
            />
          )}
          {route.name === "draft" && (
            <DraftSheet draftId={route.id} identity={identity} mode="existing" onClose={goBack} users={devUsers.data ?? []} />
          )}
          {route.name === "new-draft" && newDraft && (
            <DraftSheet mode="new" onClose={goBack} onCreated={onDraftCreated} pending={newDraft} />
          )}
        </Suspense>
      </>
    );
  }

  return (
    <SourceGroupContext.Provider value={setSourceGroup}>
      <a className="skip-link absolute -top-16 left-2 z-10 rounded-full bg-paper px-4 py-2.5 text-ink shadow focus:top-2" href="#main">
        Skip to content
      </a>
      <header className="topbar sticky top-0 z-[5] flex min-h-14 items-center justify-between gap-2 bg-background pt-[env(safe-area-inset-top)] pr-2 pl-3">
        <h1 className="brand m-0 text-[17px] font-bold tracking-[-0.01em]">
          <a className="inline-flex min-h-tap items-center gap-2 text-ink no-underline" href="#/ask"><Mark />Handy Manual</a>
        </h1>
        {identity && (
          <div className="flex items-center">
            {asking.turns.length > 0 && (
              <button aria-label="New question" className="inline-flex size-tap cursor-pointer items-center justify-center rounded-full text-ink hover:bg-paper-soft" onClick={newQuestion} type="button">
                <SquarePen aria-hidden className="size-5" />
              </button>
            )}
            <UserMenu identity={identity} onSignOut={doSignOut} />
          </div>
        )}
      </header>
      <main className="mx-auto max-w-[720px] px-4 pb-6 outline-none" id="main" tabIndex={-1}>
        {body}
      </main>
      <Suspense fallback={null}><Toaster position="top-center" /></Suspense>
    </SourceGroupContext.Provider>
  );
}
