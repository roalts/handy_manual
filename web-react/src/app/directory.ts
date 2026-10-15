// Session, development user list and group descriptions.

import { useQuery } from "@tanstack/react-query";
import { getGroups, getSession, isApiError, listDevUsers } from "@/lib/api";
import { setGroupWords } from "@/lib/text";
import type { DevUser, Identity } from "@/lib/types";
import { keys } from "./query";

/** The signed-in user, null when signed out (401). Fetched once; sign-in and sign-out set it directly. */
export function useSession() {
  return useQuery<Identity | null>({
    queryKey: keys.session,
    queryFn: async () => {
      try {
        return await getSession();
      } catch (err) {
        if (isApiError(err) && err.status === 401) return null;
        throw err;
      }
    },
    staleTime: Infinity,
  });
}

/** Development only; production answers 404 and the sign-in screen falls back to a user ID field. */
export function useDevUsers() {
  return useQuery<DevUser[]>({
    queryKey: keys.devUsers,
    queryFn: async () => {
      try {
        return (await listDevUsers())?.users ?? [];
      } catch {
        return [];
      }
    },
    staleTime: Infinity,
  });
}

/** Loaded once per session; replaces the offline GROUP_WORDS fallback. */
export function useGroups(enabled: boolean) {
  return useQuery({
    queryKey: keys.groups,
    queryFn: async () => {
      const groups = await getGroups();
      setGroupWords(groups);
      return groups;
    },
    enabled,
    staleTime: Infinity,
  });
}
