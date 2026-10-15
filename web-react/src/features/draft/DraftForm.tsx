// Work-order draft form. Nothing leaves without the confirmation dialog (FR-006).

import { Ban, CircleCheck, CircleX, Send, ShieldAlert } from "lucide-react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useFieldArray, useForm, type UseFormRegisterReturn } from "react-hook-form";
import { toast } from "@/app/toast";
import { Button } from "@/components/ui/button";
import { draftAction, isApiError, patchDraft, type ApiError } from "@/lib/api";
import {
  APPROVAL_REASON_WORDS, DRAFT_STATUS_WORDS, REGION_BY_SYSTEM, SYSTEM_NAMES, groupWords, personLabel, sourceHref,
} from "@/lib/text";
import type { DevUser, Identity, WorkOrderDraft } from "@/lib/types";
import { useAnnounce } from "@/app/announce";
import { keys } from "@/app/query";
import { ConfirmSubmit } from "./ConfirmSubmit";
import { ReadOnly } from "./ReadOnly";
import { draftFormSchema, editsFrom, formFromDraft, type DraftFormValues } from "./schema";

interface Props {
  draft: WorkOrderDraft;
  identity: Identity;
  users: DevUser[];
}

type Message = { kind: "pending" | "error"; text: string } | null;

/** Native `input` events too, so values set by assistive tools and test drivers are seen. */
const onInputToo = (r: UseFormRegisterReturn) => ({ ...r, onInput: r.onChange });

/**
 * Edits a draft and moves it on: save, request approval, approve or reject (approvers only), and
 * submit. Requesting approval and submitting save unsaved edits first; submitting always goes
 * through ConfirmSubmit.
 */
export function DraftForm({ draft, identity, users }: Props) {
  const qc = useQueryClient();
  const announce = useAnnounce();
  const [message, setMessage] = useState<Message>(null);
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);

  const form = useForm<DraftFormValues>({ resolver: zodResolver(draftFormSchema), values: formFromDraft(draft) });
  const parts = useFieldArray({ control: form.control, name: "parts" });

  const editable = draft.status === "draft" || draft.status === "rejected";
  const system = SYSTEM_NAMES[draft.target_system] ?? draft.target_system;
  const needsApproval = draft.approval_reasons.length > 0;
  const blocked = draft.approval_reasons.includes("no eligible approver");
  const approvers = draft.eligible_approvers ?? [];
  const isApprover = approvers.includes(identity.user_id);
  const person = (id: string) => personLabel(id, users);

  const describe = (err: ApiError) => {
    if (err.status === 0 && err.detail === "unsure") {
      return `The connection dropped, so it's not certain the work order reached ${system}. Submit again: it uses the same key and can't create a duplicate.`;
    }
    if (err.status === 0) return "No connection. Your edits are kept here; try again when you have signal.";
    if (err.status === 503 && err.code === "submission_failed") {
      return `${system} couldn't be reached, so nothing was submitted. The draft is unchanged; submitting again is safe.`;
    }
    if (err.status === 403) return "Not visible to you, or you are not allowed to do this.";
    if (err.status === 409) return `This draft can't do that right now${err.detail ? `: ${err.detail}` : ""}.`;
    if (err.status === 422) return `Check the form${err.detail ? `: ${err.detail}` : ""}.`;
    return "Something went wrong. Nothing was sent. Try again.";
  };

  const run = useMutation({
    mutationFn: async ({ fn }: { label: string; fn: () => Promise<WorkOrderDraft | null> }) => fn(),
    onMutate: ({ label }) => setMessage({ kind: "pending", text: `${label}…` }),
    onSuccess: (next) => {
      setMessage(null);
      if (next) qc.setQueryData(keys.draft(next.draft_id), next);
    },
    onError: (err) => {
      if (isApiError(err) && err.status === 401) return setMessage(null);
      setMessage({ kind: "error", text: isApiError(err) ? describe(err) : "Something went wrong. Nothing was sent. Try again." });
    },
  });
  const busy = run.isPending;

  /** Validates and saves the form when it has changes; returns the saved draft, or null when invalid. */
  async function saveIfDirty(): Promise<WorkOrderDraft | null | "invalid"> {
    if (!editable) return draft;
    if (!form.formState.isDirty && draft.status !== "rejected") return draft;
    let values: DraftFormValues | null = null;
    await form.handleSubmit((v) => { values = v; })();
    if (!values) return "invalid";
    const saved = await patchDraft(draft.draft_id, editsFrom(values));
    qc.setQueryData(keys.draft(saved.draft_id), saved);
    return saved;
  }

  const save = () => run.mutate({ label: "Saving", fn: async () => {
    const saved = await saveIfDirty();
    if (saved === "invalid") return null;
    toast("Draft saved.");
    announce("Draft saved.");
    return saved;
  } });

  const requestApproval = () => run.mutate({ label: "Requesting approval", fn: async () => {
    const saved = await saveIfDirty();
    if (saved === "invalid" || !saved) return null;
    if (!saved.approval_reasons.length || saved.approval_reasons.includes("no eligible approver")) return saved;
    const next = await draftAction(saved.draft_id, "request-approval");
    toast("Sent for approval.");
    announce("Sent for approval.");
    return next;
  } });

  const openConfirm = () => run.mutate({ label: "Saving", fn: async () => {
    const saved = await saveIfDirty();
    if (saved === "invalid" || !saved) return null;
    if (!saved.approval_reasons.length || saved.status === "approved") setConfirming(true);
    return saved;
  } });

  const submit = () => {
    setConfirming(false);
    run.mutate({ label: `Sending to ${system}`, fn: async () => {
      try {
        const next = await draftAction(draft.draft_id, "submit", { confirm: true }, { "Idempotency-Key": draft.idempotency_key });
        toast(`Sent to ${system}.`);
        announce(`Sent to ${system}.`);
        return next;
      } catch (err) {
        if (isApiError(err) && err.status === 0) throw Object.assign(err, { detail: "unsure" });
        throw err;
      }
    } });
  };

  const decide = (action: "approve" | "reject", label: string) => () => run.mutate({ label, fn: async () => {
    const next = await draftAction(draft.draft_id, action, { note: note.trim() || null });
    setNote("");
    toast(action === "approve" ? "Approved." : "Rejected.");
    return next;
  } });

  const ro = !editable || busy;
  const err = form.formState.errors;
  const onNote = (e: FormEvent<HTMLTextAreaElement>) => setNote(e.currentTarget.value);

  return (
    <>
      <p className={`draft-status status-${draft.status}`}>
        <span className="tag mr-1 rounded-full bg-brand-soft px-2.5 py-0.5 text-ink">{DRAFT_STATUS_WORDS[draft.status] ?? draft.status}</span>
        {" "}Goes to {system} ({REGION_BY_SYSTEM[draft.target_system] ?? "?"}) when submitted.
      </p>

      <ApprovalBox draft={draft} person={person} system={system} />

      <form aria-labelledby="draft-title" className="draft-form my-2.5" noValidate onSubmit={(e) => e.preventDefault()}>
        <ReadOnly label="Machine" value={draft.asset_id} />
        <div className="field">
          <label htmlFor="wo-fault">Fault code</label>
          <input autoComplete="off" className="field-control" disabled={ro} id="wo-fault" type="text" {...onInputToo(form.register("fault_code"))} />
        </div>
        <div className={`field${err.summary ? " invalid" : ""}`}>
          <label htmlFor="wo-summary">Summary</label>
          <textarea aria-invalid={err.summary ? true : undefined} className="field-control" disabled={ro} id="wo-summary" required rows={3} {...onInputToo(form.register("summary"))} />
          {err.summary && <p className="field-error" role="alert">{err.summary.message}</p>}
        </div>
        <div className="field">
          <label htmlFor="wo-steps">Notes for the technician</label>
          <textarea className="field-control" disabled={ro} id="wo-steps" rows={4} {...onInputToo(form.register("work_steps"))} />
        </div>
        <div className="field">
          <label htmlFor="wo-priority">Priority</label>
          <select className="field-control" disabled={ro} id="wo-priority" {...form.register("priority")}>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </div>
        <ReadOnly
          label="Certification needed"
          value={draft.required_certification.length ? draft.required_certification.map((g) => `${g} (${groupWords(g)})`).join(", ") : "None"}
        />
        <ReadOnly label="Campaign" value={draft.campaign_code ?? "None"} />
        <fieldset className="field">
          <legend>Parts</legend>
          {parts.fields.length ? (
            <ul className="parts m-0 grid list-none gap-2 p-0">
              {parts.fields.map((p, i) => (
                <li className="flex items-center gap-2" key={p.id}>
                  <span className="code flex-1">{p.part_number}</span>
                  <label className="sr-only" htmlFor={`wo-qty-${i}`}>Quantity of {p.part_number}</label>
                  <input
                    className="field-control w-[5.5em]"
                    disabled={ro}
                    id={`wo-qty-${i}`}
                    inputMode="numeric"
                    min={1}
                    type="number"
                    {...onInputToo(form.register(`parts.${i}.quantity`, { valueAsNumber: true }))}
                  />
                  {!ro && (
                    <Button onClick={() => parts.remove(i)} size="sm" type="button" variant="secondary">
                      Remove<span className="sr-only"> {p.part_number}</span>
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="hint">No parts.</p>
          )}
        </fieldset>
        <fieldset className="field checks grid gap-1">
          <legend>Also needed</legend>
          <label className="check flex min-h-tap items-center gap-2.5" htmlFor="wo-specialist">
            <input className="size-[26px] accent-brand" disabled={ro} id="wo-specialist" type="checkbox" {...form.register("needs_specialist")} />
            <span>A specialist</span>
          </label>
          <label className="check flex min-h-tap items-center gap-2.5" htmlFor="wo-return">
            <input className="size-[26px] accent-brand" disabled={ro} id="wo-return" type="checkbox" {...form.register("return_visit")} />
            <span>A return visit</span>
          </label>
        </fieldset>
        {draft.citations.length > 0 && (
          <div className="field readonly">
            <span className="field-label">Based on</span>
            <span className="chips inline-flex flex-wrap gap-1">
              {draft.citations.map((id, i) => (
                <a aria-label={`Source ${i + 1}`} className="chip justify-center" href={sourceHref(id)} key={id}>{i + 1}</a>
              ))}
            </span>
          </div>
        )}
      </form>

      {message && (
        <p className={`form-message ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</p>
      )}

      <div className="sticky-actions">
        {editable && <Button disabled={busy} onClick={save} type="button" variant="secondary">Save draft</Button>}
        {editable && needsApproval && (
          <Button disabled={busy || blocked} onClick={requestApproval} type="button">Request approval</Button>
        )}
        {((draft.status === "draft" && !needsApproval) || draft.status === "approved") && (
          <Button disabled={busy} onClick={openConfirm} type="button">Submit to {system}…</Button>
        )}
        {draft.status === "pending_approval" && (isApprover ? (
          <>
            <div className="field approver-note m-0 basis-full">
              <label htmlFor="wo-note">Note to the technician (optional)</label>
              <textarea className="field-control" disabled={busy} id="wo-note" onChange={onNote} onInput={onNote} rows={2} value={note} />
            </div>
            <Button disabled={busy} onClick={decide("approve", "Approving")} type="button">Approve</Button>
            <Button disabled={busy} onClick={decide("reject", "Rejecting")} type="button" variant="secondary">Reject</Button>
          </>
        ) : (
          <p className="hint">Waiting for a field team lead to approve. You can leave this screen.</p>
        ))}
      </div>

      <ConfirmSubmit
        assetId={draft.asset_id}
        onCancel={() => setConfirming(false)}
        onConfirm={submit}
        open={confirming}
        summary={form.getValues("summary") || draft.summary}
        system={system}
      />
    </>
  );
}

/** Where the draft stands: sent, rejected, approved, or why it needs approval and who can give it. */
function ApprovalBox({ draft, person, system }: { draft: WorkOrderDraft; person: (id: string) => string; system: string }) {
  const note = draft.decision_note ? <span className="decision-note mt-1 block font-semibold">Note: {draft.decision_note}</span> : null;
  const by = draft.decided_by ? ` by ${person(draft.decided_by)}` : "";
  if (draft.status === "submitted") {
    return (
      <div className="notice notice-bulletin" role="status">
        <strong className="notice-title"><Send aria-hidden className="icon" />Sent to {system}</strong>
        <span className="notice-text">Reference {draft.external_ref}</span>
      </div>
    );
  }
  if (draft.status === "rejected") {
    return (
      <div className="notice notice-not_visible" role="status">
        <strong className="notice-title"><CircleX aria-hidden className="icon" />Rejected</strong>
        <span className="notice-text">Rejected{by}. Edit it and request approval again.</span>
        {note}
      </div>
    );
  }
  if (draft.status === "approved") {
    return (
      <div className="notice notice-bulletin" role="status">
        <strong className="notice-title"><CircleCheck aria-hidden className="icon" />Approved</strong>
        <span className="notice-text">Approved{by}. You can submit it to {system}.</span>
        {note}
      </div>
    );
  }
  if (!draft.approval_reasons.length) return null;
  const blocked = draft.approval_reasons.includes("no eligible approver");
  const reasons = draft.approval_reasons.filter((r) => r !== "no eligible approver").map((r) => APPROVAL_REASON_WORDS[r] ?? r);
  const region = REGION_BY_SYSTEM[draft.target_system] ?? "this region";
  const approvers = draft.eligible_approvers ?? [];
  return (
    <div className={`notice ${blocked ? "notice-not_visible" : "notice-check_on_site"}`} role="note">
      <strong className="notice-title">{blocked ? <Ban aria-hidden className="icon" /> : <ShieldAlert aria-hidden className="icon" />}{blocked ? "No approver available" : "Needs approval"}</strong>
      <span className="notice-text">
        {reasons.length ? `Approval is needed because ${reasons.join(" and ")}. ` : ""}
        {blocked
          ? "No field team lead can approve this draft, so it can't be submitted. Call your team lead."
          : `A field team lead for ${region} must approve it before it goes to ${system}.`}
      </span>
      {!blocked && approvers.length > 0 && (
        <span className="approvers mt-1 block font-semibold">Can approve: {approvers.map(person).join(", ")}</span>
      )}
    </div>
  );
}
