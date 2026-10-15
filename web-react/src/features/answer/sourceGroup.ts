// The sources behind one citation control. Tapping it opens the first source; the source sheet
// shows a switcher for the rest. In memory only; a sheet opened from its own route has no group.

import { createContext, useContext } from "react";

export interface GroupItem {
  passageId: string;
  /** Citation number in the answer. */
  n: number;
  title: string;
  locator: string;
}

export const SourceGroupContext = createContext<(items: GroupItem[]) => void>(() => {});

/** Records the group a tapped citation opens; a no-op outside the provider. */
export const useOpenSourceGroup = () => useContext(SourceGroupContext);
