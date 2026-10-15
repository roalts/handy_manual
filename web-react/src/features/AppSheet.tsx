// Bottom sheet over the answer (Vaul). Each sheet also has its own hash route, so closing it goes
// back in history, or to the ask screen when the page was opened on the sheet's route.

import { X } from "lucide-react";
import type { ReactNode } from "react";
import { Drawer, DrawerContent, DrawerTitle } from "@/components/ui/drawer";

interface Props {
  /** Visible title; also the dialog's accessible name. */
  title: ReactNode;
  /** Small line above the title, e.g. "Source 1 · Bulletin". */
  kicker?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  bodyId?: string;
}

/** Always open while mounted; dismissing it in any way (drag, scrim, Close) calls onClose. */
export function AppSheet({ title, kicker, onClose, children, bodyId = "sheet-body" }: Props) {
  return (
    <Drawer onOpenChange={(open) => !open && onClose()} open repositionInputs={false}>
      <DrawerContent aria-describedby={undefined} className="mx-auto max-w-[720px] bg-background">
        <div className="flex items-start justify-between gap-2 pt-1 pr-2 pl-4">
          <div className="min-w-0 py-1.5">
            {kicker && <p className="sheet-kicker m-0 text-[14px] text-ink-soft">{kicker}</p>}
            <DrawerTitle asChild>
              <h2 className="m-0 text-[22px] leading-tight">{title}</h2>
            </DrawerTitle>
          </div>
          <button aria-label="Close" className="inline-flex size-tap shrink-0 cursor-pointer items-center justify-center rounded-full text-ink hover:bg-paper-soft" onClick={onClose} type="button">
            <X aria-hidden className="size-5" />
          </button>
        </div>
        <div className="overflow-y-auto overscroll-contain px-4 pb-[max(16px,env(safe-area-inset-bottom))]" id={bodyId}>
          {children}
        </div>
      </DrawerContent>
    </Drawer>
  );
}
