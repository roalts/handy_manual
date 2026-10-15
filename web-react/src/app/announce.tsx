import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

const AnnounceContext = createContext<(text: string) => void>(() => {});

/** A polite live region for screen readers; announce() re-sets the text so repeats are read. */
export function AnnounceProvider({ children }: { children: ReactNode }) {
  const [text, setText] = useState("");
  const timer = useRef<number | undefined>(undefined);
  const announce = useCallback((next: string) => {
    setText("");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setText(next), 50);
  }, []);
  return (
    <AnnounceContext.Provider value={announce}>
      {children}
      <div aria-live="polite" className="sr-only" id="live">{text}</div>
    </AnnounceContext.Provider>
  );
}

/** announce() from the nearest AnnounceProvider; a no-op outside one. */
export const useAnnounce = () => useContext(AnnounceContext);
