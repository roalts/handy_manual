// "Send to MaintPro/Servio?" (FR-006: explicit confirmation before anything leaves).

import {
  Confirmation, ConfirmationAction, ConfirmationActions, ConfirmationRequest, ConfirmationTitle,
} from "@/components/ai-elements/confirmation";
import { AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogTitle } from "@/components/ui/alert-dialog";

interface Props {
  open: boolean;
  system: string;
  assetId: string;
  summary: string;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Modal confirmation naming the system, machine and summary; closing it in any way cancels. */
export function ConfirmSubmit({ open, system, assetId, summary, onConfirm, onCancel }: Props) {
  return (
    <AlertDialog onOpenChange={(o) => !o && onCancel()} open={open}>
      <AlertDialogContent className="confirm w-[min(92vw,420px)] rounded-[22px] border-0 p-5">
        <AlertDialogTitle className="m-0 text-[22px] leading-tight">Send to {system}?</AlertDialogTitle>
        <AlertDialogDescription asChild>
          <div>
            <Confirmation>
              <ConfirmationTitle>This creates a work order in {system} for {assetId}:</ConfirmationTitle>
              <ConfirmationRequest>
                <p className="confirm-summary m-0 font-semibold">{summary}</p>
                <p className="hint">Nothing has been sent yet.</p>
              </ConfirmationRequest>
            </Confirmation>
          </div>
        </AlertDialogDescription>
        <ConfirmationActions>
          <ConfirmationAction onClick={onConfirm}>Send to {system}</ConfirmationAction>
          <ConfirmationAction onClick={onCancel} variant="secondary">Cancel</ConfirmationAction>
        </ConfirmationActions>
      </AlertDialogContent>
    </AlertDialog>
  );
}
