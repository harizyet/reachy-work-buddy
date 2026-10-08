/** Leaves the app for an external address (Google sign-in). A function of its own so tests can observe it. */
export function goExternal(url: string): void {
  window.location.assign(url);
}
