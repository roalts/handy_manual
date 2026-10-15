import type { ReactNode } from "react";

/** A labelled value laid out like a form field, for what the user can't edit. */
export function ReadOnly({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="field readonly">
      <span className="field-label">{label}</span>
      <span className="field-value block py-1">{value}</span>
    </div>
  );
}
