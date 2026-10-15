// The editable fields of a draft (PATCH /api/work-orders/{id}); everything else is read-only.

import { z } from "zod";
import type { DraftEdits, WorkOrderDraft } from "@/lib/types";

export const draftFormSchema = z.object({
  fault_code: z.string().max(40),
  summary: z.string().trim().min(1, "The summary can't be empty."),
  work_steps: z.string(),
  priority: z.enum(["low", "medium", "high"]),
  parts: z.array(z.object({
    part_number: z.string().min(1),
    quantity: z.number({ error: "Enter a quantity." }).int().min(1, "At least 1."),
  })),
  needs_specialist: z.boolean(),
  return_visit: z.boolean(),
});

export type DraftFormValues = z.infer<typeof draftFormSchema>;

/** Form values for a draft: empty strings for missing text, medium priority, 1 for a part without a quantity. */
export function formFromDraft(d: WorkOrderDraft): DraftFormValues {
  return {
    fault_code: d.fault_code ?? "",
    summary: d.summary ?? "",
    work_steps: d.work_steps ?? "",
    priority: d.priority ?? "medium",
    parts: (d.parts ?? []).map((p) => ({ part_number: p.part_number, quantity: p.quantity ?? 1 })),
    needs_specialist: Boolean(d.needs_specialist),
    return_visit: Boolean(d.return_visit),
  };
}

/** The PATCH body for validated values; a blank fault code is sent as null. */
export function editsFrom(v: DraftFormValues): DraftEdits {
  return {
    fault_code: v.fault_code.trim() || null,
    summary: v.summary.trim(),
    work_steps: v.work_steps,
    priority: v.priority,
    parts: v.parts,
    needs_specialist: v.needs_specialist,
    return_visit: v.return_visit,
  };
}
