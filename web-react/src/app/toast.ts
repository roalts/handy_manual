// Sonner stays out of the first-load bundle; the Toaster is lazy in App and mounts right after the first screen.

/** Shows a toast; the first call also loads sonner. */
export function toast(message: string): void {
  void import("sonner").then((m) => m.toast(message));
}
