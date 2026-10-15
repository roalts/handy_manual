// Development sign-in (FR-009): the test-user list from /api/dev/users, or a user ID field when
// the list isn't available (production answers 404).

import { ChevronRight, TriangleAlert } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Mark } from "@/components/Mark";
import { Button } from "@/components/ui/button";
import { groupWords } from "@/lib/text";
import type { DevUser } from "@/lib/types";

interface Props {
  users: DevUser[] | undefined;
  message: string | null;
  busy: boolean;
  onSignIn: (userId: string) => void;
}

/** Shown while signed out. `users` is undefined while the test-user list loads; an empty list shows the user ID field. */
export function SignIn({ users, message, busy, onSignIn }: Props) {
  const [userId, setUserId] = useState("");
  const onText = (e: FormEvent<HTMLInputElement>) => setUserId(e.currentTarget.value);
  return (
    <section aria-labelledby="signin-title" className="signin pt-4">
      <Mark className="mark brand-mark mb-3.5 size-11" />
      <h2 className="m-0 text-[27px] leading-tight tracking-[-0.02em]" id="signin-title" ref={(el) => el?.focus()} tabIndex={-1}>Sign in</h2>
      {message && (
        <p className="notice notice-check_on_site" role="alert">
          <span className="notice-title"><TriangleAlert aria-hidden className="icon" />{message}</span>
        </p>
      )}
      <p className="mt-2 text-ink-soft">Development sign-in: pick a test user.</p>
      {users === undefined ? (
        <p className="hint" role="status">Loading…</p>
      ) : users.length ? (
        <ul className="user-list m-0 mt-3 list-none p-0">
          {users.map((u) => (
            <li className="border-t border-line first:border-t-0" key={u.user_id}>
              <button
                className="btn user flex min-h-tap w-full cursor-pointer items-center gap-3 bg-transparent py-3 text-left text-ink disabled:opacity-55"
                disabled={busy}
                onClick={() => onSignIn(u.user_id)}
                type="button"
              >
                <span className="flex min-w-0 flex-1 flex-col">
                  <span><strong>{u.name}</strong> <span className="code text-ink-soft">{u.user_id}</span></span>
                  <span className="text-[15px] text-ink-soft">{u.title}</span>
                  <span className="text-[14px] text-ink-soft">{u.groups.map(groupWords).join(" · ")}</span>
                </span>
                <ChevronRight aria-hidden className="icon text-ink-soft" />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <form className="signin-form" onSubmit={(e) => { e.preventDefault(); onSignIn(userId.trim()); }}>
          <div className="field">
            <label htmlFor="signin-id">User ID</label>
            <input autoCapitalize="none" autoComplete="username" className="field-control" id="signin-id" onChange={onText} onInput={onText} required type="text" value={userId} />
          </div>
          <Button disabled={busy} type="submit">Sign in</Button>
        </form>
      )}
    </section>
  );
}
