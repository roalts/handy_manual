// Work-order draft sheet (specs/contracts/work-orders-audit.md), lazy-loaded with its form code.

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import { getDraft, isApiError } from "@/lib/api";
import type { DevUser, Identity, WorkOrderDraft, WorkOrderSuggestion } from "@/lib/types";
import { keys } from "@/app/query";
import { AppSheet } from "@/features/AppSheet";
import { DraftForm } from "./DraftForm";
import { NewDraftForm } from "./NewDraftForm";

export interface PendingDraft {
  answerId: string;
  suggestion: WorkOrderSuggestion;
}

type Props =
  | { mode: "new"; pending: PendingDraft; onCreated: (draft: WorkOrderDraft) => void; onClose: () => void }
  | { mode: "existing"; draftId: string; identity: Identity; users: DevUser[]; onClose: () => void };

/** A new draft that still needs its machine, or an existing draft by ID. */
export default function DraftSheet(props: Props) {
  return props.mode === "new" ? <NewDraftSheet {...props} /> : <ExistingDraftSheet {...props} />;
}

/** Sheet around the asset-ID form for a suggestion that named no machine. */
function NewDraftSheet({ pending, onCreated, onClose }: Extract<Props, { mode: "new" }>) {
  useEffect(() => { document.title = "New work order · Handy Manual"; }, []);
  return (
    <AppSheet onClose={onClose} title={<span id="draft-title">New work order</span>}>
      <NewDraftForm onCreated={onCreated} pending={pending} />
    </AppSheet>
  );
}

/** Refetches the draft each time it opens and shows the form, or why it can't (403, 404, other errors). */
function ExistingDraftSheet({ draftId, identity, users, onClose }: Extract<Props, { mode: "existing" }>) {
  useEffect(() => { document.title = "Work order draft · Handy Manual"; }, []);
  const q = useQuery({ queryKey: keys.draft(draftId), queryFn: () => getDraft(draftId), staleTime: 0 });
  const status = isApiError(q.error) ? q.error.status : null;

  if (q.data) {
    return (
      <AppSheet onClose={onClose} title={<span id="draft-title">Work order draft</span>}>
        <DraftForm draft={q.data} identity={identity} key={q.data.draft_id} users={users} />
      </AppSheet>
    );
  }
  if (status === 403 || status === 404) {
    return (
      <AppSheet onClose={onClose} title={<span id="nv-title">{status === 403 ? "Not visible to you" : "Draft not found"}</span>}>
        <section className={`card ${status === 403 ? "not-visible" : "abstain"}`}>
          <p>{status === 403 ? "This draft cites a source your permissions don't include." : "There is no draft with this ID."}</p>
        </section>
      </AppSheet>
    );
  }
  if (q.error && status !== 401) {
    return (
      <AppSheet onClose={onClose} title="Couldn't open the draft">
        <section className="card error" role="alert">
          <Button onClick={() => void q.refetch()} type="button">Try again</Button>
        </section>
      </AppSheet>
    );
  }
  return (
    <AppSheet onClose={onClose} title="Opening draft…">
      <p className="hint" role="status">Opening draft…</p>
    </AppSheet>
  );
}
