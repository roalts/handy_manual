// Draft from a suggestion with no machine (asset_id null): ask for the machine, then create.

import { useMutation } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { createDraft, isApiError } from "@/lib/api";
import { assetFieldError, groupWords, normalizeAssetId } from "@/lib/text";
import type { WorkOrderDraft } from "@/lib/types";
import { ReadOnly } from "./ReadOnly";
import type { PendingDraft } from "./DraftSheet";

/** Asks for the asset ID, then creates the draft; asset errors show on the field, others on the form. */
export function NewDraftForm({ pending, onCreated }: { pending: PendingDraft; onCreated: (d: WorkOrderDraft) => void }) {
  const s = pending.suggestion;
  const [assetId, setAssetId] = useState("");
  const [assetError, setAssetError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const create = useMutation({
    mutationFn: (id: string) => createDraft({ answer_id: pending.answerId, suggestion: s, asset_id: id }),
    onSuccess: onCreated,
    onError: (err, id) => {
      if (isApiError(err) && err.status === 401) return;
      const fieldError = assetFieldError(isApiError(err) ? err : null, id);
      setAssetError(fieldError);
      if (fieldError) input.current?.focus();
      else {
        setFormError(isApiError(err) && err.status === 0
          ? "No connection. Nothing was created; try again when you have signal."
          : "The draft couldn't be created. Nothing was sent. Try again.");
      }
    },
  });

  const submit = () => {
    // The DOM value, not state: an input event and a submit in the same tick (paste then Enter) would read stale state.
    const id = normalizeAssetId(input.current?.value ?? assetId);
    setAssetId(id);
    setFormError(null);
    if (!id) {
      setAssetError("Enter the machine's asset ID.");
      input.current?.focus();
      return;
    }
    setAssetError(null);
    create.mutate(id);
  };

  const onText = (e: React.FormEvent<HTMLInputElement>) => setAssetId(e.currentTarget.value);

  return (
    <>
      <div className="notice notice-check_on_site" role="note">
        <strong className="notice-title">Machine needed</strong>
        <span className="notice-text">The answer didn't name one machine. Enter the asset ID before the draft is created.</span>
      </div>
      <form aria-labelledby="draft-title" className="draft-form my-2.5" noValidate onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <div className={`field${assetError ? " invalid" : ""}`}>
          <label htmlFor="wo-asset">Machine (asset ID)</label>
          <input
            aria-describedby={assetError ? "wo-asset-hint wo-asset-error" : "wo-asset-hint"}
            aria-invalid={assetError ? true : undefined}
            autoCapitalize="characters"
            autoComplete="off"
            autoFocus
            className="field-control"
            disabled={create.isPending}
            enterKeyHint="go"
            id="wo-asset"
            onChange={onText}
            onInput={onText}
            placeholder="e.g. TAC-C-0142"
            ref={input}
            required
            spellCheck={false}
            type="text"
            value={assetId}
          />
          <p className="hint" id="wo-asset-hint">On the nameplate, for example TAC-C-0142.</p>
          {assetError && <p className="field-error" id="wo-asset-error" role="alert">{assetError}</p>}
        </div>
        <ReadOnly label="Summary" value={s.summary} />
        {s.fault_code && <ReadOnly label="Fault code" value={s.fault_code} />}
        <ReadOnly
          label="Certification needed"
          value={s.required_certification?.length ? s.required_certification.map((g) => `${g} (${groupWords(g)})`).join(", ") : "None"}
        />
        {s.campaign_code && <ReadOnly label="Campaign" value={s.campaign_code} />}
        <ReadOnly label="Parts" value={s.parts?.length ? s.parts.map((p) => `${p.part_number} × ${p.quantity ?? 1}`).join(", ") : "None"} />
        {formError && <p className="form-message error" role="alert">{formError}</p>}
        <div className="sticky-actions">
          <Button className="flex-auto" disabled={create.isPending} type="submit">{create.isPending ? "Creating…" : "Create draft"}</Button>
          <p className="hint">Creating a draft sends nothing to MaintPro or Servio.</p>
        </div>
      </form>
    </>
  );
}
