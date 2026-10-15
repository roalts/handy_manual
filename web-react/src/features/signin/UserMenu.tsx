// Avatar button in the header: a disclosure with the signed-in user and "Sign out". Escape, a tap
// outside or moving focus away closes it.

import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { groupWords } from "@/lib/text";
import type { Identity } from "@/lib/types";

/** Up to two initials, from the first two words of the name. */
const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("");

/** The avatar and its panel with the user's name, ID and groups; Escape returns focus to the avatar. */
export function UserMenu({ identity, onSignOut }: { identity: Identity; onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const outside = (e: Event) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", outside);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div className="user-bar relative" id="user-bar" ref={root}>
      <button
        aria-controls={panelId}
        aria-expanded={open}
        aria-label={`${identity.name}, account`}
        className="avatar inline-flex size-tap cursor-pointer items-center justify-center rounded-full"
        onClick={() => setOpen((o) => !o)}
        ref={button}
        type="button"
      >
        <span aria-hidden className="inline-flex size-8 items-center justify-center rounded-full bg-paper-soft text-[14px] font-bold text-ink">
          {initials(identity.name)}
        </span>
      </button>
      <div
        className="absolute top-full right-0 z-10 mt-1 w-[min(300px,calc(100vw-24px))] rounded-[var(--radius)] bg-background p-4 shadow-[0_8px_30px_rgb(0_0_0/0.18)] ring-1 ring-line"
        hidden={!open}
        id={panelId}
      >
        <p className="user-name m-0 font-semibold">{identity.name} <span className="code font-normal text-ink-soft">{identity.user_id}</span></p>
        {identity.groups.length > 0 && <p className="hint mt-1">{identity.groups.map(groupWords).join(" · ")}</p>}
        <Button className="mt-2 w-full" onClick={() => { setOpen(false); onSignOut(); }} type="button" variant="secondary">Sign out</Button>
      </div>
    </div>
  );
}
