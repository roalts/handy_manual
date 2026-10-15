import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Joins class names; on Tailwind conflicts the later class wins. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
