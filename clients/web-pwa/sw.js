// Minimal no-op service worker — present purely so the page qualifies as
// an installable PWA (manifest + a registered service worker). A call
// needs a live network connection anyway, so there's no offline caching
// story here worth building; this just passes every request straight
// through.
self.addEventListener("fetch", () => {});
